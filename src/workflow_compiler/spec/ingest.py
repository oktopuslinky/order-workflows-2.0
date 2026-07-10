"""Parse an edited spec Markdown file back onto the structured WorkflowSpec.

Ingestion is **deterministic** (no LLM). The parser reads the strict grammar
``spec/renderer.py`` emits; the merge then applies the parsed overlay onto the
*existing* spec so fields the Markdown does not render (source spans,
confidences, extraction metadata) survive the round trip. Elements are matched
by their ``[id]`` marker (entities) or normalized text (scalar facts, review
items); anything new is recorded with provenance — ``DOCUMENT_GROUNDED`` when
the text grounds in the source document, ``HUMAN_PROVIDED`` otherwise. After
merging, the relational structure is re-``validated()`` (the referential-
integrity invariant) and the flat facts are re-derived via ``rebuild_facts``.

Human additions are **never dropped for being ungrounded** — that is the point
of the review loop; they are recorded as human-provided so the spec validator
flags them for confirmation instead of removing them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from workflow_compiler.agents.review_pipeline import _grounded, _norm, rebuild_facts
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.models import (
    ActivityNode,
    BindingSource,
    CompensationNode,
    CrossReference,
    DecisionNode,
    EventNode,
    ExceptionNode,
    FactCategory,
    Provenance,
    SpecItem,
    TransitionEdge,
    TriggerInputBinding,
    TriggerMode,
    WorkflowFact,
    WorkflowSpec,
    WorkflowStructure,
    WorkflowTrigger,
)
from workflow_compiler.spec.renderer import (
    ACTIVITIES_SECTION,
    BINDING_SOURCE_TEXT,
    COMPENSATIONS_SECTION,
    DECISIONS_SECTION,
    DEPENDENCIES_SECTION,
    EVENTS_SECTION,
    EXCEPTIONS_SECTION,
    ITEM_SECTIONS,
    METADATA_LIST_KEYS,
    METADATA_SCALAR_KEYS,
    METADATA_SECTION,
    PURPOSE_SECTION,
    QUESTIONS_SECTION,
    SCALAR_SECTIONS,
    TRANSITIONS_SECTION,
    TRIGGER_MODE_TEXT,
    TRIGGERS_SECTION,
)

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_BULLET = re.compile(r"^(?:-|\d+\.)\s+(.*)$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKER = re.compile(r"\s*\[(human|inferred)\]\s*$")
_ENTITY = re.compile(r"^\[(?P<id>[A-Za-z]+\d+)\]\s*(?P<rest>.*)$")
_CHECKBOX = re.compile(r"^\[(?P<box>[ xX])\]\s*(?:\((?P<ref>[^)]+)\)\s*)?(?P<text>.*)$")
_ANSWER = re.compile(r"^\s+Answer:\s*(.*)$")
_TRANSITION = re.compile(
    r"^(?P<src>.+?)\s*->\s*(?P<tgt>.+?)(?:\s*\(trigger:\s*(?P<trig>.*?)\s*\))?$"
)
_USES = re.compile(r"uses output `(?P<out>[^`]+)` of `(?P<other>[^`]+)` as input `(?P<inp>[^`]+)`")
_PROVIDES = re.compile(
    r"provides output `(?P<out>[^`]+)` to `(?P<other>[^`]+)` input `(?P<inp>[^`]+)`"
)
_TRIGGER_HEAD = re.compile(
    r"^triggers `(?P<target>[^`]+)` \((?P<mode>[^)]+)\)(?:\s+when `(?P<cond>[^`]+)`)?$"
)
_TRIGGER_RESULT = re.compile(r"^\s+result:\s*(?P<name>.+?)\s*$")
_TRIGGER_INPUT = re.compile(
    r"^\s+input\s+(?P<field>[^:]+):\s*(?P<source>.+?)"
    r"(?:\s+`(?P<ref>[^`]+)`)?\s*\((?P<type>[^)]+)\)\s*$"
)

#: Rendered text ⇄ enum, derived from the renderer's maps so they never drift.
_MODE_BY_TEXT: dict[str, TriggerMode] = {text: mode for mode, text in TRIGGER_MODE_TEXT.items()}
_SOURCE_BY_TEXT: dict[str, BindingSource] = {
    text: source for source, text in BINDING_SOURCE_TEXT.items()
}

#: Tail keys per entity kind → model field name.
_TAIL_FIELDS: dict[str, dict[str, str]] = {
    "activity": {"parallel": "parallel_group"},
    "decision": {"after": "after", "yes": "yes_target", "no": "no_target"},
    "exception": {"raised by": "raised_by"},
    "compensation": {"compensates": "compensates"},
    "event": {"emitted by": "emitted_by"},
}
_ENTITY_SECTIONS: dict[str, str] = {
    ACTIVITIES_SECTION: "activity",
    DECISIONS_SECTION: "decision",
    EXCEPTIONS_SECTION: "exception",
    COMPENSATIONS_SECTION: "compensation",
    EVENTS_SECTION: "event",
}
_ID_PREFIX = {"activity": "a", "decision": "d", "exception": "e", "compensation": "c",
              "event": "v"}


@dataclass
class _ParsedEntity:
    kind: str
    id: str | None
    label: str
    fields: dict[str, str | None] = field(default_factory=dict)


@dataclass
class IngestResult:
    """The outcome of folding one edited spec file back into the model."""

    spec: WorkflowSpec
    cross_references: list[CrossReference]
    triggers: list[WorkflowTrigger] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _split_tail(text: str) -> tuple[str, dict[str, str]]:
    """Split ``label — key: value; key: value`` into (label, pairs)."""
    for separator in (" — ", " -- "):
        if separator in text:
            label, _, tail = text.partition(separator)
            pairs: dict[str, str] = {}
            for part in tail.split(";"):
                key, colon, value = part.partition(":")
                if colon and _norm(value):
                    pairs[_norm(key).lower()] = _norm(value)
            return _norm(label), pairs
    return _norm(text), {}


def _strip_marker(text: str) -> tuple[str, str | None]:
    """Remove a trailing ``[human]``/``[inferred]`` marker, returning it."""
    match = _MARKER.search(text)
    if match:
        return text[: match.start()].rstrip(), match.group(1)
    return text, None


def _sections(markdown: str) -> tuple[str, dict[str, list[str]]]:
    """Split the file into (workflow name, section title → raw non-empty lines)."""
    cleaned = _COMMENT.sub("", markdown)
    h1 = _H1.search(cleaned)
    if h1 is None:
        raise CompilationError("Spec file has no '# <workflow name>' heading.")
    name = h1.group(1)

    sections: dict[str, list[str]] = {}
    matches = list(_H2.finditer(cleaned))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        body = cleaned[match.end() : end]
        lines = [line.rstrip() for line in body.splitlines()]
        sections[match.group(1)] = [line for line in lines if line.strip()]
    return name, sections


def _bullets(lines: list[str]) -> list[str]:
    """Extract bullet payloads from section lines (ignores non-bullet lines)."""
    out: list[str] = []
    for line in lines:
        match = _BULLET.match(line.strip())
        if match and _norm(match.group(1)):
            out.append(match.group(1).strip())
    return out


def _provenance_for(text: str, document_text: str) -> Provenance:
    """New element provenance: grounded in the document, else human-provided."""
    return (
        Provenance.DOCUMENT_GROUNDED
        if _grounded(text, None, document_text)
        else Provenance.HUMAN_PROVIDED
    )


def _next_id(prefix: str, existing: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def ingest_spec_markdown(
    old_spec: WorkflowSpec,
    markdown: str,
    document_text: str,
    cross_references: list[CrossReference],
    triggers: list[WorkflowTrigger] | None = None,
) -> IngestResult:
    """Merge an edited spec Markdown file onto ``old_spec``.

    Returns the merged spec, the (possibly confirmation-updated) project
    cross-references and triggers, a human-readable change list, and parser
    warnings. ``triggers`` fired by this spec's slug are reconstructed from the
    file (a full round trip, since every trigger field is rendered); triggers
    fired by other workflows pass through untouched.
    """
    triggers = triggers or []
    name, sections = _sections(markdown)
    changes: list[str] = []
    warnings: list[str] = []
    provenance: dict[str, Provenance] = {}

    metadata = _merge_metadata(old_spec, name, sections, changes)
    scalar = _merge_scalar_facts(old_spec, sections, document_text, provenance, changes)
    structure = _merge_structure(
        old_spec, sections, document_text, provenance, changes, warnings
    )
    structure, integrity_warnings = structure.validated()
    warnings.extend(integrity_warnings)
    facts = rebuild_facts(structure, scalar)

    spec = old_spec.model_copy(
        update={
            "metadata": metadata,
            "facts": facts,
            "assumptions": _merge_items(old_spec.assumptions, sections, ASSUMPTIONS_KEY,
                                         document_text),
            "ambiguities": _merge_items(old_spec.ambiguities, sections, AMBIGUITIES_KEY,
                                        document_text),
            "suggested_edits": _merge_items(old_spec.suggested_edits, sections,
                                            SUGGESTIONS_KEY, document_text),
            "open_questions": _merge_questions(old_spec, sections, changes),
            "provenance": provenance,
        }
    )
    references = _merge_references(spec.slug, sections, cross_references, changes, warnings)
    merged_triggers = _merge_triggers(spec.slug, sections, triggers, changes, warnings)
    return IngestResult(spec=spec, cross_references=references, triggers=merged_triggers,
                        changes=changes, warnings=warnings)


ASSUMPTIONS_KEY = "Assumptions"
AMBIGUITIES_KEY = "Ambiguities"
SUGGESTIONS_KEY = "Suggested Edits"


# --------------------------------------------------------------------------- #
# Merge helpers (each pure: old spec + parsed sections → new pieces)
# --------------------------------------------------------------------------- #


def _merge_metadata(
    old_spec: WorkflowSpec,
    name: str,
    sections: dict[str, list[str]],
    changes: list[str],
) -> object:
    """Apply the H1, Purpose, and Metadata sections onto the old metadata."""
    updates: dict[str, object] = {}
    if _norm(name) and _norm(name) != _norm(old_spec.metadata.name):
        updates["name"] = _norm(name)
        changes.append(f"renamed workflow to '{_norm(name)}'")

    if PURPOSE_SECTION in sections:
        purpose = _norm(" ".join(sections[PURPOSE_SECTION]))
        if purpose != _norm(old_spec.metadata.purpose or ""):
            updates["purpose"] = purpose or None
            updates["description"] = purpose or None
            changes.append("updated purpose")

    for bullet in _bullets(sections.get(METADATA_SECTION, [])):
        key, colon, value = bullet.partition(":")
        key = _norm(key).lower()
        if not colon:
            continue
        if key in METADATA_SCALAR_KEYS:
            field_name = METADATA_SCALAR_KEYS[key]
            new = _norm(value) or None
            if new != getattr(old_spec.metadata, field_name):
                updates[field_name] = new
                changes.append(f"metadata {key} → {new or '(cleared)'}")
        elif key in METADATA_LIST_KEYS:
            field_name = METADATA_LIST_KEYS[key]
            new_list = [_norm(v) for v in value.split(",") if _norm(v)]
            if new_list != list(getattr(old_spec.metadata, field_name)):
                updates[field_name] = new_list
                changes.append(f"metadata {key} updated ({len(new_list)} items)")
    return old_spec.metadata.model_copy(update=updates) if updates else old_spec.metadata


def _merge_scalar_facts(
    old_spec: WorkflowSpec,
    sections: dict[str, list[str]],
    document_text: str,
    provenance: dict[str, Provenance],
    changes: list[str],
) -> list[WorkflowFact]:
    """Rebuild the flat scalar facts from their sections, preserving old facts."""
    old_by_key: dict[tuple[FactCategory, str], WorkflowFact] = {
        (f.category, f.statement.lower()): f
        for f in old_spec.facts.facts
        if f.category in SCALAR_SECTIONS.values()
    }
    merged: list[WorkflowFact] = []
    seen: set[tuple[FactCategory, str]] = set()
    for title, category in SCALAR_SECTIONS.items():
        if title not in sections:
            # Section absent from the file: keep the old facts untouched.
            for (cat, _key), fact in old_by_key.items():
                if cat == category:
                    merged.append(fact)
            continue
        for index, bullet in enumerate(_bullets(sections[title]), start=1):
            text, _marker_name = _strip_marker(bullet)
            statement = _norm(text)
            key = (category, statement.lower())
            if not statement or key in seen:
                continue
            seen.add(key)
            existing = old_by_key.get(key)
            if existing is not None:
                merged.append(existing)
                old_prov = old_spec.provenance_of(f"{category.value}:{statement.lower()}")
                if old_prov != Provenance.DOCUMENT_GROUNDED:
                    provenance[f"{category.value}:{statement.lower()}"] = old_prov
                continue
            prov = _provenance_for(statement, document_text)
            if prov != Provenance.DOCUMENT_GROUNDED:
                provenance[f"{category.value}:{statement.lower()}"] = prov
            merged.append(
                WorkflowFact(
                    id=f"{category.value}-new-{index}",
                    statement=statement,
                    category=category,
                    confidence=0.6,
                )
            )
            changes.append(f"added {category.value} '{statement}' ({prov.value})")
    # Note removals per category for sections that were present.
    for (category, key), fact in old_by_key.items():
        title = next(t for t, c in SCALAR_SECTIONS.items() if c == category)
        if title in sections and (category, key) not in seen:
            changes.append(f"removed {category.value} '{fact.statement}'")
    return merged


def _entity_lists(structure: WorkflowStructure) -> dict[str, list]:
    return {
        "activity": structure.activities,
        "decision": structure.decisions,
        "exception": structure.exceptions,
        "compensation": structure.compensations,
        "event": structure.events,
    }


def _entity_label_field(kind: str) -> str:
    return {"decision": "question", "exception": "reason"}.get(kind, "name")


def _build_entity(kind: str, entity_id: str, label: str, fields: dict[str, str | None]):
    common: dict[str, object] = {"id": entity_id, _entity_label_field(kind): label}
    for key, field_name in _TAIL_FIELDS[kind].items():
        common[field_name] = fields.get(key)
    factory = {
        "activity": ActivityNode,
        "decision": DecisionNode,
        "exception": ExceptionNode,
        "compensation": CompensationNode,
        "event": EventNode,
    }[kind]
    return factory(**common)  # type: ignore[arg-type]


def _merge_structure(
    old_spec: WorkflowSpec,
    sections: dict[str, list[str]],
    document_text: str,
    provenance: dict[str, Provenance],
    changes: list[str],
    warnings: list[str],
) -> WorkflowStructure:
    """Rebuild the relational structure from the entity sections."""
    old_structure = old_spec.facts.structure or WorkflowStructure()
    old_lists = _entity_lists(old_structure)
    new_structure = WorkflowStructure(
        # Structure-level triggers are injected at approval (never rendered in
        # the spec file), so they pass through ingestion untouched.
        triggers=[t.model_copy() for t in old_structure.triggers],
        transitions=_parse_transitions(sections, old_structure),
    )
    new_lists = _entity_lists(new_structure)

    for title, kind in _ENTITY_SECTIONS.items():
        old_items = {item.id: item for item in old_lists[kind]}
        if title not in sections:
            new_lists[kind].extend(old_lists[kind])
            _carry_provenance(old_spec, provenance, kind, old_lists[kind])
            continue
        seen_ids: set[str] = set()
        parsed = _parse_entities(kind, sections[title], warnings)
        all_ids = set(old_items) | {p.id for p in parsed if p.id}
        for entry in parsed:
            entity_id = entry.id
            if entity_id and entity_id in old_items:
                old = old_items[entity_id]
                updated = _build_entity(kind, entity_id, entry.label, entry.fields)
                if updated != old:
                    changes.append(f"modified {kind} {entity_id}")
                new_lists[kind].append(updated)
                old_prov = old_spec.provenance_of(f"{kind}:{entity_id}")
                if old_prov != Provenance.DOCUMENT_GROUNDED:
                    provenance[f"{kind}:{entity_id}"] = old_prov
            else:
                if entity_id is None:
                    entity_id = _next_id(_ID_PREFIX[kind], all_ids)
                    all_ids.add(entity_id)
                prov = _provenance_for(entry.label, document_text)
                if prov != Provenance.DOCUMENT_GROUNDED:
                    provenance[f"{kind}:{entity_id}"] = prov
                new_lists[kind].append(
                    _build_entity(kind, entity_id, entry.label, entry.fields)
                )
                changes.append(f"added {kind} {entity_id} '{entry.label}' ({prov.value})")
            seen_ids.add(entity_id)
        for old_id, old_item in old_items.items():
            if old_id not in seen_ids:
                label = getattr(old_item, _entity_label_field(kind))
                changes.append(f"removed {kind} {old_id} '{label}'")
    return new_structure


def _carry_provenance(
    old_spec: WorkflowSpec,
    provenance: dict[str, Provenance],
    kind: str,
    items: list,
) -> None:
    for item in items:
        ref = f"{kind}:{item.id}"
        old_prov = old_spec.provenance_of(ref)
        if old_prov != Provenance.DOCUMENT_GROUNDED:
            provenance[ref] = old_prov


def _parse_entities(kind: str, lines: list[str], warnings: list[str]) -> list[_ParsedEntity]:
    parsed: list[_ParsedEntity] = []
    for bullet in _bullets(lines):
        text, _marker_name = _strip_marker(bullet)
        match = _ENTITY.match(text)
        if match:
            entity_id: str | None = match.group("id")
            rest = match.group("rest")
        else:
            entity_id = None
            rest = text
        label, pairs = _split_tail(rest)
        if not label:
            warnings.append(f"Skipped unparseable {kind} line: {bullet!r}")
            continue
        fields: dict[str, str | None] = {}
        for key in _TAIL_FIELDS[kind]:
            fields[key] = pairs.get(key)
        unknown = set(pairs) - set(_TAIL_FIELDS[kind])
        if unknown:
            warnings.append(
                f"Ignored unknown attribute(s) {sorted(unknown)} on {kind} '{label}'."
            )
        parsed.append(_ParsedEntity(kind=kind, id=entity_id, label=label, fields=fields))
    return parsed


def _parse_transitions(
    sections: dict[str, list[str]], old_structure: WorkflowStructure
) -> list[TransitionEdge]:
    if TRANSITIONS_SECTION not in sections:
        return list(old_structure.transitions)
    transitions: list[TransitionEdge] = []
    for bullet in _bullets(sections[TRANSITIONS_SECTION]):
        text, _marker_name = _strip_marker(bullet)
        match = _TRANSITION.match(text)
        if match:
            transitions.append(
                TransitionEdge(
                    source=_norm(match.group("src")),
                    target=_norm(match.group("tgt")),
                    trigger=_norm(match.group("trig") or "") or None,
                )
            )
    return transitions


def _merge_items(
    old_items: list[SpecItem],
    sections: dict[str, list[str]],
    title: str,
    document_text: str,
) -> list[SpecItem]:
    """Rebuild a review-item list, preserving matched old items' provenance."""
    if title not in sections:
        return list(old_items)
    assert title in ITEM_SECTIONS
    old_by_text = {item.text.lower(): item for item in old_items}
    merged: list[SpecItem] = []
    for bullet in _bullets(sections[title]):
        text, marker_name = _strip_marker(bullet)
        text = _norm(text)
        if not text:
            continue
        existing = old_by_text.get(text.lower())
        if existing is not None:
            merged.append(existing)
            continue
        if marker_name == "human":
            prov = Provenance.HUMAN_PROVIDED
        elif marker_name == "inferred":
            prov = Provenance.LLM_INFERRED
        else:
            prov = _provenance_for(text, document_text)
        merged.append(SpecItem(text=text, provenance=prov))
    return merged


