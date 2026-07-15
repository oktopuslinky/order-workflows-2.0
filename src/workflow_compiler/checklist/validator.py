"""Deterministic readiness validator.

:class:`ChecklistValidator` inspects a :class:`WorkflowState` after fact
extraction and emits one :class:`ChecklistItem` per requirement. It makes **no**
LLM call and never mutates the state — it only reports what the document does and
does not supply, so the compiler can decide whether to halt before generation.

The requirements mirror ``examples/ideal_temporal_workflow.md``: the document
shape that produces clean, runnable Temporal code. An ideal document clears every
item; a deficient one surfaces exactly what the author must add.
"""

from __future__ import annotations

import re

from workflow_compiler.models import (
    CompensationNode,
    DecisionNode,
    FactCategory,
    WorkflowState,
    WorkflowStructure,
)
from workflow_compiler.models.checklist import (
    ChecklistItem,
    ChecklistSeverity,
    ChecklistStatus,
    WorkflowChecklist,
)

#: Leading identifier of an input declaration, e.g. ``order_id`` in
#: "order_id — identifier of the order".
_LEAD_IDENTIFIER = re.compile(r"^[`'\"]?([A-Za-z_][A-Za-z0-9_]*)")
_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def _lead_identifier(statement: str) -> str | None:
    """Return the leading ``identifier`` token of a fact statement, if any."""
    match = _LEAD_IDENTIFIER.match(statement.strip())
    return match.group(1) if match else None


def _is_snake(token: str) -> bool:
    """True when ``token`` is a lower_snake_case identifier."""
    return bool(_SNAKE.match(token))


def _spec_line(node_id: str, label: str, tail: list[tuple[str, str | None]]) -> str:
    """One spec-file entity bullet, byte-identical to what ``spec.renderer`` emits.

    The suggestion is only useful if the user can paste it, so this must track the
    renderer's format exactly — ``test_suggested_line_matches_the_rendered_spec`` pins
    them together.
    """
    parts = "; ".join(f"{key}: {value}" for key, value in tail if value)
    return f"- [{node_id}] {label}" + (f" — {parts}" if parts else "")


def _decision_fix(offenders: list[DecisionNode], structure: WorkflowStructure) -> str:
    """The exact edit that clears R4, written against this workflow's own ids.

    The spec's Decisions section round-trips ``no:`` deterministically, so handing the
    user the line to paste is a complete fix. A free-text answer is only a fallback,
    and only in ``<decision> -> <target>`` form — say so rather than inviting prose.
    """
    d = offenders[0]
    targets = ", ".join(f"{x.id} ({x.reason})" for x in structure.exceptions)
    example = structure.exceptions[0].id if structure.exceptions else "rejected"
    line = _spec_line(
        d.id, d.question, [("after", d.after), ("yes", d.yes_target), ("no", example)]
    )
    return (
        f"Route the 'no' branch of {', '.join(o.id for o in offenders)} in this spec's "
        f"Decisions section, e.g. `{line}`. "
        + (f"Declared exceptions: {targets}. " if targets else "")
        + "A 'no' branch may target an exception id, an activity id, or a terminal token "
        "(end, rejected, failed, completed). You can also answer here, one pair per line, "
        f"as `{d.id} -> {example}` — prose is not applied."
    )


def _compensation_fix(unbound: list[CompensationNode], structure: WorkflowStructure) -> str:
    """The exact edit that clears R5, written against this workflow's own ids."""
    c = unbound[0]
    activities = ", ".join(f"{a.id} ({a.name})" for a in structure.activities)
    example = structure.activities[0] if structure.activities else None
    line = _spec_line(c.id, c.name, [("compensates", example.id if example else "a1")])
    return (
        f"Bind {', '.join(u.id for u in unbound)} to the activity it reverses in this "
        f"spec's Compensations section, e.g. `{line}`. "
        + (f"Declared activities: {activities}. " if activities else "")
        + f"You can also answer here, one pair per line, as "
        f"`{c.name} -> {example.name if example else 'Reserve inventory'}`."
    )


