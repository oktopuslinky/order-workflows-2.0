"""Tests for the readiness checklist.

Covers the deterministic validator and the local-amendment path (the machinery
behind the spec's Open Questions) — all offline.
"""

from __future__ import annotations

from workflow_compiler.checklist import ChecklistValidator
from workflow_compiler.checklist import amend as checklist_amend
from workflow_compiler.models import (
    ActivityNode,
    ChecklistStatus,
    CompensationNode,
    DecisionNode,
    EventNode,
    ExceptionNode,
    FactCategory,
    WorkflowFact,
    WorkflowFacts,
    WorkflowMetadata,
    WorkflowState,
    WorkflowStructure,
)
from workflow_compiler.models.checklist import ChecklistSeverity


def _fact(category: FactCategory, statement: str, index: int = 1) -> WorkflowFact:
    return WorkflowFact(
        id=f"{category.value}-{index}", statement=statement, category=category, confidence=1.0
    )


def _ideal_state() -> WorkflowState:
    """A state shaped like examples/ideal_temporal_workflow.md — clears every item."""
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Reserve inventory"),
            ActivityNode(id="a2", name="Charge payment"),
        ],
        decisions=[
            DecisionNode(
                id="d1", question="Is the charge approved?", after="a2",
                yes_target="a1", no_target="e1",
            )
        ],
        exceptions=[ExceptionNode(id="e1", reason="PaymentDeclined", raised_by="a2")],
        compensations=[CompensationNode(id="c1", name="Release inventory", compensates="a1")],
    )
    facts = WorkflowFacts(
        facts=[
            _fact(FactCategory.INPUT, "order_id — the order to settle", 1),
            _fact(FactCategory.INPUT, "amount — total to charge", 2),
            _fact(FactCategory.OUTPUT, "settlement_id — completed settlement", 1),
            _fact(FactCategory.RETRY, "Reserve inventory retries 3x", 1),
        ],
        structure=structure,
    )
    return WorkflowState(
        document_text="ideal",
        workflow_metadata=WorkflowMetadata(
            name="Order Settlement", trigger_events=["order.settle received"]
        ),
        workflow_facts=facts,
    )


def _broken_state() -> WorkflowState:
    """Missing trigger, no inputs, an unbranched decision, an unbound compensation."""
    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Reserve inventory")],
        decisions=[DecisionNode(id="d1", question="Is it valid?", after="a1", yes_target="a1")],
        compensations=[CompensationNode(id="c1", name="Release inventory")],
        events=[EventNode(id="v1", name="shipping confirmed", emitted_by="a1")],
    )
    facts = WorkflowFacts(facts=[], structure=structure)
    return WorkflowState(
        document_text="broken",
        workflow_metadata=WorkflowMetadata(name="Broken", trigger_events=[]),
        workflow_facts=facts,
    )


# -- validator --------------------------------------------------------------


def test_ideal_state_clears_every_required_item() -> None:
    checklist = ChecklistValidator().validate(_ideal_state())
    assert checklist.is_satisfied()
    assert checklist.unmet_required() == []
    # Nothing should even need confirmation for the ideal document.
    assert all(item.is_cleared() for item in checklist.items)


def test_broken_state_flags_exactly_the_missing_required_items() -> None:
    checklist = ChecklistValidator().validate(_broken_state())
    blocking = {item.id for item in checklist.unmet_required()}
    assert blocking == {"R1-trigger", "R2-inputs", "R4-decisions", "R5-compensations"}
    assert not checklist.is_satisfied()


def test_unbounded_wait_is_optional_not_blocking() -> None:
    checklist = ChecklistValidator().validate(_broken_state())
    waits = next(i for i in checklist.items if i.id == "R6-bounded-waits")
    assert waits.severity == ChecklistSeverity.OPTIONAL
    assert waits.status == ChecklistStatus.NEEDS_CONFIRMATION


def test_non_snake_input_names_need_confirmation() -> None:
    state = _ideal_state()
    state.workflow_facts.facts.append(_fact(FactCategory.INPUT, "customerId — the payer", 3))
    checklist = ChecklistValidator().validate(state)
    names = next(i for i in checklist.items if i.id == "R2b-input-names")
    assert names.status == ChecklistStatus.NEEDS_CONFIRMATION
    assert "customerId" in (names.evidence or "")


# -- amendment --------------------------------------------------------------


def test_amend_applies_answers_and_clears_the_gate() -> None:
    state = _broken_state()
    state.checklist = ChecklistValidator().validate(state)
    answers = {
        "R1-trigger": "order.received",
        "R2-inputs": "order_id, amount",
        "R4-decisions": "d1 -> OrderInvalid",
        "R5-compensations": "Release inventory -> Reserve inventory",
    }
    result = checklist_amend.apply(state, answers)

    assert result.checklist is not None
    assert result.checklist.is_satisfied()
    # Trigger landed on the metadata.
    assert "order.received" in result.workflow_metadata.trigger_events
    # Inputs became INPUT facts.
    inputs = [f.statement for f in result.workflow_facts.by_category(FactCategory.INPUT)]
    assert "order_id" in inputs and "amount" in inputs
    # Compensation got bound to the activity it reverses.
    comp = result.workflow_facts.structure.compensations[0]
    assert comp.compensates == "a1"
    # Decision's 'no' branch routes to a real exception node now.
    decision = result.workflow_facts.structure.decisions[0]
    assert decision.no_target is not None and decision.no_target != decision.after


def test_accept_as_is_clears_remaining_required_items() -> None:
    state = _broken_state()
    state.checklist = ChecklistValidator().validate(state)
    # Answer only the trigger; accept the rest as-is.
    result = checklist_amend.apply(state, {"R1-trigger": "order.received"}, accept_as_is=True)
    assert result.checklist.is_satisfied()