def _merge_questions(
    old_spec: WorkflowSpec,
    sections: dict[str, list[str]],
    changes: list[str],
) -> list[SpecItem]:
    """Parse the Open Questions checkboxes + answers back onto the old items."""
    if QUESTIONS_SECTION not in sections:
        return list(old_spec.open_questions)
    old_by_ref = {q.ref: q for q in old_spec.open_questions if q.ref}
    old_by_text = {q.text.lower(): q for q in old_spec.open_questions}
    merged: list[SpecItem] = []
    lines = sections[QUESTIONS_SECTION]
    index = 0
    while index < len(lines):
        bullet_match = _BULLET.match(lines[index].strip())
        if bullet_match is None:
            index += 1
            continue
        box_match = _CHECKBOX.match(bullet_match.group(1).strip())
        if box_match is None:
            index += 1
            continue
        answer = None
        if index + 1 < len(lines):
            answer_match = _ANSWER.match(lines[index + 1])
            if answer_match:
                answer = _norm(answer_match.group(1)) or None
                index += 1
        text = _norm(box_match.group("text"))
        ref = _norm(box_match.group("ref") or "") or None
        checked = box_match.group("box").lower() == "x"
        existing = (ref and old_by_ref.get(ref)) or old_by_text.get(text.lower())
        resolved = checked or bool(answer)
        if existing is not None:
            if resolved and not existing.resolved:
                changes.append(f"answered open question '{existing.text}'")
            merged.append(
                existing.model_copy(
                    update={"resolved": resolved, "answer": answer or existing.answer}
                )
            )
        elif text:
            merged.append(
                SpecItem(
                    text=text,
                    provenance=Provenance.HUMAN_PROVIDED,
                    resolved=resolved,
                    answer=answer,
                    ref=ref,
                )
            )
        index += 1
    return merged


