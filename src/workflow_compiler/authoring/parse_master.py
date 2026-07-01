"""Parse an edited master document back into structured pieces for re-authoring.

Where :func:`~workflow_compiler.authoring.split.split_master` produces clean
per-workflow documents for compilation (dropping all helper blocks), this parser is
for the **re-author** round: it keeps the human's ``## Notes to the compiler``,
per-workflow ``### Guidance``, and ``### Open questions`` so they can guide the next
extraction pass and be carried forward into the regenerated document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from workflow_compiler.authoring.split import slugify

_H1 = re.compile(r"^# (?P<title>.+?)\s*$")
_INVOKES = re.compile(r"invokes\s+`(?P<name>[^`]+)`")
_HELPER_TITLES = {"guidance", "open questions", "readiness gaps"}


@dataclass
class ParsedWorkflow:
    """One workflow parsed out of an edited master document."""

    name: str
    slug: str
    ideal_content: str
    guidance: str = ""
    open_questions: list[str] = field(default_factory=list)
    invokes: list[str] = field(default_factory=list)


@dataclass
class ParsedMaster:
    """The whole edited master document, decomposed."""

    global_notes: str
    workflows: list[ParsedWorkflow]


def _clean_comment_lines(lines: list[str]) -> str:
    """Join lines, dropping HTML comments and the ``_(placeholder)_`` markers."""
    text = "\n".join(lines)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    kept = [
        ln for ln in text.splitlines()
        if ln.strip() and not re.fullmatch(r"_\(.*\)_", ln.strip())
    ]
    return "\n".join(kept).strip()


def _extract_h2_block(preamble: list[str], title: str) -> str:
    """Return the body under a ``## <title>`` heading in the preamble."""
    lower = title.lower()
    body: list[str] = []
    capturing = False
    for line in preamble:
        if line.startswith("## "):
            capturing = line[3:].strip().lower() == lower
            continue
        if capturing and (line.startswith("# ") or line.startswith("## ")):
            break
        if capturing:
            body.append(line)
    return _clean_comment_lines(body)


def _split_section(block: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Split a workflow section into (ideal-content lines, {helper-title: lines})."""
    ideal: list[str] = []
    helpers: dict[str, list[str]] = {}
    current: str | None = None
    for line in block:
        if line.startswith("### "):
            title = line[4:].strip().lower()
            current = title if title in _HELPER_TITLES else None
            if current is not None:
                helpers.setdefault(current, [])
                continue
        if line.startswith("## ") or line.startswith("# "):
            current = None
        if current is None:
            ideal.append(line)
        else:
            helpers[current].append(line)
    return ideal, helpers


def parse_master(master_text: str) -> ParsedMaster:
    """Decompose an edited master document into notes + per-workflow parts."""
    lines = master_text.splitlines()
    boundaries = [i for i, line in enumerate(lines) if _H1.match(line)]
    preamble = lines[: boundaries[0]] if boundaries else lines
    global_notes = _extract_h2_block(preamble, "Notes to the compiler")

    workflows: list[ParsedWorkflow] = []
    for pos, start in enumerate(boundaries):
        end = boundaries[pos + 1] if pos + 1 < len(boundaries) else len(lines)
        block = lines[start:end]
        title = _H1.match(block[0]).group("title")  # type: ignore[union-attr]
        ideal_lines, helpers = _split_section(block)
        ideal_content = "\n".join(ideal_lines).strip() + "\n"
        guidance = _clean_comment_lines(helpers.get("guidance", []))
        open_qs = [
            ln.strip()[1:].strip()
            for ln in helpers.get("open questions", [])
            if ln.strip().startswith("-")
        ]
        invokes = [m.group("name") for m in _INVOKES.finditer(ideal_content)]
        workflows.append(
            ParsedWorkflow(
                name=title,
                slug=slugify(title),
                ideal_content=ideal_content,
                guidance=guidance,
                open_questions=open_qs,
                invokes=list(dict.fromkeys(invokes)),
            )
        )
    return ParsedMaster(global_notes=global_notes, workflows=workflows)
