"""Tests for the free-form spec chat (prose instructions → patches).

Same shape as ``test_dialogue.py``: the engine runs its real orchestration
against an exact ``MockProvider`` queue, so everything after the LLM call is the
production path. What is asserted is the behavior the design fixes — that an
instruction applies immediately, that a vague one earns exactly one clarifying
question, that an unmappable one is parked rather than lost, that the target
workflow is resolved safely, and that a changed spec re-arms the approval gate.
"""

from __future__ import annotations

import pytest

from workflow_compiler.dialogue import SpecChatEngine
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    ApprovalStatus,
    ChatRole,
    ChatTurnStatus,
    CompilationProject,
    InstructionPlan,
    Patch,
    PatchAction,
    ProjectStage,
    Provenance,
    Severity,
    SpecChatSession,
    SpecFinding,
    SuggestedOption,
    WorkflowMetadata,
    WorkflowSpec,
)

_DOCUMENT = "The order workflow captures an order and ships it."


def _spec(slug: str = "order-fulfillment", name: str = "Order Fulfillment") -> WorkflowSpec:
    """A minimal spec with a semver version, so bumps are observable."""
    return WorkflowSpec(
        slug=slug,
        metadata=WorkflowMetadata(name=name, purpose="Fulfill an order.", version="0.1.0"),
    )


def _project(*slugs: str) -> CompilationProject:
    specs = [_spec(s) for s in (slugs or ("order-fulfillment",))]
    project = CompilationProject(document_text=_DOCUMENT, specs=specs)
    project.stage = ProjectStage.SPEC_VALIDATED
    project.spec_approval_status = ApprovalStatus.APPROVED
    return project


def _add_actor(value: str = "Warehouse") -> Patch:
    return Patch(action=PatchAction.ADD, target="actors", payload={"value": value})


def _plan(**kwargs: object) -> InstructionPlan:
    return InstructionPlan(**kwargs)  # type: ignore[arg-type]


def _engine(provider: MockProvider) -> SpecChatEngine:
    return SpecChatEngine(provider)


# --------------------------------------------------------------------------- #
# Opening
# --------------------------------------------------------------------------- #


def test_start_needs_no_validate_run() -> None:
    """The guided dialogue needs findings; a chat has no agenda, so it does not."""
    project = _project()
    project.stage = ProjectStage.SPEC_DRAFTED
    project.validation_findings = {}

    session = SpecChatEngine.start(project)

    assert session.turns == []
    assert not session.awaiting_clarification


def test_start_rejects_a_project_with_no_specs() -> None:
    project = CompilationProject(document_text=_DOCUMENT)

    with pytest.raises(CompilationError, match="no specifications"):
        SpecChatEngine.start(project)


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #


async def test_instruction_applies_immediately_and_bumps_the_version() -> None:
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[
            _plan(
                target_slug="order-fulfillment",
                patches=[_add_actor()],
                reply="Added Warehouse as an actor.",
            )
        ]
    )

    outcome = await _engine(provider).send(project, session, "warehouse should be an actor")

    assert outcome.status is ChatTurnStatus.APPLIED
    assert outcome.applied
    assert "Warehouse" in project.specs[0].metadata.actors
    assert project.specs[0].metadata.version == "0.1.1"
    assert any("version bumped to 0.1.1" in line for line in outcome.changes)
    assert outcome.reply == "Added Warehouse as an actor."


async def test_an_applied_change_is_human_provenance() -> None:
    """Instructions carry human authority — additions need no document grounding."""
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(structured=[_plan(patches=[_add_actor()])])

    await _engine(provider).send(project, session, "add warehouse")

    assert project.specs[0].provenance["actors:Warehouse"] is Provenance.HUMAN_PROVIDED


async def test_an_applied_change_re_arms_the_approval_gate() -> None:
    """A changed spec must not stay approved against a validation that predates it."""
    project = _project()
    project.validation_findings = {
        "order-fulfillment": [
            SpecFinding(severity=Severity.BLOCKING, workflow="order-fulfillment", message="x")
        ]
    }
    session = SpecChatEngine.start(project)
    provider = MockProvider(structured=[_plan(patches=[_add_actor()])])

    await _engine(provider).send(project, session, "add warehouse")

    assert project.stage is ProjectStage.SPEC_DRAFTED
    assert project.spec_approval_status is ApprovalStatus.PENDING
    # No agenda to preserve, so stale findings go immediately (unlike the
    # guided dialogue, which needs them until the session ends).
    assert "order-fulfillment" not in project.validation_findings


async def test_already_satisfied_changes_nothing() -> None:
    project = _project()
    project.specs[0].metadata.actors = ["Warehouse"]
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[_plan(already_satisfied=True, reply="Warehouse is already an actor.")]
    )

    outcome = await _engine(provider).send(project, session, "add warehouse as an actor")

    assert outcome.status is ChatTurnStatus.NO_CHANGE
    assert project.specs[0].metadata.version == "0.1.0"
    assert project.spec_approval_status is ApprovalStatus.APPROVED