def _merge_references(
    slug: str,
    sections: dict[str, list[str]],
    cross_references: list[CrossReference],
    changes: list[str],
    warnings: list[str],
) -> list[CrossReference]:
    """Update cross-reference confirmations from this file's checkboxes."""
    if DEPENDENCIES_SECTION not in sections:
        return list(cross_references)
    updated = [r.model_copy() for r in cross_references]
    for bullet in _bullets(sections[DEPENDENCIES_SECTION]):
        box_match = _CHECKBOX.match(bullet.strip())
        if box_match is None:
            continue
        text = box_match.group("text")
        checked = box_match.group("box").lower() == "x"
        uses = _USES.search(text)
        provides = _PROVIDES.search(text)
        if uses:
            key = (uses.group("other"), uses.group("out"), slug, uses.group("inp"))
        elif provides:
            key = (slug, provides.group("out"), provides.group("other"),
                   provides.group("inp"))
        else:
            warnings.append(f"Unrecognized dependency line: {bullet!r}")
            continue
        matched = next(
            (
                r
                for r in updated
                if (r.source_workflow, r.output_field, r.target_workflow, r.input_field)
                == key
            ),
            None,
        )
        if matched is None:
            warnings.append(f"Dependency line does not match a known link: {bullet!r}")
            continue
        if checked and not matched.user_confirmed:
            matched.user_confirmed = True
            changes.append(
                f"confirmed dependency {key[0]}.{key[1]} -> {key[2]}.{key[3]}"
            )
    return updated


