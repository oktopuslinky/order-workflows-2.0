"""Fold checklist answers back into the workflow state as deterministic edits.

This is the "local amendment" path: the user's answers from the filled-in report
are applied directly to ``metadata``/``facts``/``structure`` with no LLM call, so
re-validation is instant and free. Additive answers (trigger, inputs, outputs) are
applied structurally; relational fixes (compensation binding, a decision's 'no'
branch) are best-effort by name. Any item the user answered is at minimum recorded
and marked ``accepted`` so an explicit answer always clears the gate, while the
underlying structure is improved wherever we can do so safely.

After any structural edit the structure is re-``validated()`` (per the
referential-integrity invariant) and the checklist is recomputed.
"""

from __future__ import annotations

import re

from workflow_compiler.checklist.validator import ChecklistValidator
from workflow_compiler.models import (
    ExceptionNode,
    FactCategory,
    WorkflowFact,
    WorkflowFacts,
    WorkflowState,
    WorkflowStructure,
)
from workflow_compiler.models.checklist import ChecklistSeverity, ChecklistStatus

#: Split a free-text answer into items on commas / semicolons / newlines.
_SPLIT = re.compile(r"[,;\n]+")
#: A "left <sep> right" pair, e.g. "Release inventory -> Reserve inventory".
_PAIR = re.compile(r"^(.*?)\s*(?:->|:|\breverses\b|\bcompensates\b)\s*(.*)$", re.IGNORECASE)


def _items(answer: str) -> list[str]:
    """Split an answer into trimmed, non-empty items."""
    return [piece.strip() for piece in _SPLIT.split(answer) if piece.strip()]


def apply(
    state: WorkflowState, answers: dict[str, str], *, accept_as_is: bool = False
) -> WorkflowState:
    """Apply ``answers`` to ``state`` and recompute the checklist.

    ``answers`` maps checklist item id -> the user's text. ``accept_as_is`` clears
    any items that remain unmet after the structural edits (optional items always,
    and answered/explicitly-acknowledged required items).
    """
    facts = state.workflow_facts or WorkflowFacts()
    structure = facts.structure or WorkflowStructure()
    extra_facts: list[WorkflowFact] = []

    for item_id, answer in answers.items():
        if not answer.strip():
            continue
        if item_id == "R1-trigger":
            _add_triggers(state, answer)
        elif item_id == "R2-inputs":
            extra_facts += _new_facts(FactCategory.INPUT, _items(answer), facts)
        elif item_id == "R3-outputs":
            extra_facts += _new_facts(FactCategory.OUTPUT, _items(answer), facts)
        elif item_id == "R5-compensations":
            structure = _bind_compensations(structure, answer)
        elif item_id == "R4-decisions":
            structure = _route_decisions(structure, answer)

    if extra_facts:
        facts = facts.model_copy(update={"facts": [*facts.facts, *extra_facts]})
    # Re-run the referential-integrity guard after any structural edit.
    structure, _warnings = structure.validated()
    facts = facts.model_copy(update={"structure": structure})
    state.workflow_facts = facts

    checklist = ChecklistValidator().validate(state)

    # Record answers on their items, and clear per accept-as-is.
    for item in checklist.items:
        was_answered = item.id in answers and answers[item.id].strip() != ""
        if was_answered:
            item.answer = answers[item.id].strip()
        if item.is_cleared():
            continue
        # accept_as_is is the explicit override: it clears every remaining gap.
        # Short of that, answering an optional item acknowledges and clears it.
        is_optional = item.severity == ChecklistSeverity.OPTIONAL
        if accept_as_is or (is_optional and was_answered):
            item.status = ChecklistStatus.ACCEPTED
    state.checklist = checklist
    state.touch()
    return state


# -- structural edits -------------------------------------------------------


def _add_triggers(state: WorkflowState, answer: str) -> None:
    """Append trigger event(s) to the metadata (creating none from thin air)."""
    meta = state.workflow_metadata
    if meta is None:
        return
    existing = {t.lower() for t in meta.trigger_events}
    additions = [t for t in _items(answer) if t.lower() not in existing]
    if additions:
        state.workflow_metadata = meta.model_copy(
            update={"trigger_events": [*meta.trigger_events, *additions]}
        )


def _new_facts(
    category: FactCategory, statements: list[str], facts: WorkflowFacts
) -> list[WorkflowFact]:
    """Build new flat facts for ``category``, skipping case-insensitive duplicates."""
    existing = {f.statement.lower() for f in facts.by_category(category)}
    start = len(facts.by_category(category))
    out: list[WorkflowFact] = []
    for offset, statement in enumerate(statements, start=1):
        if statement.lower() in existing:
            continue
        existing.add(statement.lower())
        out.append(
            WorkflowFact(
                id=f"{category.value}-{start + offset}",
                statement=statement,
                category=category,
                confidence=1.0,
            )
        )
    return out


def _activity_id_by_name(structure: WorkflowStructure, needle: str) -> str | None:
    """Find a declared activity id whose name matches/contains ``needle``."""
    key = needle.strip().lower()
    if not key:
        return None
    for a in structure.activities:
        if a.name.lower() == key:
            return a.id
    for a in structure.activities:
        if key in a.name.lower() or a.name.lower() in key:
            return a.id
    return None


def _bind_compensations(structure: WorkflowStructure, answer: str) -> WorkflowStructure:
    """Bind unbound compensations to activities named in ``answer``.

    Accepts pairs like ``Release inventory -> Reserve inventory`` or
    ``Release inventory reverses Reserve inventory``.
    """
    bindings: dict[str, str] = {}  # comp-name(lower) -> activity name
    for piece in _items(answer):
        pair = _PAIR.match(piece)
        if pair:
            bindings[pair.group(1).strip().lower()] = pair.group(2).strip()

    comps = []
    for c in structure.compensations:
        if (not c.compensates or c.compensates not in structure.activity_ids()):
            target_name = bindings.get(c.name.lower())
            if target_name:
                activity_id = _activity_id_by_name(structure, target_name)
                if activity_id:
                    comps.append(c.model_copy(update={"compensates": activity_id}))
                    continue
        comps.append(c)
    return structure.model_copy(update={"compensations": comps})


def _route_decisions(structure: WorkflowStructure, answer: str) -> WorkflowStructure:
    """Route a decision's 'no' branch to a (possibly new) named exception.

    Accepts pairs like ``d1 -> OrderNotSettleable`` (decision id / question on the
    left, exception name on the right).
    """
    routes: dict[str, str] = {}  # decision key(lower) -> exception name
    for piece in _items(answer):
        pair = _PAIR.match(piece)
        if pair:
            routes[pair.group(1).strip().lower()] = pair.group(2).strip()
    if not routes:
        return structure

    exceptions = list(structure.exceptions)
    exc_id_by_reason = {x.reason.lower(): x.id for x in exceptions}
    next_index = len(exceptions)

    decisions = []
    for d in structure.decisions:
        if d.no_target and d.no_target != d.after:
            decisions.append(d)
            continue
        exc_name = routes.get(d.id.lower()) or routes.get(d.question.lower())
        if not exc_name:
            decisions.append(d)
            continue
        exc_id = exc_id_by_reason.get(exc_name.lower())
        if exc_id is None:
            next_index += 1
            exc_id = f"e{next_index}"
            exceptions.append(
                ExceptionNode(id=exc_id, reason=exc_name, raised_by=d.after)
            )
            exc_id_by_reason[exc_name.lower()] = exc_id
        decisions.append(d.model_copy(update={"no_target": exc_id}))

    return structure.model_copy(update={"decisions": decisions, "exceptions": exceptions})
