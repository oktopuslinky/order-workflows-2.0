"""Deterministic parser for workflow edit-request documents.

Parses the structured skeleton of an edit request (see
``docs/EDIT_FORMAT_GUIDE.md``) — headings, per-workflow sections, change
blocks — and fails fast with actionable errors **before any LLM call**. The
natural-language bullet entries inside each block stay opaque strings; the
:class:`~workflow_compiler.agents.edit_interpreter.EditInterpreterAgent`
translates those.

Like ``spec/ingest.py``, this module is pure and deterministic: same input,
same output, no I/O, no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from workflow_compiler.exceptions import CompilationError

#: Allowed ``###`` change-block titles inside a ``## Workflow:`` section.
ALLOWED_BLOCKS = ("Add", "Modify", "Remove", "Triggers", "Dependencies")

#: Reserved for a future release — recognized and rejected explicitly.
_RESERVED_H2 = re.compile(r"^##\s+(Split Workflow|Merge Workflows)\b(.*)$", re.IGNORECASE)

_H1_RE = re.compile(r"^#\s+Edit Request\s*$", re.IGNORECASE)
_WORKFLOW_H2 = re.compile(r"^##\s+Workflow:\s*(?P<slug>\S+)\s*$", re.IGNORECASE)
_ADD_WORKFLOW_H2 = re.compile(r"^##\s+Add Workflow:\s*(?P<slug>\S+)\s*$", re.IGNORECASE)
_REMOVE_WORKFLOW_H2 = re.compile(r"^##\s+Remove Workflow:\s*(?P<slug>\S+)\s*$", re.IGNORECASE)
_PROJECT_H2 = re.compile(r"^##\s+Project\s*$", re.IGNORECASE)
_REASON_H2 = re.compile(r"^##\s+Reason\s*$", re.IGNORECASE)
_ANY_H2 = re.compile(r"^##\s+")
_H3_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.+)$")


@dataclass
class WorkflowEditSection:
    """The change blocks targeting one existing workflow."""

    slug: str
    blocks: dict[str, list[str]] = field(default_factory=dict)

    def entry_count(self) -> int:
        return sum(len(entries) for entries in self.blocks.values())

    def to_markdown(self) -> str:
        """Re-render the section's blocks (the interpreter's prompt input)."""
        lines: list[str] = []
        for title, entries in self.blocks.items():
            if not entries:
                continue
            lines.append(f"### {title}")
            lines.extend(f"- {entry}" for entry in entries)
            lines.append("")
        return "\n".join(lines).strip()


@dataclass
class NewWorkflowSection:
    """A whole new workflow described in natural language."""

    slug: str
    body: str


@dataclass
class EditRequestDoc:
    """The parsed skeleton of one edit-request document."""

    project_bullets: list[str] = field(default_factory=list)
    workflows: list[WorkflowEditSection] = field(default_factory=list)
    add_workflows: list[NewWorkflowSection] = field(default_factory=list)
    remove_workflows: list[str] = field(default_factory=list)
    reason: str | None = None

    def is_empty(self) -> bool:
        """True when the document requests no change at all."""
        return (
            not self.project_bullets
            and not self.add_workflows
            and not self.remove_workflows
            and all(section.entry_count() == 0 for section in self.workflows)
        )


def _bullets(lines: list[str]) -> list[str]:
    """Top-level bullet entries in ``lines``; continuation lines are folded in.

    A bullet's entry continues until the next top-level bullet or blank-line
    separated non-bullet content — indented sub-bullets and wrapped lines stay
    part of the entry so the interpreter sees the whole statement.
    """
    entries: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        match = _BULLET_RE.match(line)
        if match and not raw.startswith((" ", "\t")):
            entries.append(match.group("text").strip())
        elif entries:
            entries[-1] += " " + line.strip().lstrip("-*").strip()
    return entries


def parse_edit_request(markdown: str, known_slugs: set[str]) -> EditRequestDoc:
    """Parse ``markdown`` into an :class:`EditRequestDoc`, validating structure.

    Raises :class:`CompilationError` on any structural problem: wrong H1,
    unknown workflow slug, unknown change block, duplicate sections, add/remove
    slug conflicts, reserved split/merge syntax, or a document with no changes.
    """
    lines = markdown.splitlines()

    # -- locate and check the H1 --------------------------------------------
    h1_index = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("#")), None
    )
    if h1_index is None or not _H1_RE.match(lines[h1_index].strip()):
        raise CompilationError(
            "An edit request must start with the H1 title '# Edit Request'."
        )

    # -- split into H2 sections ----------------------------------------------
    # Only *recognized* H2 headings start a new section: the body of an
    # '## Add Workflow:' section is a full workflow document and legitimately
    # contains its own H2 headings ('## Purpose', '## Process', …).
    recognized = (
        _WORKFLOW_H2,
        _ADD_WORKFLOW_H2,
        _REMOVE_WORKFLOW_H2,
        _PROJECT_H2,
        _REASON_H2,
        _RESERVED_H2,
    )
    doc = EditRequestDoc()
    seen_workflow_slugs: set[str] = set()
    sections: list[tuple[str, list[str]]] = []  # (heading line, body lines)
    current_heading: str | None = None
    current_body: list[str] | None = None
    for line in lines[h1_index + 1 :]:
        stripped = line.strip()
        is_recognized = _ANY_H2.match(stripped) and any(
            p.match(stripped) for p in recognized
        )
        in_add_body = current_heading is not None and _ADD_WORKFLOW_H2.match(
            current_heading
        )
        if is_recognized or (_ANY_H2.match(stripped) and not in_add_body):
            current_heading = stripped
            current_body = []
            sections.append((stripped, current_body))
        elif current_body is not None:
            current_body.append(line)

    sorted_slugs = ", ".join(sorted(known_slugs)) or "(none)"
    for heading, body in sections:
        reserved = _RESERVED_H2.match(heading)
        if reserved:
            raise CompilationError(
                f"'{reserved.group(1)}' is reserved for a future release and is "
                "not yet supported. Remove the section to proceed."
            )
        wf = _WORKFLOW_H2.match(heading)
        if wf:
            slug = wf.group("slug")
            if slug not in known_slugs:
                raise CompilationError(
                    f"Unknown workflow slug '{slug}' in '## Workflow:' section. "
                    f"Known workflows: {sorted_slugs}."
                )
            if slug in seen_workflow_slugs:
                raise CompilationError(
                    f"Duplicate '## Workflow: {slug}' section — merge the two "
                    "sections into one."
                )
            seen_workflow_slugs.add(slug)
            doc.workflows.append(_parse_workflow_section(slug, body))
            continue
        add_wf = _ADD_WORKFLOW_H2.match(heading)
        if add_wf:
            slug = add_wf.group("slug")
            if slug in known_slugs:
                raise CompilationError(
                    f"Cannot add workflow '{slug}': the slug already exists. "
                    "Use a '## Workflow:' section to edit it instead."
                )
            if any(s.slug == slug for s in doc.add_workflows):
                raise CompilationError(f"Duplicate '## Add Workflow: {slug}' section.")
            text = "\n".join(body).strip()
            if not text:
                raise CompilationError(
                    f"'## Add Workflow: {slug}' has an empty body — describe the "
                    "new workflow (see docs/DOCUMENT_FORMAT_GUIDE.md)."
                )
            doc.add_workflows.append(NewWorkflowSection(slug=slug, body=text))
            continue
        remove_wf = _REMOVE_WORKFLOW_H2.match(heading)
        if remove_wf:
            slug = remove_wf.group("slug")
            if slug not in known_slugs:
                raise CompilationError(
                    f"Cannot remove workflow '{slug}': no such slug. "
                    f"Known workflows: {sorted_slugs}."
                )
            if slug in doc.remove_workflows:
                raise CompilationError(f"Duplicate '## Remove Workflow: {slug}' section.")
            doc.remove_workflows.append(slug)
            continue
        if _PROJECT_H2.match(heading):
            doc.project_bullets.extend(_bullets(body))
            continue
        if _REASON_H2.match(heading):
            doc.reason = "\n".join(body).strip() or None
            continue
        raise CompilationError(
            f"Unrecognized section {heading!r}. Allowed: '## Project', "
            "'## Workflow: <slug>', '## Add Workflow: <slug>', "
            "'## Remove Workflow: <slug>', '## Reason'."
        )

    # -- cross-section conflicts ---------------------------------------------
    conflict = seen_workflow_slugs.intersection(doc.remove_workflows)
    if conflict:
        raise CompilationError(
            f"Workflow(s) {sorted(conflict)} are both edited and removed in the "
            "same request — pick one."
        )

    if doc.is_empty():
        raise CompilationError("The edit request contains no changes.")
    return doc


def _parse_workflow_section(slug: str, body: list[str]) -> WorkflowEditSection:
    """Parse the ``###`` change blocks of one ``## Workflow:`` section."""
    section = WorkflowEditSection(slug=slug)
    current_block: list[str] | None = None
    pending: dict[str, list[str]] = {}
    for line in body:
        h3 = _H3_RE.match(line)
        if h3:
            title = h3.group("title").strip().title()
            if title not in ALLOWED_BLOCKS:
                allowed = ", ".join(ALLOWED_BLOCKS)
                raise CompilationError(
                    f"Unknown change block '### {h3.group('title')}' under "
                    f"'## Workflow: {slug}'. Allowed blocks: {allowed}."
                )
            if title in pending:
                raise CompilationError(
                    f"Duplicate '### {title}' block under '## Workflow: {slug}'."
                )
            current_block = []
            pending[title] = current_block
        elif current_block is not None:
            current_block.append(line)
        elif line.strip():
            raise CompilationError(
                f"Content under '## Workflow: {slug}' must live inside a "
                f"'###' change block ({', '.join(ALLOWED_BLOCKS)}); found: "
                f"{line.strip()!r}."
            )
    section.blocks = {title: _bullets(block) for title, block in pending.items()}
    return section
