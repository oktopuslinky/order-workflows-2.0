"""Deterministic ``changes.md`` → ChangeSpec fold-in (the inverse of the renderer).

Human edits to ``changes.md`` are parsed back onto the stored
:class:`~workflow_compiler.models.change_spec.ChangeSpec` without a model.
Ingestion **merges** the parsed overlay onto the existing spec: components are
matched by ``kind:name``; a matched component keeps its provenance unless the
user changed its text (then it becomes ``human_provided``); a heading the stored
spec does not know is a new, human-provided component; a stored component whose
heading disappeared is removed. Assumptions / open questions follow the same
rules as the workflow spec's review items. ``Grounding`` and ``Sources`` are
read-only — whatever the stored spec has is kept.

Round trip is identity: ``render → ingest(None) → render`` reproduces the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.models import (
    ChangeSpec,
    ChangeType,
    ComponentChange,
    ComponentKind,
    Provenance,
    SpecItem,
)
from workflow_compiler.spec.change_renderer import (
    ASSUMPTIONS_SECTION,
    CHANGES_TITLE,
    COMPONENTS_SECTION,
    EXISTING_HEADING,
    GROUNDING_SECTION,
    PROPOSED_HEADING,
    QUESTIONS_SECTION,
    SOURCES_SECTION,
)

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3 = re.compile(r"^###\s+(?!#)(.+?)\s*$")
_H4 = re.compile(r"^####\s+(.+?)\s*$")
_MARKER = re.compile(r"\s*\[(human|inferred)\]\s*$")
_BULLET = re.compile(r"^-\s+(.*)$")
_KEYVAL = re.compile(r"^(?P<key>[a-z][a-z ]*?):\s*(?P<value>.*)$")
_CHECKBOX = re.compile(r"^\[(?P<box>[ xX])\]\s*(?:\((?P<ref>[^)]+)\)\s*)?(?P<text>.*)$")
_ANSWER = re.compile(r"^\s+Answer:\s*(.*)$")
_HEADING_SPLIT = " — "

_KIND_ALIASES: dict[str, ComponentKind] = {k.value: k for k in ComponentKind} | {
    "function": ComponentKind.ACTIVITY,
    "class": ComponentKind.TYPE,
    "document": ComponentKind.DOC,
    "test_case": ComponentKind.TEST,
    "test-case": ComponentKind.TEST,
    "story": ComponentKind.DOC,
    "epic": ComponentKind.DOC,
    "test_plan": ComponentKind.DOC,
    "file": ComponentKind.MODULE,
    "mmd": ComponentKind.DIAGRAM,
}
_CHANGE_ALIASES: dict[str, ChangeType] = {c.value: c for c in ChangeType} | {
    "modified": ChangeType.MODIFY,
    "change": ChangeType.MODIFY,
    "update": ChangeType.MODIFY,
    "added": ChangeType.ADD,
    "new": ChangeType.ADD,
    "create": ChangeType.ADD,
    "removed": ChangeType.REMOVE,
    "delete": ChangeType.REMOVE,
    "deleted": ChangeType.REMOVE,
    "unchanged": ChangeType.VERIFY,
    "check": ChangeType.VERIFY,
    "review": ChangeType.VERIFY,
}


def coerce_kind(value: str) -> ComponentKind:
    """Map free-form kind words onto :class:`ComponentKind` (default: module)."""
    return _KIND_ALIASES.get(value.strip().lower(), ComponentKind.MODULE)


def coerce_change_type(value: str) -> ChangeType:
    """Map free-form change words onto :class:`ChangeType` (default: modify)."""
    return _CHANGE_ALIASES.get(value.strip().lower(), ChangeType.MODIFY)


@dataclass
class ChangeIngestResult:
    """Outcome of folding an edited ``changes.md`` back onto a change spec."""

    spec: ChangeSpec
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _ParsedComponent:
    name: str
    kind: ComponentKind
    change_type: ChangeType
    marker: str | None
    path: str = ""
    requirement_ids: list[str] = field(default_factory=list)
    existing: str = ""
    proposed: str = ""


def _strip_marker(text: str) -> tuple[str, str | None]:
    match = _MARKER.search(text)
    if match is None:
        return text.strip(), None
    return text[: match.start()].strip(), match.group(1)


def _sections(markdown: str) -> dict[str, list[str]]:
    """``## Title`` → raw lines (comments removed, trailing whitespace stripped)."""
    cleaned = _COMMENT.sub("", markdown)
    h1 = _H1.search(cleaned)
    if h1 is None or h1.group(1).strip().lower() != CHANGES_TITLE.lower():
        raise CompilationError(f"changes.md has no '# {CHANGES_TITLE}' heading.")
    sections: dict[str, list[str]] = {}
    matches = list(_H2.finditer(cleaned))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        body = cleaned[match.end() : end]
        sections[match.group(1).strip()] = [line.rstrip() for line in body.splitlines()]
    return sections


