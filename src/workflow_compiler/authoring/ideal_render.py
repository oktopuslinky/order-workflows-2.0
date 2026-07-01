"""Deterministically render a WorkflowState into ideal-format Markdown.

The output mirrors ``examples/ideal_temporal_workflow.md`` section-for-section. It
is a pure function of the extracted metadata / facts / structure — no LLM — so it
never introduces ungrounded content. Activity names are reused **verbatim** across
Process / API Interfaces / Retries / Compensation, which is the property the
downstream code generator relies on to match retries and compensations by name.
"""

from __future__ import annotations

from workflow_compiler.models import FactCategory, WorkflowFacts, WorkflowState
from workflow_compiler.models.structure import DecisionNode, WorkflowStructure


def _bold(text: str) -> str:
    return f"**{text}**"


def _statements(facts: WorkflowFacts | None, category: FactCategory) -> list[str]:
    if facts is None:
        return []
    return [f.statement for f in facts.by_category(category)]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- _(none provided)_"


def _metadata_table(state: WorkflowState) -> str:
    md = state.workflow_metadata
    domain = (md.domain if md and md.domain else None) or "—"
    owner = (md.owner if md and md.owner else None) or "—"
    version = (md.version if md and md.version else None) or "—"
    tags = ", ".join(md.tags) if md and md.tags else "—"
    return (
        "| Field   | Value |\n"
        "|---------|-------|\n"
        f"| Domain  | {domain} |\n"
        f"| Owner   | {owner} |\n"
        f"| Version | {version} |\n"
        f"| Tags    | {tags} |"
    )


def _process_steps(
    structure: WorkflowStructure,
    invokes: list[str],
    descriptions: dict[str, str] | None = None,
) -> list[str]:
    """Build numbered Process steps from activities + decisions, both branches named.

    ``descriptions`` optionally supplies a grounded natural sentence per activity name
    (from :class:`~workflow_compiler.agents.ideal_prose.IdealProseAgent`); the bolded
    canonical name is always kept so verbatim name reuse across sections holds.
    """
    descriptions = descriptions or {}
    exc_name_by_id = {e.id: e.reason for e in structure.exceptions}
    decisions_after: dict[str, list[DecisionNode]] = {}
    for d in structure.decisions:
        decisions_after.setdefault(d.after or "", []).append(d)

    def decision_sentence(d: DecisionNode) -> str:
        target = d.no_target
        if target in exc_name_by_id:
            named = _bold(exc_name_by_id[target])
            no_branch = f"the workflow raises {named} and ends"
        else:
            no_branch = "the workflow raises a named exception and ends"
        question = d.question.rstrip("?")
        return f"If the answer to \"{question}?\" is no, {no_branch}; otherwise it continues."

    steps: list[str] = []
    handled: set[str] = set()
    # Unattached decisions (no `after`) lead the process.
    for d in decisions_after.get("", []):
        steps.append(decision_sentence(d))
    for a in structure.activities:
        if a.id in handled:
            continue
        if a.parallel_group is not None:
            group = [x for x in structure.activities if x.parallel_group == a.parallel_group]
            names = ", ".join(_bold(x.name) for x in group)
            steps.append(
                f"In parallel, {names} run concurrently — these are independent and "
                "share no data."
            )
            handled.update(x.id for x in group)
        else:
            clause = descriptions.get(a.name)
            if clause:
                steps.append(f"{_bold(a.name)} — {clause}")
            else:
                steps.append(f"The workflow performs {_bold(a.name)}.")
            handled.add(a.id)
        for d in decisions_after.get(a.id, []):
            steps.append(decision_sentence(d))
    for child in invokes:
        steps.append(f"The workflow invokes `{child}` as a child workflow.")
    return steps


