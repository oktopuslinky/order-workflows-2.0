"""Deterministic WorkflowSpec → Markdown projection (the human review surface).

The rendered file follows a strict line grammar so ``spec/ingest.py`` can parse
it back without a model. The **structured spec is the source of truth**; this
Markdown is a lossy-only-in-formatting view of it — every field the file renders
is a field the parser reads back, and fields the file does *not* render (source
spans, confidences, extraction metadata) survive a round trip because ingestion
merges the parsed overlay onto the existing spec instead of rebuilding it.

Line grammar (what the parser relies on):

* ``# <name>`` — the workflow name (H1, exactly one).
* ``## <Section>`` — fixed section titles (see the ``*_SECTION`` constants).
* Metadata: ``- <key>: <value>`` (list-valued keys comma-joined).
* Scalar facts: one ``- <statement>`` bullet per fact.
* Entities: ``- [<id>] <label>`` with optional ``— key: value; key: value`` tail.
* Review items: ``- <text>``, with an optional trailing ``[human]``/``[inferred]``
  provenance marker.
* Open questions: ``- [ ] (<ref>) <question>`` + an indented ``Answer:`` line.
* Cross-references: ``- [ ] uses output `x` of `slug` as input `y` — <desc>``.
"""

from __future__ import annotations

from workflow_compiler.models import (
    CrossReference,
    FactCategory,
    Provenance,
    SpecItem,
    WorkflowFacts,
    WorkflowSpec,
    WorkflowStructure,
)

#: Section titles, shared with the parser. Order here is render order.
PURPOSE_SECTION = "Purpose"
METADATA_SECTION = "Metadata"
INPUTS_SECTION = "Inputs"
OUTPUTS_SECTION = "Outputs"
ACTIVITIES_SECTION = "Activities"
DECISIONS_SECTION = "Decisions"
EXCEPTIONS_SECTION = "Exceptions"
COMPENSATIONS_SECTION = "Compensations"
EVENTS_SECTION = "Events"
TRANSITIONS_SECTION = "State Transitions"
RULES_SECTION = "Business Rules"
APIS_SECTION = "API Interfaces"
SYSTEMS_FACTS_SECTION = "Systems Involved"
TIMERS_SECTION = "Timers and SLAs"
RETRIES_SECTION = "Retries"
ASSUMPTIONS_SECTION = "Assumptions"
AMBIGUITIES_SECTION = "Ambiguities"
QUESTIONS_SECTION = "Open Questions"
SUGGESTIONS_SECTION = "Suggested Edits"
DEPENDENCIES_SECTION = "Cross-Workflow Dependencies"

#: Scalar fact sections and their category (shared with the parser).
SCALAR_SECTIONS: dict[str, FactCategory] = {
    INPUTS_SECTION: FactCategory.INPUT,
    OUTPUTS_SECTION: FactCategory.OUTPUT,
    RULES_SECTION: FactCategory.RULE,
    APIS_SECTION: FactCategory.API,
    SYSTEMS_FACTS_SECTION: FactCategory.SYSTEM,
    TIMERS_SECTION: FactCategory.TIMER,
    RETRIES_SECTION: FactCategory.RETRY,
}

#: Review-item sections and the WorkflowSpec field they render (shared).
ITEM_SECTIONS: dict[str, str] = {
    ASSUMPTIONS_SECTION: "assumptions",
    AMBIGUITIES_SECTION: "ambiguities",
    SUGGESTIONS_SECTION: "suggested_edits",
}

#: Metadata keys rendered as ``- key: value`` lines (list keys comma-joined).
METADATA_LIST_KEYS: dict[str, str] = {
    "actors": "actors",
    "systems": "systems",
    "triggers": "trigger_events",
    "start states": "start_states",
    "end states": "end_states",
    "tags": "tags",
}
METADATA_SCALAR_KEYS: dict[str, str] = {
    "domain": "domain",
    "owner": "owner",
    "version": "version",
}

#: Provenance markers appended to bullets (absent = document-grounded).
PROVENANCE_MARKERS: dict[Provenance, str] = {
    Provenance.LLM_INFERRED: "[inferred]",
    Provenance.HUMAN_PROVIDED: "[human]",
}

_HEADER_COMMENT = (
    "<!--\n"
    "  workflow-compiler specification (v1) — slug: {slug}\n"
    "  This file is a projection of the structured spec. Edit it freely, then run\n"
    "  `workflow-compiler validate <project-id>` to fold your edits back in.\n"
    "  Lines you add are recorded as human-provided. Keep the `[id]` markers on\n"
    "  existing entries so your edits update the right element.\n"
    "-->"
)


def _marker(spec: WorkflowSpec, ref: str) -> str:
    """Return the trailing provenance marker for element ``ref`` ('' if grounded)."""
    marker = PROVENANCE_MARKERS.get(spec.provenance_of(ref), "")
    return f" {marker}" if marker else ""


