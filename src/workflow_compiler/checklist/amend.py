"""Fold checklist answers back into the workflow state as deterministic edits.

This is the "local amendment" path: the user's answers from the filled-in report
are applied directly to ``metadata``/``facts``/``structure`` with no LLM call, so
re-validation is instant and free. Additive answers (trigger, inputs, outputs) are
applied structurally; relational fixes (compensation binding, a decision's 'no'
branch) are resolved by id or name against what the workflow actually declares.

**Answering is not the same as clearing.** A REQUIRED item is cleared only by a
structural repair (or by an explicit ``accept_as_is`` override) — never by the mere
presence of an answer, because generating code from a structure we failed to repair
would silently drop a branch. An answer we could not apply is recorded on the item
and called out in its evidence, so the gate can tell the user their answer landed but
did nothing, and name the edit that would work. Optional items, which gate nothing,
are cleared by any answer.

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
from workflow_compiler.models.structure import TERMINAL_TARGETS

#: Split a free-text answer into items on commas / semicolons / newlines.
_SPLIT = re.compile(r"[,;\n]+")
#: A "left <sep> right" pair, e.g. "Release inventory -> Reserve inventory".
_PAIR = re.compile(r"^(.*?)\s*(?:->|:|\breverses\b|\bcompensates\b)\s*(.*)$", re.IGNORECASE)
#: A separator-less pair whose left is a bare id, e.g. "d1 CartNotEligible". Only
#: honoured when the left side names a declared node, so prose cannot match by accident.
_LOOSE_PAIR = re.compile(r"^(\S+)\s+(.+)$")
#: A name we are willing to declare as a *new* exception: name-shaped, not a sentence.
_EXCEPTION_NAME = re.compile(r"^[A-Za-z][\w-]*(?:\s+[\w-]+){0,3}$")


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
        elif was_answered:
            # Answered, still unmet: the answer could not be turned into a
            # structural edit. Say so on the item — silently re-asking the original
            # question would tell the user nothing about why their answer failed.
            item.evidence = (
                f"{item.evidence} Your answer was recorded but could not be applied "
                f'automatically: "{item.answer}".'
            ).strip()
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
    """Route each unrouted decision's 'no' branch to the target the answer names.

    The left of a pair identifies the decision (``d1``, or its question text); the
    right names the target — an exception id (``e1``), an exception name
    (``CartNotEligible``), an activity, a terminal token, or a new exception to
    declare. ``d1 -> CartNotEligible``, ``d1: e1`` and ``d1 CartNotEligible`` all work,
    and a target named anywhere in a sentence is found (``d1 - raise CartNotEligible
    and stop``).

    A pair whose left side names no declared decision is ignored, and an answer with no
    pairs at all is applied **only** when exactly one decision is unrouted and the
    answer resolves to exactly one target — otherwise which decision the user meant is
    a guess, and a mis-wired branch is worse than a blocked spec.
    """
    unrouted = [d for d in structure.decisions if not d.no_target or d.no_target == d.after]
    if not unrouted:
        return structure

    keys = {d.id.lower() for d in structure.decisions}
    keys |= {d.question.strip().lower() for d in structure.decisions}

    routes: dict[str, str] = {}  # decision key(lower) -> raw target text
    unattributed: list[str] = []
    for piece in _items(answer):
        pair = _PAIR.match(piece) or _LOOSE_PAIR.match(piece)
        if pair and pair.group(1).strip().lower() in keys:
            routes[pair.group(1).strip().lower()] = pair.group(2).strip()
        else:
            unattributed.append(piece)

    if not routes and len(unrouted) == 1:
        # Unambiguous: one open branch, so an answer that names one target can only
        # mean that one.
        target = _resolve_target(structure, answer)
        if target:
            routes[unrouted[0].id.lower()] = target
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
        raw = routes.get(d.id.lower()) or routes.get(d.question.strip().lower())
        if not raw:
            decisions.append(d)
            continue
        target = _resolve_target(structure, raw)
        if target is None:
            # Nothing declared matches — treat the answer as a new exception to
            # declare, but only if it reads like a name rather than a sentence.
            name = raw.strip()
            if not _EXCEPTION_NAME.match(name):
                decisions.append(d)
                continue
            next_index += 1
            target = f"e{next_index}"
            exceptions.append(ExceptionNode(id=target, reason=name, raised_by=d.after))
            exc_id_by_reason[name.lower()] = target
        decisions.append(d.model_copy(update={"no_target": target}))

    return structure.model_copy(update={"decisions": decisions, "exceptions": exceptions})


def _resolve_target(structure: WorkflowStructure, text: str) -> str | None:
    """Resolve ``text`` to a declared node id or terminal token, else None.

    Matches an id or a full name exactly first, then looks for a declared exception /
    activity name or a terminal token *mentioned inside* the text, so a sentence like
    "raise CartNotEligible and reject" resolves to that exception's id.
    """
    key = text.strip().strip("`'\"").lower()
    if not key:
        return None

    candidates: list[tuple[str, str]] = [(x.id, x.reason) for x in structure.exceptions]
    candidates += [(a.id, a.name) for a in structure.activities]
    for node_id, name in candidates:
        if key in (node_id.lower(), name.strip().lower()):
            return node_id
    if key in TERMINAL_TARGETS:
        return key

    # Fall back to a mention inside a longer phrase; longest name first so
    # "CartNotEligible" wins over a shorter name that is a substring of it.
    for node_id, name in sorted(candidates, key=lambda c: -len(c[1])):
        if name.strip() and re.search(rf"\b{re.escape(name.strip().lower())}\b", key):
            return node_id
    for terminal in TERMINAL_TARGETS:
        if re.search(rf"\b{re.escape(terminal)}\b", key):
            return terminal
    return None