def _api_table(facts: WorkflowFacts | None, state: WorkflowState) -> str:
    api = _statements(facts, FactCategory.API)
    if not api:
        return "_(no external API calls were extracted)_"
    rows = "\n".join(f"| — | {stmt} |" for stmt in api)
    return "| System | Endpoint / Action |\n|--------|-------------------|\n" + rows


def _exceptions_block(structure: WorkflowStructure) -> str:
    name_by_id = {a.id: a.name for a in structure.activities}
    if not structure.exceptions:
        return "- _(no exceptions were extracted)_"
    lines: list[str] = []
    for e in structure.exceptions:
        raiser = name_by_id.get(e.raised_by or "", "")
        by = f" — raised by {_bold(raiser)}" if raiser else ""
        lines.append(f"- {_bold(e.reason)}{by}.")
    return "\n".join(lines)


def _compensation_block(structure: WorkflowStructure) -> str:
    name_by_id = {a.id: a.name for a in structure.activities}
    if not structure.compensations:
        return "- _(no compensations were extracted)_"
    lines: list[str] = []
    for c in structure.compensations:
        activity = name_by_id.get(c.compensates or "", "")
        if activity:
            lines.append(f"- {_bold(c.name)} compensates {_bold(activity)}.")
        else:
            lines.append(f"- {_bold(c.name)} is a compensation (target activity unresolved).")
    return "\n".join(lines)


def render_ideal_section(
    state: WorkflowState,
    *,
    name: str | None = None,
    invokes: list[str] | None = None,
    descriptions: dict[str, str] | None = None,
) -> str:
    """Render ``state`` as one ideal-format Markdown workflow section.

    ``name`` overrides the heading with the authoritative (segment) workflow name
    so it stays identical wherever the workflow is referenced — this is what lets
    an ``invokes`` link match a child workflow by name downstream. When omitted the
    metadata name is used. ``invokes`` names other workflows this one triggers; each
    is emitted as a Process line so the Temporal design stage models it as a child
    workflow.
    """
    md = state.workflow_metadata
    facts = state.workflow_facts
    structure = (facts.structure if facts else None) or WorkflowStructure()
    invokes = invokes or []

    name = (name or (md.name if md and md.name else "Workflow")).strip()
    purpose = (md.purpose or md.description if md else None) or "_(purpose not extracted)_"
    trigger = (
        ", ".join(md.trigger_events)
        if md and md.trigger_events
        else "_(trigger not extracted)_"
    )

    process = _process_steps(structure, invokes, descriptions)
    process_md = (
        "\n".join(f"{i}. {step}" for i, step in enumerate(process, start=1))
        if process
        else "1. _(no activities were extracted)_"
    )

    sections = [
        f"# {name}",
        "",
        "## Metadata",
        "",
        _metadata_table(state),
        "",
        "## Purpose",
        "",
        purpose,
        "",
        "## Trigger",
        "",
        trigger,
        "",
        "## Actors",
        "",
        _bullets(md.actors if md else []),
        "",
        "## Systems",
        "",
        _bullets(md.systems if md else []),
        "",
        "## Inputs and Outputs",
        "",
        "**Inputs (these become the workflow input fields)**",
        _bullets(_statements(facts, FactCategory.INPUT)),
        "",
        "**Outputs**",
        _bullets(_statements(facts, FactCategory.OUTPUT)),
        "",
        "## Process",
        "",
        process_md,
        "",
        "## Business Rules",
        "",
        _bullets(_statements(facts, FactCategory.RULE)),
        "",
        "## Timers and SLAs",
        "",
        _bullets(_statements(facts, FactCategory.TIMER)),
        "",
        "## API Interfaces",
        "",
        _api_table(facts, state),
        "",
        "## Exceptions and Error Handling",
        "",
        _exceptions_block(structure),
        "",
        "## Retries",
        "",
        _bullets(_statements(facts, FactCategory.RETRY)),
        "",
        "## Compensation and Rollback",
        "",
        _compensation_block(structure),
        "",
    ]
    return "\n".join(sections)