def _tail(pairs: list[tuple[str, str | None]]) -> str:
    """Render the ``— key: value; key: value`` tail (omitting empty values)."""
    parts = [f"{key}: {value}" for key, value in pairs if value]
    return f" — {'; '.join(parts)}" if parts else ""


def _item_line(item: SpecItem) -> str:
    """Render one assumption/ambiguity/suggestion bullet with its marker."""
    marker = PROVENANCE_MARKERS.get(item.provenance, "")
    return f"- {item.text}" + (f" {marker}" if marker else "")


def render_spec(spec: WorkflowSpec, cross_references: list[CrossReference]) -> str:
    """Render ``spec`` (plus its project cross-references) to Markdown."""
    facts: WorkflowFacts = spec.facts
    structure = facts.structure or WorkflowStructure()
    lines: list[str] = [f"# {spec.metadata.name}", ""]
    lines += [_HEADER_COMMENT.format(slug=spec.slug), ""]

    def section(title: str, body: list[str]) -> None:
        lines.append(f"## {title}")
        lines.extend(body or ["<!-- none -->"])
        lines.append("")

    section(PURPOSE_SECTION, [spec.metadata.purpose or ""])

    meta_lines: list[str] = []
    for key, field in METADATA_SCALAR_KEYS.items():
        value = getattr(spec.metadata, field) or ""
        meta_lines.append(f"- {key}: {value}")
    for key, field in METADATA_LIST_KEYS.items():
        values = getattr(spec.metadata, field) or []
        meta_lines.append(f"- {key}: {', '.join(values)}")
    section(METADATA_SECTION, meta_lines)

    scalar_by_category: dict[FactCategory, list[str]] = {}
    for fact in facts.facts:
        scalar_by_category.setdefault(fact.category, []).append(fact.statement)
    for title, category in SCALAR_SECTIONS.items():
        bullets = [
            f"- {statement}" + _marker(spec, f"{category.value}:{statement.lower()}")
            for statement in scalar_by_category.get(category, [])
        ]
        section(title, bullets)

    section(
        ACTIVITIES_SECTION,
        [
            f"- [{a.id}] {a.name}"
            + _tail([("parallel", a.parallel_group)])
            + _marker(spec, f"activity:{a.id}")
            for a in structure.activities
        ],
    )
    section(
        DECISIONS_SECTION,
        [
            f"- [{d.id}] {d.question}"
            + _tail([("after", d.after), ("yes", d.yes_target), ("no", d.no_target)])
            + _marker(spec, f"decision:{d.id}")
            for d in structure.decisions
        ],
    )
    section(
        EXCEPTIONS_SECTION,
        [
            f"- [{x.id}] {x.reason}"
            + _tail([("raised by", x.raised_by)])
            + _marker(spec, f"exception:{x.id}")
            for x in structure.exceptions
        ],
    )
    section(
        COMPENSATIONS_SECTION,
        [
            f"- [{c.id}] {c.name}"
            + _tail([("compensates", c.compensates)])
            + _marker(spec, f"compensation:{c.id}")
            for c in structure.compensations
        ],
    )
    section(
        EVENTS_SECTION,
        [
            f"- [{v.id}] {v.name}"
            + _tail([("emitted by", v.emitted_by)])
            + _marker(spec, f"event:{v.id}")
            for v in structure.events
        ],
    )
    section(
        TRANSITIONS_SECTION,
        [
            f"- {t.source} -> {t.target}" + (f" (trigger: {t.trigger})" if t.trigger else "")
            for t in structure.transitions
        ],
    )

    for title, field in ITEM_SECTIONS.items():
        section(title, [_item_line(item) for item in getattr(spec, field)])

    question_lines: list[str] = []
    for question in spec.open_questions:
        box = "x" if question.resolved else " "
        ref = f"({question.ref}) " if question.ref else ""
        question_lines.append(f"- [{box}] {ref}{question.text}")
        question_lines.append(f"  Answer: {question.answer or ''}")
    section(QUESTIONS_SECTION, question_lines)

    dependency_lines: list[str] = []
    for reference in cross_references:
        if spec.slug not in (reference.source_workflow, reference.target_workflow):
            continue
        box = "x" if reference.user_confirmed else " "
        if reference.target_workflow == spec.slug:
            text = (
                f"uses output `{reference.output_field}` of `{reference.source_workflow}` "
                f"as input `{reference.input_field}`"
            )
        else:
            text = (
                f"provides output `{reference.output_field}` to `{reference.target_workflow}` "
                f"input `{reference.input_field}`"
            )
        suffix = f" — {reference.description}" if reference.description else ""
        dependency_lines.append(f"- [{box}] {text}{suffix}")
    section(DEPENDENCIES_SECTION, dependency_lines)

    return "\n".join(lines).rstrip() + "\n"
