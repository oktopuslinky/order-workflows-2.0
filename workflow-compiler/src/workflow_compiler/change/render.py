"""Markdown renderers for the four change artifacts (deterministic, no LLM).

Each renderer projects one structured document to markdown whose heading
structure mirrors the manager's reference documents (reference digest §5):
EPIC sections are unnumbered H2s, user stories are one ``## US-00N: Title``
section each with ``### Story / Acceptance Criteria / Notes``, the TDD uses
``## N. Title`` / ``### 4.x Title`` with an **Existing** and a **Proposed**
part per section, and the impact analysis is numbered like a BCR. Every
artifact ends with a ``## Sources`` footer listing the knowledge-base files
(and line spans) it was grounded on.

:mod:`workflow_compiler.change.parse` reads the same markdown back; the two
modules are kept in lock-step and covered by round-trip tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from workflow_compiler.models.change import (
    TDD_CONTAINER_TITLE,
    EpicDoc,
    ImpactDoc,
    ImpactTableRow,
    SourceRef,
    StoriesDoc,
    StoryDoc,
    TddDoc,
)

SOURCES_HEADING = "Sources"
KG_APPENDIX_HEADING = "Appendix A — Knowledge-graph traversal (deterministic)"
DIAGRAMS_HEADING = "Diagrams Needed"
EXISTING = "Existing"
PROPOSED = "Proposed"

# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


def cell(text: str) -> str:
    """Escape a table cell: pipes and newlines cannot appear raw."""
    return text.replace("\r\n", "\n").replace("|", "\\|").replace("\n", "<br>").strip()


def one_line(text: str) -> str:
    """Collapse a bullet's text onto one line."""
    return " ".join(text.replace("\r\n", "\n").split("\n")).strip()


def table(columns: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(cell(c) for c in columns) + " |",
        "|" + "|".join(" --- " for _ in columns) + "|",
    ]
    for row in rows:
        values = [cell(str(v)) for v in row]
        values += [""] * (len(columns) - len(values))
        lines.append("| " + " | ".join(values[: len(columns)]) + " |")
    return lines


def bullets(items: Iterable[str], *, empty: str = "_None._") -> list[str]:
    out = [f"- {one_line(item)}" for item in items if one_line(item)]
    return out or [empty]


def checklist(
    items: Iterable[str], done: Sequence[bool] = (), *, empty: str = "_None._"
) -> list[str]:
    out: list[str] = []
    for i, item in enumerate(items):
        text = one_line(item)
        if not text:
            continue
        mark = "x" if i < len(done) and done[i] else " "
        out.append(f"- [{mark}] {text}")
    return out or [empty]