def _parse_triggers(
    slug: str, lines: list[str], warnings: list[str]
) -> list[WorkflowTrigger]:
    """Parse the Triggers section into fully reconstructed WorkflowTriggers.

    A trigger spans a checkbox head line plus indented ``result:`` / ``input``
    continuation lines; every field is rendered, so parse is an exact inverse of
    render (no merge against old triggers is needed).
    """
    triggers: list[WorkflowTrigger] = []
    current: WorkflowTrigger | None = None
    for raw in lines:
        bullet = _BULLET.match(raw.strip())
        if bullet is not None:
            box_match = _CHECKBOX.match(bullet.group(1).strip())
            head = _TRIGGER_HEAD.match(box_match.group("text").strip()) if box_match else None
            if box_match is None or head is None:
                warnings.append(f"Unrecognized trigger line: {raw.strip()!r}")
                current = None
                continue
            mode = _MODE_BY_TEXT.get(_norm(head.group("mode")).lower())
            if mode is None:
                warnings.append(f"Unknown trigger mode in line: {raw.strip()!r}")
                current = None
                continue
            current = WorkflowTrigger(
                source_workflow=slug,
                target_workflow=_norm(head.group("target")),
                mode=mode,
                condition=_norm(head.group("cond") or "") or None,
                user_confirmed=box_match.group("box").lower() == "x",
            )
            triggers.append(current)
            continue
        result_match = _TRIGGER_RESULT.match(raw)
        if result_match is not None and current is not None:
            current.result_binding = _norm(result_match.group("name")) or None
            continue
        input_match = _TRIGGER_INPUT.match(raw)
        if input_match is not None and current is not None:
            source = _SOURCE_BY_TEXT.get(_norm(input_match.group("source")).lower())
            if source is None:
                warnings.append(f"Unknown input source in trigger line: {raw.strip()!r}")
                continue
            current.input_map.append(
                TriggerInputBinding(
                    target_input=_norm(input_match.group("field")),
                    source=source,
                    source_ref=_norm(input_match.group("ref") or "") or None,
                    type=_norm(input_match.group("type")) or "str",
                )
            )
    return triggers


def _merge_triggers(
    slug: str,
    sections: dict[str, list[str]],
    triggers: list[WorkflowTrigger],
    changes: list[str],
    warnings: list[str],
) -> list[WorkflowTrigger]:
    """Replace ``slug``'s outgoing triggers with the ones parsed from its file.

    Triggers fired by other workflows keep their original position; the parsed
    block for this slug is spliced in where the slug's first trigger was (or
    appended if it had none), preserving overall order for a clean round trip.
    """
    if TRIGGERS_SECTION not in sections:
        return list(triggers)
    parsed = _parse_triggers(slug, sections[TRIGGERS_SECTION], warnings)
    old_for_slug = [t for t in triggers if t.source_workflow == slug]
    if parsed != old_for_slug:
        changes.append(f"updated triggers for {slug} ({len(parsed)} trigger(s))")
    result: list[WorkflowTrigger] = []
    inserted = False
    for trigger in triggers:
        if trigger.source_workflow == slug:
            if not inserted:
                result.extend(parsed)
                inserted = True
        else:
            result.append(trigger)
    if not inserted:
        result.extend(parsed)
    return result
