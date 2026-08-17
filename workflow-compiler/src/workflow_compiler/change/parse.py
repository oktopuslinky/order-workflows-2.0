"""Parse change-artifact markdown back into the structured documents.

The inverse of :mod:`workflow_compiler.change.render`. Parsing is lenient about
prose (bodies are kept verbatim) and strict about structure (headings, tables,
checklists, the ``## Sources`` footer), because later phases need exactly the
structured bits — story ids/titles/acceptance criteria, the TDD sections, the
affected-components table — and never re-extract them with a model.

Human edits and chat revisions go through these parsers too: an artifact whose
title heading is missing is rejected (:class:`ArtifactParseError`), anything
else degrades to empty fields rather than failing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.models.change import (
    TDD_SECTIONS,
    AffectedItem,
    EpicDoc,
    ImpactDoc,
    ImpactTableRow,
    NfrRow,
    RequirementImpact,
    RiskRow,
    SourceRef,
    StoriesDoc,
    StoryDoc,
    StoryMapRow,
    TddDoc,
    TddSection,
)

from .render import (
    DIAGRAMS_HEADING,
    EXISTING,
    KG_APPENDIX_HEADING,
    PROPOSED,
    SOURCES_HEADING,
)


class ArtifactParseError(CompilationError):
    """The markdown does not have the structure of the artifact it claims to be."""


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_META = re.compile(r"^\*\*([^*]+?):\*\*\s*(.*)$")
_CHECK = re.compile(r"^[-*]\s+\[( |x|X)\]\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(?!\[[ xX]\]\s)(.*)$")
_SOURCE = re.compile(r"^[-*]\s+`([^`]+)`(?:\s+—\s+(.*))?$")
_SPAN = re.compile(r"lines?\s+(\d+)\s*[–-]\s*(\d+)")
_EMPTY_MARKERS = {"_None._", "_To be determined._", "_No traversal rows._"}


@dataclass
class Section:
    level: int
    title: str
    body: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.body).strip()


def split_sections(markdown: str) -> list[Section]:
    """Flatten the document into headed sections (level 0 = preamble).

    Headings inside fenced code blocks are body text, not structure.
    """
    sections: list[Section] = [Section(level=0, title="")]
    in_fence = False
    for line in markdown.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            sections[-1].body.append(line)
            continue
        match = None if in_fence else _HEADING.match(line)
        if match:
            sections.append(Section(level=len(match.group(1)), title=match.group(2).strip()))
        else:
            sections[-1].body.append(line)
    return sections


def _title_parts(sections: Sequence[Section]) -> list[str]:
    for section in sections:
        if section.level == 1:
            return [p.strip() for p in section.title.split(" — ")]
    raise ArtifactParseError("The artifact has no title heading (`# …`).")


def _meta_of(sections: Sequence[Section]) -> dict[str, str]:
    """``**Label:** value`` lines from the preamble/title section."""
    out: dict[str, str] = {}
    for section in sections:
        if section.level > 1:
            break
        for line in section.body:
            match = _META.match(line.strip())
            if match:
                out[match.group(1).strip().lower()] = match.group(2).strip()
    return out


def _coverage_of(sections: Sequence[Section]) -> str:
    for section in sections:
        if section.level > 1:
            break
        for line in section.body:
            if line.strip().startswith("> "):
                return line.strip()[2:].strip()
    return ""


def _find(sections: Sequence[Section], title: str, *, level: int | None = None) -> Section | None:
    wanted = _norm(title)
    for section in sections:
        if level is not None and section.level != level:
            continue
        if _norm(section.title) == wanted:
            return section
    return None


def _norm(title: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", title).strip().lower()


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    cells = re.split(r"(?<!\\)\|", inner)
    return [c.strip().replace("\\|", "|").replace("<br>", "\n") for c in cells]


def parse_table(body: str) -> tuple[list[str], list[list[str]]]:
    """First pipe table in ``body`` → (columns, rows). Missing → ([], [])."""
    lines = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    columns = _split_row(lines[0])
    rows: list[list[str]] = []
    for line in lines[2:]:
        values = _split_row(line)
        values += [""] * (len(columns) - len(values))
        rows.append(values[: len(columns)])
    return columns, rows


def parse_bullets(body: str) -> list[str]:
    out: list[str] = []
    for line in body.splitlines():
        match = _BULLET.match(line.strip())
        if match and match.group(1).strip() not in _EMPTY_MARKERS:
            out.append(match.group(1).strip())
    return out


def parse_checklist(body: str) -> tuple[list[str], list[bool]]:
    items: list[str] = []
    done: list[bool] = []
    for line in body.splitlines():
        match = _CHECK.match(line.strip())
        if match:
            items.append(match.group(2).strip())
            done.append(match.group(1).lower() == "x")
    return items, done


def parse_paragraph(body: str) -> str:
    text = body.strip()
    return "" if text in _EMPTY_MARKERS else text


def parse_sources(sections: Sequence[Section]) -> list[SourceRef]:
    section = _find(sections, SOURCES_HEADING, level=2)
    if section is None:
        return []
    out: list[SourceRef] = []
    for line in section.body:
        match = _SOURCE.match(line.strip())
        if not match:
            continue
        spans = [(int(a), int(b)) for a, b in _SPAN.findall(match.group(2) or "")]
        out.append(SourceRef(path=match.group(1), spans=spans))
    return out


def _body_between(sections: Sequence[Section], start: int, *, min_level: int) -> str:
    """Body of ``sections[start]`` plus any deeper sections until the next peer."""
    parts = [sections[start].text]
    for section in sections[start + 1 :]:
        if section.level <= min_level:
            break
        parts.append("#" * section.level + " " + section.title)
        parts.append(section.text)
    return "\n".join(p for p in parts if p).strip()


# --------------------------------------------------------------------------- #
# Impact
# --------------------------------------------------------------------------- #


def parse_impact(markdown: str) -> ImpactDoc:
    sections = split_sections(markdown)
    parts = _title_parts(sections)
    if not parts or not parts[0].lower().startswith("impact analysis"):
        raise ArtifactParseError("Expected a `# Impact Analysis — …` title.")
    meta = _meta_of(sections)
    doc = ImpactDoc(
        cr_id=meta.get("change request", parts[1] if len(parts) > 1 else ""),
        title=" — ".join(parts[2:]) if len(parts) > 2 else "",
        target_workflow=meta.get("target workflow", ""),
        kb_name=meta.get("knowledge base", ""),
        status=meta.get("status", "Draft"),
        coverage_note=_coverage_of(sections),
        sources=parse_sources(sections),
    )
    if (s := _find(sections, "Change Summary", level=2)) is not None:
        doc.summary = parse_paragraph(s.text)
    if (s := _find(sections, "Requirements Assessment", level=2)) is not None:
        _, rows = parse_table(s.text)
        doc.requirements = [
            RequirementImpact(req_id=r[0], requirement=r[1], impact=r[2]) for r in rows
        ]
    if (s := _find(sections, "Affected Components", level=2)) is not None:
        _, rows = parse_table(s.text)
        doc.affected = [
            AffectedItem(kind=r[0], ref=r[1], change_type=r[2], rationale=r[3], kg_ref=r[4])
            for r in rows
        ]
    if (s := _find(sections, "Impact on Existing Design", level=2)) is not None:
        doc.design_impacts = parse_bullets(s.text)
    if (s := _find(sections, "Risks & Assumptions", level=2)) is not None:
        doc.risks = parse_bullets(s.text)
    if (s := _find(sections, "Open Decisions", level=2)) is not None:
        doc.open_decisions, _ = parse_checklist(s.text)
    if (s := _find(sections, KG_APPENDIX_HEADING, level=2)) is not None:
        _, rows = parse_table(s.text)
        doc.kg_rows = [
            ImpactTableRow(
                hops=int(r[0]) if r[0].isdigit() else 0,
                type=r[1],
                name=r[2],
                path=r[3] or None,
                via=r[4],
                node_id=r[2],
            )
            for r in rows
        ]
    return doc


# --------------------------------------------------------------------------- #
# EPIC
# --------------------------------------------------------------------------- #


def parse_epic(markdown: str) -> EpicDoc:
    sections = split_sections(markdown)
    parts = _title_parts(sections)
    meta = _meta_of(sections)
    doc = EpicDoc(
        id=parts[0],
        title=" — ".join(parts[1:]),
        owner=meta.get("epic owner", ""),
        linked_brd=meta.get("linked brd", ""),
        linked_bcr=meta.get("linked bcr", ""),
        status=meta.get("status", "Proposed"),
        target_release=meta.get("target release", ""),
        coverage_note=_coverage_of(sections),
        sources=parse_sources(sections),
    )
    if (s := _find(sections, "Epic Statement", level=2)) is not None:
        doc.statement = parse_paragraph(s.text)
    if (s := _find(sections, "Business Value", level=2)) is not None:
        doc.value = parse_bullets(s.text)
    if (s := _find(sections, "In-Scope Capabilities", level=2)) is not None:
        doc.capabilities = parse_bullets(s.text)
    if (s := _find(sections, "Definition of Done", level=2)) is not None:
        doc.dod, doc.dod_done = parse_checklist(s.text)
    if (s := _find(sections, "Story Map", level=2)) is not None:
        _, rows = parse_table(s.text)
        doc.story_map = [StoryMapRow(id=r[0], title=r[1], status=r[2], doc=r[3]) for r in rows]
    if (s := _find(sections, "Non-Functional Requirements", level=2)) is not None:
        _, rows = parse_table(s.text)
        doc.nfrs = [NfrRow(nfr=r[0], target=r[1]) for r in rows]
    if (s := _find(sections, "Dependencies", level=2)) is not None:
        doc.dependencies = parse_bullets(s.text)
    if (s := _find(sections, "Risks", level=2)) is not None:
        _, rows = parse_table(s.text)
        doc.risks = [RiskRow(risk=r[0], mitigation=r[1]) for r in rows]
    return doc


# --------------------------------------------------------------------------- #
# Stories
# --------------------------------------------------------------------------- #

_STORY_TITLE = re.compile(r"^(US-\d+)\s*[:—-]\s*(.*)$")


def _parse_story(sections: Sequence[Section], start: int) -> StoryDoc:
    head = sections[start]
    match = _STORY_TITLE.match(head.title)
    assert match is not None
    story = StoryDoc(id=match.group(1), title=match.group(2).strip())
    for line in head.body:
        m = _META.match(line.strip())
        if not m:
            continue
        label, value = m.group(1).strip().lower(), m.group(2).strip()
        if label == "epic":
            story.epic = value
        elif label == "status":
            story.status = value
        elif label == "story points":
            story.points = int(value) if value.isdigit() else 0
        elif label == "implements":
            story.implements = [v.strip() for v in value.split(",") if v.strip()]
    for section in sections[start + 1 :]:
        if section.level <= head.level:
            break
        title = _norm(section.title)
        if title == "story":
            lines = [ln.strip() for ln in section.body if ln.strip()]
            for ln in lines:
                low = ln.lower()
                if low.startswith("as ") and not story.as_a:
                    story.as_a = ln
                elif low.startswith("i want") and not story.i_want:
                    story.i_want = ln
                elif low.startswith("so that") and not story.so_that:
                    story.so_that = ln
        elif title == "acceptance criteria":
            story.acceptance, _ = parse_checklist(section.text)
            if not story.acceptance:
                story.acceptance = parse_bullets(section.text)
        elif title == "notes":
            story.notes = parse_paragraph(section.text)
    return story


def parse_stories(markdown: str) -> StoriesDoc:
    sections = split_sections(markdown)
    parts = _title_parts(sections)
    meta = _meta_of(sections)
    doc = StoriesDoc(
        epic_id=parts[1] if len(parts) > 1 else "",
        epic_title=" — ".join(parts[2:]) if len(parts) > 2 else "",
        linked_bcr=meta.get("linked bcr", ""),
        coverage_note=_coverage_of(sections),
        sources=parse_sources(sections),
    )
    for i, section in enumerate(sections):
        if section.level == 2 and _STORY_TITLE.match(section.title):
            doc.stories.append(_parse_story(sections, i))
    return doc


# --------------------------------------------------------------------------- #
# TDD
# --------------------------------------------------------------------------- #

_TDD_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")


def parse_tdd(markdown: str) -> TddDoc:
    sections = split_sections(markdown)
    parts = _title_parts(sections)
    meta = _meta_of(sections)
    doc = TddDoc(
        id=meta.get("document id", parts[0]),
        title=" — ".join(parts[1:]),
        linked_epic=meta.get("linked epic", ""),
        supersedes=meta.get("supersedes", ""),
        version=meta.get("version", "0.1"),
        status=meta.get("status", "Draft"),
        author=meta.get("author", ""),
        coverage_note=_coverage_of(sections),
        sources=parse_sources(sections),
    )
    keys = {(number, title.lower()): key for key, number, title in TDD_SECTIONS}
    by_number = {number: (key, title) for key, number, title in TDD_SECTIONS}
    i = 0
    while i < len(sections):
        section = sections[i]
        m = _TDD_NUMBER.match(section.title) if section.level in (2, 3) else None
        if m is None:
            if section.level == 2 and _norm(section.title) == _norm(DIAGRAMS_HEADING):
                doc.diagrams_needed = parse_bullets(section.text)
            i += 1
            continue
        number, title = m.group(1), m.group(2).strip()
        if number not in by_number:
            i += 1
            continue
        key = keys.get((number, title.lower()), by_number[number][0])
        entry = TddSection(key=key, number=number, title=by_number[number][1])
        # Collect the Existing / Proposed parts nested under this heading.
        j = i + 1
        while j < len(sections) and sections[j].level > section.level:
            part = sections[j]
            norm = part.title.strip().lower()
            if norm == EXISTING.lower():
                entry.existing = _body_between(sections, j, min_level=part.level)
            elif norm == PROPOSED.lower():
                entry.proposed = _body_between(sections, j, min_level=part.level)
            j += 1
        if entry.existing == "" and entry.proposed == "" and section.text:
            entry.proposed = section.text
        entry.existing = parse_paragraph(entry.existing)
        entry.proposed = parse_paragraph(entry.proposed)
        doc.sections.append(entry)
        i = j
    return doc


def parse_artifact(kind: str, markdown: str) -> ImpactDoc | EpicDoc | StoriesDoc | TddDoc:
    """Dispatch on artifact kind (``impact`` | ``epic`` | ``stories`` | ``tdd``)."""
    if kind == "impact":
        return parse_impact(markdown)
    if kind == "epic":
        return parse_epic(markdown)
    if kind == "stories":
        return parse_stories(markdown)
    if kind == "tdd":
        return parse_tdd(markdown)
    raise ArtifactParseError(f"Unknown artifact kind {kind!r}.")