class ChecklistValidator:
    """Validate a post-facts :class:`WorkflowState` into a :class:`WorkflowChecklist`."""

    def validate(self, state: WorkflowState) -> WorkflowChecklist:
        """Build the readiness checklist for ``state`` (deterministic, no LLM)."""
        facts = state.workflow_facts
        if facts is None:
            # Nothing extracted yet — a single blocking item says so.
            return WorkflowChecklist(
                items=[
                    ChecklistItem(
                        id="R0-facts",
                        requirement="The document must yield extractable workflow facts.",
                        category="facts",
                        severity=ChecklistSeverity.REQUIRED,
                        status=ChecklistStatus.MISSING,
                        evidence="No facts were extracted from the document.",
                        question="Does the document describe a concrete process with steps?",
                    )
                ]
            )

        structure = facts.structure or WorkflowStructure()
        trigger_events = state.workflow_metadata.trigger_events if state.workflow_metadata else []
        inputs = facts.by_category(FactCategory.INPUT)
        outputs = facts.by_category(FactCategory.OUTPUT)
        retries = facts.by_category(FactCategory.RETRY)
        timers = facts.by_category(FactCategory.TIMER)
        transitions = facts.by_category(FactCategory.STATE_TRANSITION)

        items = [
            self._trigger(trigger_events),
            self._inputs_present(inputs),
            self._input_names(inputs),
            self._outputs_present(outputs),
            self._decisions_complete(structure),
            self._compensations_bound(structure),
            self._bounded_waits(structure, timers),
            self._exceptions_present(structure),
            self._retries_present(structure, retries),
            self._state_transitions(transitions),
        ]
        return WorkflowChecklist(items=items)

    # -- individual rules ---------------------------------------------------

    @staticmethod
    def _trigger(trigger_events: list[str]) -> ChecklistItem:
        ok = bool(trigger_events)
        return ChecklistItem(
            id="R1-trigger",
            requirement="The workflow has a single, explicit start trigger.",
            category="trigger",
            severity=ChecklistSeverity.REQUIRED,
            status=ChecklistStatus.SATISFIED if ok else ChecklistStatus.MISSING,
            evidence=(
                f"Trigger(s): {', '.join(trigger_events)}."
                if ok
                else "No trigger event was discovered."
            ),
            question=(
                None if ok else "What event starts this workflow (e.g. 'order.settle received')?"
            ),
        )

    @staticmethod
    def _inputs_present(inputs: list) -> ChecklistItem:  # type: ignore[type-arg]
        ok = bool(inputs)
        return ChecklistItem(
            id="R2-inputs",
            requirement="The workflow declares its top-level inputs.",
            category="inputs",
            severity=ChecklistSeverity.REQUIRED,
            status=ChecklistStatus.SATISFIED if ok else ChecklistStatus.MISSING,
            evidence=(
                f"{len(inputs)} input(s): {', '.join(f.statement for f in inputs)}."
                if ok
                else "No workflow inputs were declared."
            ),
            question=(
                None
                if ok
                else "What named inputs does the workflow receive (e.g. order_id, amount)?"
            ),
        )

    @staticmethod
    def _input_names(inputs: list) -> ChecklistItem:  # type: ignore[type-arg]
        offenders = []
        for fact in inputs:
            token = _lead_identifier(fact.statement)
            if token is not None and not _is_snake(token):
                offenders.append(token)
        if not inputs:
            status = ChecklistStatus.SATISFIED
            evidence = "No inputs to name-check."
        elif offenders:
            status = ChecklistStatus.NEEDS_CONFIRMATION
            evidence = f"Non snake_case input name(s): {', '.join(offenders)}."
        else:
            status = ChecklistStatus.SATISFIED
            evidence = "All input names are snake_case."
        return ChecklistItem(
            id="R2b-input-names",
            requirement="Input names are snake_case (map directly to dataclass fields).",
            category="inputs",
            severity=ChecklistSeverity.OPTIONAL,
            status=status,
            evidence=evidence,
            question=(
                "Provide snake_case names for these inputs (e.g. customerId -> customer_id)."
                if offenders
                else None
            ),
        )

    @staticmethod
    def _outputs_present(outputs: list) -> ChecklistItem:  # type: ignore[type-arg]
        ok = bool(outputs)
        return ChecklistItem(
            id="R3-outputs",
            requirement="The workflow declares its outputs / result.",
            category="outputs",
            severity=ChecklistSeverity.OPTIONAL,
            status=ChecklistStatus.SATISFIED if ok else ChecklistStatus.NEEDS_CONFIRMATION,
            evidence=(
                f"{len(outputs)} output(s) declared."
                if ok
                else "No outputs declared (the workflow may still be valid)."
            ),
            question=None if ok else "What does the workflow produce when it completes?",
        )

    @staticmethod
    def _decisions_complete(structure: WorkflowStructure) -> ChecklistItem:
        decisions = structure.decisions
        if not decisions:
            return ChecklistItem(
                id="R4-decisions",
                requirement="Every decision states both branches; 'no' routes to an exception.",
                category="decisions",
                severity=ChecklistSeverity.REQUIRED,
                status=ChecklistStatus.SATISFIED,
                evidence="No decisions to validate.",
            )
        incomplete: list[str] = []
        offenders = []
        for d in decisions:
            if not d.yes_target or not d.no_target:
                incomplete.append(f"{d.id} ('{d.question}') is missing a branch target")
                offenders.append(d)
            elif d.no_target == d.after:
                incomplete.append(f"{d.id} ('{d.question}') routes 'no' back to its own activity")
                offenders.append(d)
        ok = not incomplete
        return ChecklistItem(
            id="R4-decisions",
            requirement="Every decision states both branches; 'no' routes to an exception.",
            category="decisions",
            severity=ChecklistSeverity.REQUIRED,
            status=ChecklistStatus.SATISFIED if ok else ChecklistStatus.MISSING,
            evidence=(
                f"All {len(decisions)} decision(s) have both branches."
                if ok
                else "; ".join(incomplete) + "."
            ),
            question=None if ok else _decision_fix(offenders, structure),
        )

    @staticmethod
    def _compensations_bound(structure: WorkflowStructure) -> ChecklistItem:
        comps = structure.compensations
        if not comps:
            return ChecklistItem(
                id="R5-compensations",
                requirement="Each compensation names the activity it reverses.",
                category="compensations",
                severity=ChecklistSeverity.REQUIRED,
                status=ChecklistStatus.SATISFIED,
                evidence="No compensations to validate.",
            )
        activity_ids = structure.activity_ids()
        unbound = [c for c in comps if not c.compensates or c.compensates not in activity_ids]
        ok = not unbound
        return ChecklistItem(
            id="R5-compensations",
            requirement="Each compensation names the activity it reverses.",
            category="compensations",
            severity=ChecklistSeverity.REQUIRED,
            status=ChecklistStatus.SATISFIED if ok else ChecklistStatus.MISSING,
            evidence=(
                f"All {len(comps)} compensation(s) are bound to an activity."
                if ok
                else f"Unbound compensation(s): {', '.join(c.id for c in unbound)}."
            ),
            question=None if ok else _compensation_fix(unbound, structure),
        )

    @staticmethod
    def _bounded_waits(structure: WorkflowStructure, timers: list) -> ChecklistItem:  # type: ignore[type-arg]
        has_waits = bool(structure.events)
        if not has_waits:
            return ChecklistItem(
                id="R6-bounded-waits",
                requirement="Every human/external wait is bounded by a timer.",
                category="waits",
                severity=ChecklistSeverity.OPTIONAL,
                status=ChecklistStatus.SATISFIED,
                evidence="No external waits to bound.",
            )
        ok = bool(timers)
        return ChecklistItem(
            id="R6-bounded-waits",
            requirement="Every human/external wait is bounded by a timer.",
            category="waits",
            severity=ChecklistSeverity.OPTIONAL,
            status=ChecklistStatus.SATISFIED if ok else ChecklistStatus.NEEDS_CONFIRMATION,
            evidence=(
                "Waits are present and at least one timer/deadline was declared."
                if ok
                else "Waits exist but no timer/deadline was declared; a signal could block forever."
            ),
            question=None if ok else "What deadline bounds each wait (e.g. 24 hours)?",
        )

    @staticmethod
    def _exceptions_present(structure: WorkflowStructure) -> ChecklistItem:
        if not structure.activities:
            status = ChecklistStatus.SATISFIED
            evidence = "No activities to guard."
        elif structure.exceptions:
            status = ChecklistStatus.SATISFIED
            evidence = f"{len(structure.exceptions)} exception(s) declared."
        else:
            status = ChecklistStatus.NEEDS_CONFIRMATION
            evidence = "No named exceptions for any failure path."
        return ChecklistItem(
            id="R7-exceptions",
            requirement="Failure paths are named as exceptions.",
            category="exceptions",
            severity=ChecklistSeverity.OPTIONAL,
            status=status,
            evidence=evidence,
            question=(
                None
                if status == ChecklistStatus.SATISFIED
                else "Which failures should the workflow handle, and what are they named?"
            ),
        )

    @staticmethod
    def _retries_present(structure: WorkflowStructure, retries: list) -> ChecklistItem:  # type: ignore[type-arg]
        if not structure.activities:
            status = ChecklistStatus.SATISFIED
            evidence = "No activities that could need retries."
        elif retries:
            status = ChecklistStatus.SATISFIED
            evidence = f"{len(retries)} retry policy/policies declared."
        else:
            status = ChecklistStatus.NEEDS_CONFIRMATION
            evidence = "No retry policies declared; activities will use the workflow default."
        return ChecklistItem(
            id="R8-retries",
            requirement="Retry policies are stated for activities that need them.",
            category="retries",
            severity=ChecklistSeverity.OPTIONAL,
            status=status,
            evidence=evidence,
            question=(
                None
                if status == ChecklistStatus.SATISFIED
                else "Which activities should retry, how many times, and with what backoff?"
            ),
        )

    @staticmethod
    def _state_transitions(transitions: list) -> ChecklistItem:  # type: ignore[type-arg]
        has = bool(transitions)
        return ChecklistItem(
            id="R9-state-transitions",
            requirement="No free-form state transitions (they do not map to Temporal).",
            category="structure",
            severity=ChecklistSeverity.OPTIONAL,
            status=ChecklistStatus.NEEDS_CONFIRMATION if has else ChecklistStatus.SATISFIED,
            evidence=(
                f"{len(transitions)} state-transition fact(s) present; these are not "
                "modeled as Temporal steps."
                if has
                else "No free-form state transitions."
            ),
            question=(
                "Confirm these state transitions are descriptive only (they will be ignored "
                "by code generation)."
                if has
                else None
            ),
        )
