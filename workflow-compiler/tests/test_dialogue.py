"""Tests for conversational spec resolution (findings → prose answers → patches).

The engine tests drive the real orchestration against an exact MockProvider
queue: the mock returns the agendas and answer plans the agent would produce,
and everything after the LLM call is the production path. What is asserted is
the behavior the design fixes: which findings earn a question, that answers
apply incrementally, that exactly one clarifying follow-up is allowed, and that
an unmappable answer is parked rather than lost.
"""

from __future__ import annotations

import pytest

from workflow_compiler.dialogue import DialogueEngine
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    AnswerPlan,
    ApprovalStatus,
    CompilationProject,
    DraftedQuestion,
    DraftedQuestions,
    Patch,
    PatchAction,
    ProjectStage,
    Provenance,
    QuestionStatus,
    Severity,
    SpecFinding,
    SpecItem,
    WorkflowMetadata,
    WorkflowSpec,
)

_DOCUMENT = "The order workflow captures an order and ships it."


def _spec(slug: str = "order-fulfillment") -> WorkflowSpec:
    """A minimal spec with a semver version, so bumps are observable."""
    return WorkflowSpec(
        slug=slug,
        metadata=WorkflowMetadata(
            name="Order Fulfillment",
            purpose="Fulfill a customer order.",
            version="0.1.0",
        ),
    )


def _project(
    *,
    findings: list[SpecFinding] | None = None,
    open_questions: list[SpecItem] | None = None,
) -> CompilationProject:
    spec = _spec()
    if open_questions:
        spec.open_questions = list(open_questions)
    project = CompilationProject(document_text=_DOCUMENT, specs=[spec])
    project.stage = ProjectStage.SPEC_VALIDATED
    project.spec_approval_status = ApprovalStatus.APPROVED
    if findings:
        project.validation_findings = {spec.slug: list(findings)}
    return project


def _finding(message: str, severity: Severity = Severity.BLOCKING) -> SpecFinding:
    return SpecFinding(severity=severity, workflow="order-fulfillment", message=message)


def _agenda(*questions: str, covers: list[str] | None = None) -> DraftedQuestions:
    return DraftedQuestions(
        questions=[
            DraftedQuestion(
                slug="order-fulfillment", question=q, covers=covers or [], section="Outputs"
            )
            for q in questions
        ]
    )


def _engine(provider: MockProvider) -> DialogueEngine:
    return DialogueEngine(provider)


# --------------------------------------------------------------------------- #
# Building the agenda
# --------------------------------------------------------------------------- #


async def test_start_builds_agenda_from_findings_and_open_questions() -> None:
    project = _project(
        findings=[_finding("Payment Confirmed is never consumed.")],
        open_questions=[SpecItem(text="Who approves a refund?")],
    )
    provider = MockProvider(
        structured=[_agenda("What happens after payment?", "Who approves refunds?")]
    )

    session = await _engine(provider).start(project)

    assert len(session.questions) == 2
    assert session.current is not None
    assert session.current.text == "What happens after payment?"
    # Both the finding and the open question reach the drafting prompt.
    prompt = provider.calls[0][1]
    assert "Payment Confirmed is never consumed." in prompt
    assert "Who approves a refund?" in prompt


async def test_info_findings_are_never_asked_about() -> None:
    """INFO records non-problems (e.g. a folded-in edit) — it must not pad the agenda."""
    project = _project(
        findings=[
            _finding("ingest: folded in 2 edits", severity=Severity.INFO),
            _finding("Outputs are unconsumed.", severity=Severity.WARNING),
        ]
    )
    provider = MockProvider(structured=[_agenda("Where do the outputs go?")])

    await _engine(provider).start(project)

    prompt = provider.calls[0][1]
    assert "Outputs are unconsumed." in prompt
    assert "folded in 2 edits" not in prompt


async def test_start_refuses_when_there_is_nothing_to_resolve() -> None:
    project = _project()
    provider = MockProvider(structured=[])

    with pytest.raises(CompilationError, match="Nothing to resolve"):
        await _engine(provider).start(project)