# --------------------------------------------------------------------------- #
# Clarifying — exactly one, then act
# --------------------------------------------------------------------------- #


async def test_a_vague_instruction_earns_one_clarifying_question() -> None:
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[
            _plan(needs_clarification=True, clarifying_question="Which step is missing?")
        ]
    )

    outcome = await _engine(provider).send(project, session, "make the cancel path better")

    assert outcome.status is ChatTurnStatus.CLARIFYING
    assert outcome.reply == "Which step is missing?"
    assert session.awaiting_clarification
    assert session.pending_instruction == "make the cancel path better"
    assert project.specs[0].metadata.version == "0.1.0"


async def test_the_reply_to_a_clarification_carries_the_original_instruction() -> None:
    """Both halves reach the interpreter — the reply alone is meaningless."""
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[
            _plan(needs_clarification=True, clarifying_question="Which step?"),
            _plan(patches=[_add_actor()], reply="Done."),
        ]
    )
    engine = _engine(provider)

    await engine.send(project, session, "make the cancel path better")
    outcome = await engine.send(project, session, "the refund step")

    assert outcome.status is ChatTurnStatus.APPLIED
    prompt = provider.calls[1][1]
    assert "make the cancel path better" in prompt
    assert "Which step?" in prompt
    assert not session.awaiting_clarification


async def test_a_second_clarification_is_never_asked() -> None:
    """The bound is one per instruction; a still-vague reply is parked instead."""
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[
            _plan(needs_clarification=True, clarifying_question="Which step?"),
            _plan(needs_clarification=True, clarifying_question="But which one really?"),
        ]
    )
    engine = _engine(provider)

    await engine.send(project, session, "make it better")
    outcome = await engine.send(project, session, "you know, the usual")

    assert outcome.status is ChatTurnStatus.PARKED
    assert not session.awaiting_clarification


# --------------------------------------------------------------------------- #
# Parking — never discard what the user said
# --------------------------------------------------------------------------- #


async def test_an_unmappable_instruction_is_parked_as_an_open_question() -> None:
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[_plan(park_note="The owner of this workflow is undecided.")]
    )

    outcome = await _engine(provider).send(project, session, "who owns this anyway?")

    assert outcome.status is ChatTurnStatus.PARKED
    parked = project.specs[0].open_questions[-1]
    assert parked.text == "The owner of this workflow is undecided."
    assert parked.provenance is Provenance.HUMAN_PROVIDED
    assert parked.resolved is False
    assert parked.ref == f"chat:{session.session_id}"


async def test_parking_falls_back_to_the_users_own_words() -> None:
    """A plan with no park_note must still keep what the user said."""
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(structured=[_plan()])

    await _engine(provider).send(project, session, "ops owns that, not decided yet")

    assert project.specs[0].open_questions[-1].text == "ops owns that, not decided yet"


# --------------------------------------------------------------------------- #
# Choosing the target workflow
# --------------------------------------------------------------------------- #


async def test_an_unknown_slug_is_rejected_rather_than_redirected() -> None:
    """Silently patching a different spec than the one on screen is the bad outcome."""
    project = _project("onboarding", "provisioning")
    session = SpecChatEngine.start(project)

    with pytest.raises(CompilationError, match="No workflow 'billing'"):
        await _engine(MockProvider()).send(project, session, "add x", slug="billing")


async def test_the_agent_may_retarget_to_another_real_workflow() -> None:
    project = _project("onboarding", "provisioning")
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[_plan(target_slug="provisioning", patches=[_add_actor()])]
    )

    outcome = await _engine(provider).send(
        project, session, "provisioning needs a warehouse actor", slug="onboarding"
    )

    assert outcome.slug == "provisioning"
    assert "Warehouse" in project.spec_for("provisioning").metadata.actors  # type: ignore[union-attr]
    assert project.spec_for("onboarding").metadata.actors == []  # type: ignore[union-attr]


async def test_a_hallucinated_target_slug_is_ignored() -> None:
    """Patching an invented workflow is worse than patching the one on screen."""
    project = _project("onboarding")
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[_plan(target_slug="does-not-exist", patches=[_add_actor()])]
    )

    outcome = await _engine(provider).send(project, session, "add warehouse")

    assert outcome.slug == "onboarding"
    assert "Warehouse" in project.specs[0].metadata.actors


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #


async def test_the_transcript_records_both_sides() -> None:
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(structured=[_plan(patches=[_add_actor()], reply="Added it.")])

    await _engine(provider).send(project, session, "add warehouse")

    assert [t.role for t in session.turns] == [ChatRole.USER, ChatRole.ASSISTANT]
    assert session.turns[0].text == "add warehouse"
    assert session.turns[1].text == "Added it."
    assert session.applied_count == 1


