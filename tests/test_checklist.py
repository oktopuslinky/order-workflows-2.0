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


def _two_unrouted_decisions() -> WorkflowState:
    """The shape that broke order-placement: both 'no' branches left unwired."""
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate cart"),
            ActivityNode(id="a2", name="Reserve inventory"),
            ActivityNode(id="a3", name="Authorise payment"),
            ActivityNode(id="a4", name="Create the order"),
        ],
        decisions=[
            DecisionNode(id="d1", question="Is cart eligible?", after="a1", yes_target="a2"),
            DecisionNode(id="d2", question="Is payment authorised?", after="a3", yes_target="a4"),
        ],
        exceptions=[
            ExceptionNode(id="e1", reason="CartNotEligible"),
            ExceptionNode(id="e2", reason="PaymentDeclined"),
        ],
    )
    state = WorkflowState(
        document_text="placement",
        workflow_metadata=WorkflowMetadata(name="Order Placement", trigger_events=["checkout"]),
        workflow_facts=WorkflowFacts(
            facts=[_fact(FactCategory.INPUT, "cart_id — the cart", 1)], structure=structure
        ),
    )
    state.checklist = ChecklistValidator().validate(state)
    return state


def test_decisions_answer_names_the_exact_spec_edit() -> None:
    """R4's question must name the offending ids and the line to write, not ask prose."""
    item = next(
        i for i in _two_unrouted_decisions().checklist.items if i.id == "R4-decisions"
    )
    question = item.question or ""
    assert "d1" in question and "d2" in question
    assert "Decisions section" in question
    assert "no: e1" in question  # the literal edit that clears it


def test_suggested_line_matches_the_rendered_spec() -> None:
    """The line we tell the user to write must be the line the spec file actually uses.

    A suggestion in the wrong format is worse than none — the user pastes it, the
    deterministic ingest does not recognise it, and the gate stays shut for no visible
    reason. Pin the checklist's copy to the renderer's real output.
    """
    from workflow_compiler.models import WorkflowSpec
    from workflow_compiler.spec import render_spec

    state = _two_unrouted_decisions()
    state.workflow_facts.structure.decisions[1].no_target = "e2"  # leave only d1 open
    item = next(
        i for i in ChecklistValidator().validate(state).items if i.id == "R4-decisions"
    )
    # The line the user is told to paste, quoted in backticks inside the question.
    suggested = (item.question or "").split("`")[1]

    # Now wire d1 exactly as the suggestion says and render the spec for real.
    state.workflow_facts.structure.decisions[0].no_target = "e1"
    spec = WorkflowSpec(
        slug="order-placement",
        metadata=state.workflow_metadata,
        facts=state.workflow_facts,
    )
    rendered = {line.strip() for line in render_spec(spec, [], []).splitlines()}
    assert suggested in rendered, f"{suggested!r} is not a line the renderer emits"


def test_prose_answer_is_reported_not_silently_dropped() -> None:
    """The exact failing answer: prose naming one exception, two decisions unrouted.

    It cannot be attributed to a decision, so the gate stays shut — but the item must
    say the answer was received and not applied, rather than silently re-asking.
    """
    state = _two_unrouted_decisions()
    answer = "On decline, raise PaymentDeclined and cancel the order"
    result = checklist_amend.apply(state, {"R4-decisions": answer})

    assert not result.checklist.is_satisfied()
    item = next(i for i in result.checklist.items if i.id == "R4-decisions")
    assert item.answer == answer
    assert "could not be applied" in (item.evidence or "")
    # And nothing was wired on a guess.
    assert all(d.no_target is None for d in result.workflow_facts.structure.decisions)


def test_attributed_answers_route_each_decision() -> None:
    """Every documented answer form resolves: id, name, and a name inside a sentence."""
    for answer in (
        "d1 -> e1\nd2 -> e2",
        "d1 -> CartNotEligible\nd2 -> PaymentDeclined",
        "d1: e1; d2: e2",
        "d1 CartNotEligible\nd2 PaymentDeclined",
        "d1 - raise CartNotEligible and stop\nd2 - raise PaymentDeclined and stop",
    ):
        result = checklist_amend.apply(_two_unrouted_decisions(), {"R4-decisions": answer})
        decisions = result.workflow_facts.structure.decisions
        assert [d.no_target for d in decisions] == ["e1", "e2"], answer
        assert result.checklist.is_satisfied(), answer


def test_sole_unrouted_decision_accepts_an_unattributed_answer() -> None:
    """One open branch means an answer naming one target is unambiguous — apply it."""
    state = _two_unrouted_decisions()
    state.workflow_facts.structure.decisions.pop()  # leave only d1 open
    state.checklist = ChecklistValidator().validate(state)

    result = checklist_amend.apply(
        state, {"R4-decisions": "reject the checkout with CartNotEligible"}
    )
    assert result.workflow_facts.structure.decisions[0].no_target == "e1"
    assert result.checklist.is_satisfied()