def meta(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """``**Label:** value`` lines, blank-separated so renderers keep them apart."""
    out: list[str] = []
    for label, value in pairs:
        if one_line(value):
            out += [f"**{label}:** {one_line(value)}", ""]
    return out[:-1] if out else out


def paragraphs(text: str, *, empty: str = "_To be determined._") -> list[str]:
    body = demote_headings(text.strip())
    return [body] if body else [empty]


def demote_headings(text: str) -> str:
    """Turn any markdown heading inside a body into bold text (outside code fences).

    Bodies are opaque prose from the model; a stray ``## Foo`` line inside one
    would break the section structure the parser relies on.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            rest = stripped[hashes:].strip()
            if rest:
                line = f"**{rest}**"
        out.append(line)
    return "\n".join(out)


def sources_footer(sources: Sequence[SourceRef]) -> list[str]:
    lines = ["", f"## {SOURCES_HEADING}", ""]
    if not sources:
        lines.append("_No knowledge-base sources were retrieved for this artifact._")
        return lines
    for src in sources:
        if src.spans:
            spans = ", ".join(f"lines {a}-{b}" for a, b in src.spans)
            lines.append(f"- `{src.path}` — {spans}")
        else:
            lines.append(f"- `{src.path}`")
    return lines


def coverage_line(note: str) -> list[str]:
    return [f"> {one_line(note)}", ""] if one_line(note) else []


def _h1(*parts: str) -> str:
    return "# " + " — ".join(p.strip() for p in parts if p and p.strip())


# --------------------------------------------------------------------------- #
# Impact analysis
# --------------------------------------------------------------------------- #


def kg_rows_table(rows: Sequence[ImpactTableRow]) -> list[str]:
    return table(
        ("Hops", "Type", "Node", "Path", "Via"),
        ((str(r.hops), r.type, r.name, r.path or "", r.via) for r in rows),
    )


def render_impact(doc: ImpactDoc) -> str:
    lines: list[str] = [_h1("Impact Analysis", doc.cr_id, doc.title), ""]
    lines += meta(
        [
            ("Change Request", doc.cr_id),
            ("Target Workflow", doc.target_workflow),
            ("Knowledge Base", doc.kb_name),
            ("Status", doc.status),
        ]
    )
    lines.append("")
    lines += coverage_line(doc.coverage_note)
    lines += ["## 1. Change Summary", "", *paragraphs(doc.summary), ""]
    lines += ["## 2. Requirements Assessment", ""]
    lines += table(
        ("Req ID", "Requirement", "Impact"),
        ((r.req_id, r.requirement, r.impact) for r in doc.requirements),
    )
    lines += ["", "## 3. Affected Components", ""]
    lines += table(
        ("Kind", "Component", "Change", "Rationale", "KG reference"),
        ((a.kind, a.ref, a.change_type, a.rationale, a.kg_ref) for a in doc.affected),
    )
    lines += ["", "## 4. Impact on Existing Design", "", *bullets(doc.design_impacts), ""]
    lines += ["## 5. Risks & Assumptions", "", *bullets(doc.risks), ""]
    lines += ["## 6. Open Decisions", "", *checklist(doc.open_decisions), ""]
    lines += [f"## {KG_APPENDIX_HEADING}", ""]
    if doc.kg_rows:
        lines += kg_rows_table(doc.kg_rows)
    else:
        lines.append("_No traversal rows._")
    lines += sources_footer(doc.sources)
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# EPIC
# --------------------------------------------------------------------------- #


def render_epic(doc: EpicDoc) -> str:
    lines: list[str] = [_h1(doc.id, doc.title), ""]
    lines += meta(
        [
            ("Epic Owner", doc.owner),
            ("Linked BRD", doc.linked_brd),
            ("Linked BCR", doc.linked_bcr),
            ("Status", doc.status),
            ("Target Release", doc.target_release),
        ]
    )
    lines.append("")
    lines += coverage_line(doc.coverage_note)
    lines += ["## Epic Statement", "", *paragraphs(doc.statement), ""]
    lines += ["## Business Value", "", *bullets(doc.value), ""]
    lines += ["## In-Scope Capabilities", "", *bullets(doc.capabilities), ""]
    lines += ["## Definition of Done", "", *checklist(doc.dod, doc.dod_done), ""]
    lines += ["## Story Map", ""]
    lines += table(
        ("Story ID", "Title", "Status", "Doc"),
        ((s.id, s.title, s.status, s.doc) for s in doc.story_map),
    )
    lines += ["", "## Non-Functional Requirements", ""]
    lines += table(("NFR", "Target"), ((n.nfr, n.target) for n in doc.nfrs))
    lines += ["", "## Dependencies", "", *bullets(doc.dependencies), ""]
    lines += ["## Risks", ""]
    lines += table(("Risk", "Mitigation"), ((r.risk, r.mitigation) for r in doc.risks))
    lines += sources_footer(doc.sources)
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# User stories
# --------------------------------------------------------------------------- #


def render_story(story: StoryDoc, *, level: int = 2) -> list[str]:
    h = "#" * level
    sub = "#" * (level + 1)
    lines: list[str] = [f"{h} {story.id}: {one_line(story.title)}", ""]
    lines += meta(
        [
            ("Epic", story.epic),
            ("Status", story.status),
            ("Story Points", str(story.points) if story.points else ""),
            ("Implements", ", ".join(story.implements)),
        ]
    )
    lines.append("")
    lines += [f"{sub} Story", ""]
    lines += [one_line(story.as_a), one_line(story.i_want), one_line(story.so_that), ""]
    lines += [f"{sub} Acceptance Criteria", "", *checklist(story.acceptance), ""]
    lines += [f"{sub} Notes", "", *paragraphs(story.notes, empty="_None._"), ""]
    return lines


def render_stories(doc: StoriesDoc) -> str:
    lines: list[str] = [_h1("User Stories", doc.epic_id, doc.epic_title), ""]
    lines += meta(
        [
            ("Epic", " — ".join(p for p in (doc.epic_id, doc.epic_title) if p)),
            ("Linked BCR", doc.linked_bcr),
            ("Stories", str(len(doc.stories))),
        ]
    )
    lines.append("")
    lines += coverage_line(doc.coverage_note)
    for story in doc.stories:
        lines += render_story(story)
    lines += sources_footer(doc.sources)
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# TDD
# --------------------------------------------------------------------------- #


def render_tdd(doc: TddDoc) -> str:
    lines: list[str] = [_h1(doc.id, doc.title), ""]
    lines += meta(
        [
            ("Document ID", doc.id),
            ("Linked EPIC", doc.linked_epic),
            ("Supersedes", doc.supersedes),
            ("Version", doc.version),
            ("Status", doc.status),
            ("Author", doc.author),
        ]
    )
    lines.append("")
    lines += coverage_line(doc.coverage_note)
    container_open = False
    for section in doc.sections:
        is_sub = "." in section.number
        if is_sub and not container_open:
            lines += [f"## {TDD_CONTAINER_TITLE}", ""]
            container_open = True
        if is_sub:
            lines += [f"### {section.number} {section.title}", ""]
            lines += [f"#### {EXISTING}", "", *paragraphs(section.existing), ""]
            lines += [f"#### {PROPOSED}", "", *paragraphs(section.proposed), ""]
        else:
            lines += [f"## {section.number}. {section.title}", ""]
            lines += [f"### {EXISTING}", "", *paragraphs(section.existing), ""]
            lines += [f"### {PROPOSED}", "", *paragraphs(section.proposed), ""]
    lines += [f"## {DIAGRAMS_HEADING}", "", *bullets(doc.diagrams_needed), ""]
    lines += sources_footer(doc.sources)
    return "\n".join(lines).rstrip() + "\n"