async def test_prior_turns_are_context_for_the_next_instruction() -> None:
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[
            _plan(patches=[_add_actor()], reply="Added Warehouse."),
            _plan(patches=[_add_actor("Billing")], reply="Added Billing."),
        ]
    )
    engine = _engine(provider)

    await engine.send(project, session, "add warehouse")
    await engine.send(project, session, "and billing too")

    prompt = provider.calls[1][1]
    assert "add warehouse" in prompt
    assert "Added Warehouse." in prompt


async def test_an_empty_message_is_rejected() -> None:
    project = _project()
    session = SpecChatEngine.start(project)

    with pytest.raises(CompilationError, match="cannot be empty"):
        await _engine(MockProvider()).send(project, session, "   ")


async def test_a_forbidden_second_clarification_does_not_reply_with_a_question() -> None:
    """Observed live: the model re-asks in `reply` after being denied a second
    clarification, so the user is told to "please specify…" just as their answer
    is parked. The engine owns the disposition, so it owns the sentence."""
    project = _project()
    session = SpecChatEngine.start(project)
    provider = MockProvider(
        structured=[
            _plan(needs_clarification=True, clarifying_question="Which step?"),
            _plan(
                needs_clarification=True,
                clarifying_question="But which one?",
                reply="Please specify whether a step is missing.",
            ),
        ]
    )
    engine = _engine(provider)

    await engine.send(project, session, "make it better")
    outcome = await engine.send(project, session, "not sure, ops owns it")

    assert outcome.status is ChatTurnStatus.PARKED
    assert "recorded it" in outcome.reply
    assert "Please specify" not in outcome.reply


# --------------------------------------------------------------------------- #
# Suggested replies to a clarifying question
# --------------------------------------------------------------------------- #


async def test_clarifying_question_carries_suggested_replies() -> None:
    """The chat asks one clarifying question per instruction, and that is exactly
    where concrete choices help — the user was vague because the specifics were
    not to hand."""
    project = _project()
    provider = MockProvider(
        structured=[
            _plan(
                needs_clarification=True,
                clarifying_question="Which step is missing?",
                clarifying_options=[
                    SuggestedOption(label="We never tell the customer.", detail="Adds a step."),
                    SuggestedOption(label="We never release the inventory."),
                    SuggestedOption(label="   "),
                ],
            )
        ]
    )
    session = SpecChatSession()

    outcome = await _engine(provider).send(project, session, "the cancel path needs work")

    assert outcome.status is ChatTurnStatus.CLARIFYING
    # Blank labels are dropped rather than rendered as empty buttons.
    assert [o.label for o in session.pending_options] == [
        "We never tell the customer.",
        "We never release the inventory.",
    ]
    assert [o.label for o in outcome.turn.options] == [
        "We never tell the customer.",
        "We never release the inventory.",
    ]


async def test_choosing_a_suggested_reply_is_recorded_and_interpreted_normally() -> None:
    project = _project()
    provider = MockProvider(
        structured=[
            _plan(
                needs_clarification=True,
                clarifying_question="Which step is missing?",
                clarifying_options=[SuggestedOption(label="We never tell the customer.")],
            ),
            _plan(patches=[_add_actor()]),
        ]
    )
    engine = _engine(provider)
    session = SpecChatSession()
    await engine.send(project, session, "the cancel path needs work")

    outcome = await engine.send(
        project,
        session,
        "We never tell the customer.",
        chosen_option="We never tell the customer.",
    )

    assert outcome.applied
    user_turn = next(t for t in reversed(session.turns) if t.role is ChatRole.USER)
    assert user_turn.chosen_option == "We never tell the customer."
    # The reply still went through the interpreter, exactly as typed prose would.
    assert "We never tell the customer." in provider.calls[1][1]


async def test_a_reply_that_was_never_offered_is_not_recorded_as_chosen() -> None:
    project = _project()
    provider = MockProvider(
        structured=[
            _plan(
                needs_clarification=True,
                clarifying_question="Which step is missing?",
                clarifying_options=[SuggestedOption(label="We never tell the customer.")],
            ),
            _plan(patches=[_add_actor()]),
        ]
    )
    engine = _engine(provider)
    session = SpecChatSession()
    await engine.send(project, session, "the cancel path needs work")

    await engine.send(
        project, session, "Something else.", chosen_option="Something else."
    )

    user_turn = next(t for t in reversed(session.turns) if t.role is ChatRole.USER)
    assert user_turn.chosen_option is None


async def test_pending_options_are_cleared_once_the_clarification_is_answered() -> None:
    """A spent question's suggestions must not linger and be re-offered."""
    project = _project()
    provider = MockProvider(
        structured=[
            _plan(
                needs_clarification=True,
                clarifying_question="Which step is missing?",
                clarifying_options=[SuggestedOption(label="We never tell the customer.")],
            ),
            _plan(patches=[_add_actor()]),
        ]
    )
    engine = _engine(provider)
    session = SpecChatSession()
    await engine.send(project, session, "the cancel path needs work")
    assert session.pending_options

    await engine.send(project, session, "We never tell the customer.")

    assert session.pending_options == []
    assert not session.awaiting_clarification