async def test_blocking_questions_sort_ahead_of_warnings() -> None:
    blocking = _finding("Blocking problem.", severity=Severity.BLOCKING)
    warning = _finding("Warning problem.", severity=Severity.WARNING)
    project = _project(findings=[warning, blocking])
    provider = MockProvider(
        structured=[
            DraftedQuestions(
                questions=[
                    DraftedQuestion(
                        slug="order-fulfillment",
                        question="warn-q",
                        covers=[warning.as_string()],
                    ),
                    DraftedQuestion(
                        slug="order-fulfillment",
                        question="block-q",
                        covers=[blocking.as_string()],
                    ),
                ]
            )
        ]
    )

    session = await _engine(provider).start(project)

    assert [q.text for q in session.questions] == ["block-q", "warn-q"]
    assert session.questions[0].severity is Severity.BLOCKING


# --------------------------------------------------------------------------- #
# Answering
# --------------------------------------------------------------------------- #


async def test_answer_applies_patches_and_bumps_the_patch_version() -> None:
    project = _project(findings=[_finding("No shipping step.")])
    provider = MockProvider(
        structured=[
            _agenda("What happens after payment?"),
            AnswerPlan(
                patches=[
                    Patch(
                        action=PatchAction.ADD,
                        target="activity",
                        payload={"name": "Pack and ship order"},
                    )
                ]
            ),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "we pack it and ship it out")

    assert outcome.applied
    assert outcome.question.status is QuestionStatus.ANSWERED
    spec = project.spec_for("order-fulfillment")
    assert spec is not None
    assert any(f.statement == "Pack and ship order" for f in spec.facts.facts)
    # Incremental application: this answer alone moved 0.1.0 → 0.1.1.
    assert spec.metadata.version == "0.1.1"
    assert "version bumped to 0.1.1" in outcome.changes


async def test_applied_answer_marks_the_element_human_provided() -> None:
    """Answers carry human authority — additions need no document grounding."""
    project = _project(findings=[_finding("Billing is not an actor.")])
    provider = MockProvider(
        structured=[
            _agenda("Is Billing a team?"),
            AnswerPlan(
                patches=[
                    Patch(
                        action=PatchAction.ADD, target="actors", payload={"value": "Billing"}
                    )
                ]
            ),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)

    await engine.answer(project, session, "Billing is a team, they do the invoices")

    spec = project.spec_for("order-fulfillment")
    assert spec is not None
    assert "Billing" in spec.metadata.actors
    assert spec.provenance_of("actors:Billing") is Provenance.HUMAN_PROVIDED


async def test_applying_an_answer_returns_the_project_to_the_spec_gate() -> None:
    project = _project(findings=[_finding("No shipping step.")])
    provider = MockProvider(
        structured=[
            _agenda("What next?"),
            AnswerPlan(
                patches=[
                    Patch(action=PatchAction.ADD, target="activity", payload={"name": "Ship"})
                ]
            ),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)

    await engine.answer(project, session, "we ship it")

    assert project.stage is ProjectStage.SPEC_DRAFTED
    assert project.spec_approval_status is ApprovalStatus.PENDING


async def test_vague_answer_asks_exactly_one_clarifying_followup() -> None:
    project = _project(findings=[_finding("Declined path is undefined.")])
    provider = MockProvider(
        structured=[
            _agenda("What happens when payment is declined?"),
            AnswerPlan(needs_followup=True, followup_question="Which customers get retried?"),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "depends on the customer")

    assert outcome.followup == "Which customers get retried?"
    assert not outcome.applied
    # The cursor must NOT advance — the same question is still being asked.
    assert session.cursor == 0
    assert session.current is not None
    assert session.current.status is QuestionStatus.PENDING
    assert session.current.awaiting_followup
    assert session.current.prompt == "Which customers get retried?"


async def test_still_vague_after_followup_is_parked_not_re_asked() -> None:
    project = _project(findings=[_finding("Declined path is undefined.")])
    provider = MockProvider(
        structured=[
            _agenda("What happens when payment is declined?"),
            AnswerPlan(needs_followup=True, followup_question="Which customers?"),
            # The agent asks again; the engine must refuse a second follow-up.
            AnswerPlan(needs_followup=True, followup_question="Still which customers?"),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)
    await engine.answer(project, session, "depends")

    outcome = await engine.answer(project, session, "honestly no idea, ops owns it")

    assert outcome.followup is None
    assert outcome.parked_as is not None
    assert outcome.question.status is QuestionStatus.PARKED
    assert session.complete


async def test_unmappable_answer_is_parked_as_a_human_open_question() -> None:
    project = _project(findings=[_finding("Declined path is undefined.")])
    provider = MockProvider(
        structured=[
            _agenda("What happens when payment is declined?"),
            AnswerPlan(park_note="The declined path is owned by ops and undecided."),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "ops owns that, not decided yet")

    spec = project.spec_for("order-fulfillment")
    assert spec is not None
    parked = [q for q in spec.open_questions if "owned by ops" in q.text]
    assert len(parked) == 1
    assert parked[0].provenance is Provenance.HUMAN_PROVIDED
    assert parked[0].resolved is False
    assert outcome.parked_as == "The declined path is owned by ops and undecided."
    # Nothing was lost, and the spec was not silently patched.
    assert spec.metadata.version == "0.1.0"


async def test_park_falls_back_to_the_verbatim_answer_without_a_note() -> None:
    project = _project(findings=[_finding("Declined path is undefined.")])
    provider = MockProvider(
        structured=[_agenda("What happens when payment is declined?"), AnswerPlan()]
    )
    engine = _engine(provider)
    session = await engine.start(project)

    await engine.answer(project, session, "ask the ops team")

    spec = project.spec_for("order-fulfillment")
    assert spec is not None
    assert any(q.text == "ask the ops team" for q in spec.open_questions)


async def test_empty_answer_is_rejected() -> None:
    project = _project(findings=[_finding("Something.")])
    provider = MockProvider(structured=[_agenda("A question?")])
    engine = _engine(provider)
    session = await engine.start(project)

    with pytest.raises(CompilationError, match="cannot be empty"):
        await engine.answer(project, session, "   ")


async def test_skip_advances_without_touching_the_spec() -> None:
    project = _project(findings=[_finding("Something.")])
    provider = MockProvider(structured=[_agenda("A question?")])
    engine = _engine(provider)
    session = await engine.start(project)

    engine.skip(session)

    spec = project.spec_for("order-fulfillment")
    assert spec is not None
    assert spec.metadata.version == "0.1.0"
    assert spec.open_questions == []
    assert session.questions[0].status is QuestionStatus.SKIPPED
    assert session.complete
    assert project.stage is ProjectStage.SPEC_VALIDATED  # untouched


async def test_answering_past_the_end_of_the_agenda_is_an_error() -> None:
    project = _project(findings=[_finding("Something.")])
    provider = MockProvider(structured=[_agenda("A question?")])
    engine = _engine(provider)
    session = await engine.start(project)
    engine.skip(session)

    with pytest.raises(CompilationError, match="no question awaiting"):
        await engine.answer(project, session, "too late")


async def test_finish_clears_findings_only_for_specs_the_session_changed() -> None:
    project = _project(findings=[_finding("No shipping step.")])
    project.validation_findings["untouched-workflow"] = [_finding("Other problem.")]
    provider = MockProvider(
        structured=[
            _agenda("What next?"),
            AnswerPlan(
                patches=[
                    Patch(action=PatchAction.ADD, target="activity", payload={"name": "Ship"})
                ]
            ),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)
    await engine.answer(project, session, "we ship it")

    engine.finish(project, session)

    assert "order-fulfillment" not in project.validation_findings
    # An untouched workflow's findings are still accurate — keep them.
    assert "untouched-workflow" in project.validation_findings


async def test_agenda_does_not_grow_when_answers_add_open_questions() -> None:
    """Parking appends an open question; the agenda is a snapshot, so it must not grow."""
    project = _project(findings=[_finding("A."), _finding("B.")])
    provider = MockProvider(
        structured=[
            _agenda("q1", "q2"),
            AnswerPlan(park_note="parked one"),
            AnswerPlan(park_note="parked two"),
        ]
    )
    engine = _engine(provider)
    session = await engine.start(project)
    total = len(session.questions)

    await engine.answer(project, session, "dunno")
    await engine.answer(project, session, "also dunno")

    assert len(session.questions) == total == 2
    assert session.complete