def _strip_code(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def parse_components(lines: list[str], warnings: list[str]) -> list[_ParsedComponent]:
    """Parse the ``## Components`` body into component blocks."""
    parsed: list[_ParsedComponent] = []
    current: _ParsedComponent | None = None
    block: str | None = None  # "existing" | "proposed" | None
    text_lines: dict[str, list[str]] = {}

    def flush_text() -> None:
        if current is None:
            return
        current.existing = "\n".join(text_lines.get("existing", [])).strip("\n").rstrip()
        current.proposed = "\n".join(text_lines.get("proposed", [])).strip("\n").rstrip()

    for raw in lines:
        h3 = _H3.match(raw)
        if h3 is not None:
            flush_text()
            heading, marker = _strip_marker(h3.group(1))
            name, sep, tail = heading.rpartition(_HEADING_SPLIT)
            if not sep:
                name, tail = heading, ""
                warnings.append(
                    f"component heading '{heading}' has no '— kind, change' tail; "
                    "kind/change default to module/modify"
                )
            kind_word, _, change_word = tail.partition(",")
            current = _ParsedComponent(
                name=name.strip(),
                kind=coerce_kind(kind_word),
                change_type=coerce_change_type(change_word),
                marker=marker,
            )
            parsed.append(current)
            block = None
            text_lines = {}
            continue
        if current is None:
            continue
        h4 = _H4.match(raw)
        if h4 is not None:
            title = h4.group(1).strip().lower()
            if title == EXISTING_HEADING.lower():
                block = "existing"
            elif title == PROPOSED_HEADING.lower():
                block = "proposed"
            else:
                block = None
                warnings.append(
                    f"unknown block '#### {h4.group(1)}' under '{current.name}' ignored"
                )
            if block is not None:
                text_lines.setdefault(block, [])
            continue
        if block is not None:
            text_lines[block].append(raw)
            continue
        bullet = _BULLET.match(raw.strip())
        if bullet is None:
            continue
        keyval = _KEYVAL.match(bullet.group(1).strip())
        if keyval is None:
            continue
        key = keyval.group("key").strip().lower()
        value = keyval.group("value").strip()
        if key == "path":
            current.path = _strip_code(value)
        elif key in ("requirements", "requirement", "requirement ids"):
            current.requirement_ids = [
                r.strip() for r in re.split(r"[,;]", value) if r.strip()
            ]
    flush_text()
    return parsed


def _parse_items(lines: list[str]) -> list[tuple[str, str | None]]:
    """``- text [marker]`` bullets → ``(text, marker)``."""
    items: list[tuple[str, str | None]] = []
    for raw in lines:
        bullet = _BULLET.match(raw.strip())
        if bullet is None:
            continue
        text, marker = _strip_marker(bullet.group(1))
        if text:
            items.append((text, marker))
    return items


def _parse_questions(lines: list[str]) -> list[tuple[str, str | None, bool, str | None]]:
    """``- [ ] (ref) text`` + ``Answer:`` → ``(text, ref, checked, answer)``."""
    out: list[tuple[str, str | None, bool, str | None]] = []
    index = 0
    while index < len(lines):
        bullet = _BULLET.match(lines[index].strip())
        if bullet is None:
            index += 1
            continue
        box = _CHECKBOX.match(bullet.group(1).strip())
        if box is None:
            index += 1
            continue
        answer = None
        if index + 1 < len(lines):
            answer_match = _ANSWER.match(lines[index + 1])
            if answer_match:
                answer = answer_match.group(1).strip() or None
                index += 1
        text = box.group("text").strip()
        ref = (box.group("ref") or "").strip() or None
        checked = box.group("box").lower() == "x"
        if text:
            out.append((text, ref, checked, answer))
        index += 1
    return out


def _provenance_from(marker: str | None, default: Provenance) -> Provenance:
    if marker == "human":
        return Provenance.HUMAN_PROVIDED
    if marker == "inferred":
        return Provenance.LLM_INFERRED
    return default


def _grounding_version(lines: list[str]) -> int | None:
    for raw in lines:
        bullet = _BULLET.match(raw.strip())
        if bullet is None:
            continue
        keyval = _KEYVAL.match(bullet.group(1).strip())
        if keyval is not None and keyval.group("key").strip().lower() == "version":
            value = keyval.group("value").strip()
            return int(value) if value.isdigit() else None
    return None


def ingest_change_markdown(spec: ChangeSpec | None, markdown: str) -> ChangeIngestResult:
    """Fold an edited ``changes.md`` onto ``spec``.

    With ``spec=None`` the file is parsed from scratch: unmarked entries are
    ``document_grounded`` (the renderer's meaning of "no marker") and the
    version is read from the Grounding section, so ``render → ingest(None) →
    render`` is identity. With a stored spec, unmarked *new* entries are
    ``human_provided`` (a person typed them) and the version bumps when anything
    changed.
    """
    from_scratch = spec is None
    old = spec or ChangeSpec()
    default_new = Provenance.DOCUMENT_GROUNDED if from_scratch else Provenance.HUMAN_PROVIDED
    changes: list[str] = []
    warnings: list[str] = []
    sections = _sections(markdown)

    # ---- components -----------------------------------------------------
    components = list(old.components)
    if COMPONENTS_SECTION in sections:
        old_by_key = {c.key(): c for c in old.components}
        merged: list[ComponentChange] = []
        seen: set[str] = set()
        for parsed in parse_components(sections[COMPONENTS_SECTION], warnings):
            key = f"{parsed.kind.value}:{parsed.name.strip().lower()}"
            if key in seen:
                warnings.append(
                    f"duplicate component '{parsed.name}' ({parsed.kind.value}) ignored"
                )
                continue
            seen.add(key)
            existing = old_by_key.get(key)
            if existing is None:
                merged.append(
                    ComponentChange(
                        name=parsed.name,
                        kind=parsed.kind,
                        path=parsed.path,
                        existing=parsed.existing,
                        proposed=parsed.proposed,
                        change_type=parsed.change_type,
                        requirement_ids=parsed.requirement_ids,
                        provenance=_provenance_from(parsed.marker, default_new),
                    )
                )
                changes.append(f"added component '{parsed.name}' ({parsed.kind.value})")
                continue
            edited = (
                parsed.path != existing.path
                or parsed.existing != existing.existing
                or parsed.proposed != existing.proposed
                or parsed.change_type != existing.change_type
                or parsed.requirement_ids != existing.requirement_ids
            )
            provenance = existing.provenance
            if edited:
                provenance = _provenance_from(parsed.marker, Provenance.HUMAN_PROVIDED)
                changes.append(f"edited component '{parsed.name}' ({parsed.kind.value})")
            elif parsed.marker is not None:
                provenance = _provenance_from(parsed.marker, existing.provenance)
            merged.append(
                existing.model_copy(
                    update={
                        "path": parsed.path,
                        "existing": parsed.existing,
                        "proposed": parsed.proposed,
                        "change_type": parsed.change_type,
                        "requirement_ids": parsed.requirement_ids,
                        "provenance": provenance,
                    }
                )
            )
        for key, component in old_by_key.items():
            if key not in seen:
                changes.append(f"removed component '{component.name}' ({component.kind.value})")
        components = merged

    # ---- assumptions ----------------------------------------------------
    assumptions = list(old.assumptions)
    if ASSUMPTIONS_SECTION in sections:
        old_by_text = {a.text.lower(): a for a in old.assumptions}
        assumptions = []
        for text, marker in _parse_items(sections[ASSUMPTIONS_SECTION]):
            existing_item = old_by_text.get(text.lower())
            if existing_item is not None:
                assumptions.append(existing_item)
                continue
            assumptions.append(
                SpecItem(text=text, provenance=_provenance_from(marker, default_new))
            )
            changes.append(f"added assumption '{text}'")

    # ---- open questions -------------------------------------------------
    questions = list(old.open_questions)
    if QUESTIONS_SECTION in sections:
        old_by_ref = {q.ref: q for q in old.open_questions if q.ref}
        old_by_text = {q.text.lower(): q for q in old.open_questions}
        questions = []
        for text, ref, checked, answer in _parse_questions(sections[QUESTIONS_SECTION]):
            existing_q = (ref and old_by_ref.get(ref)) or old_by_text.get(text.lower())
            resolved = checked or bool(answer)
            if existing_q is not None:
                if resolved and not existing_q.resolved:
                    changes.append(f"answered open question '{existing_q.text}'")
                questions.append(
                    existing_q.model_copy(
                        update={"resolved": resolved, "answer": answer or existing_q.answer}
                    )
                )
            else:
                questions.append(
                    SpecItem(
                        text=text,
                        provenance=default_new,
                        resolved=resolved,
                        answer=answer,
                        ref=ref,
                    )
                )
                changes.append(f"added open question '{text}'")

    sources = list(old.sources)
    if from_scratch:
        # Sources are read-only when folding onto a stored spec; parsed from scratch
        # they are simply what the file says.
        version = _grounding_version(sections.get(GROUNDING_SECTION, [])) or old.version
        if SOURCES_SECTION in sections:
            sources = [_strip_code(text) for text, _m in _parse_items(sections[SOURCES_SECTION])]
    else:
        version = old.version + 1 if changes else old.version
    new_spec = old.model_copy(
        update={
            "components": components,
            "assumptions": assumptions,
            "open_questions": questions,
            "sources": sources,
            "version": version,
        }
    )
    return ChangeIngestResult(spec=new_spec, changes=changes, warnings=warnings)


__all__ = [
    "ChangeIngestResult",
    "coerce_change_type",
    "coerce_kind",
    "ingest_change_markdown",
    "parse_components",
]
