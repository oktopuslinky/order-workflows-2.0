"""Tests for suggested answers and the pre-drafted question agenda.

Two features that share a seam. Both are about the *drafting* half of the
dialogue rather than the applying half, which ``test_dialogue.py`` already
covers, so what is asserted here is:

* an option is a shortcut and never an authority — it reaches the same
  interpretation path as typed prose, and a label the user was not actually
  offered is not recorded as one they accepted;
* a prepared agenda is used only while it still describes the project, and a
  stale one is silently re-drafted rather than shown.

The fingerprint tests are the load-bearing ones. Pre-drafting is only safe
because a superseded agenda is detectable; if the digest stopped noticing a
change, the failure would be a user answering questions about a specification
that no longer exists.
"""

from __future__ import annotations

import pytest

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.dialogue import DialogueEngine
from workflow_compiler.dialogue.agenda import (
    agenda_fingerprint,
    askable_findings,
    has_anything_to_ask,
    prepared_agenda_is_fresh,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    AnswerPlan,
    ApprovalStatus,
    CompilationProject,
    CrossReference,
    DialogueQuestion,
    DraftedQuestion,
    DraftedQuestions,
    Patch,
    PatchAction,
    PreparedAgenda,
    ProjectStage,
    Severity,
    SpecFinding,
    SpecItem,
    SuggestedOption,
    WorkflowMetadata,
    WorkflowSpec,
)
from workflow_compiler.models.edit import WiringAction, XrefOp
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore

_DOCUMENT = "The order workflow captures an order and ships it."
_SLUG = "order-fulfillment"


def _spec(slug: str = _SLUG, version: str = "0.1.0") -> WorkflowSpec:
    return WorkflowSpec(
        slug=slug,
        metadata=WorkflowMetadata(
            name="Order Fulfillment", purpose="Fulfill a customer order.", version=version
        ),
    )


def _project(
    *,
    findings: list[SpecFinding] | None = None,
    open_questions: list[SpecItem] | None = None,
    specs: list[WorkflowSpec] | None = None,
) -> CompilationProject:
    built = specs or [_spec()]
    if open_questions:
        built[0].open_questions = list(open_questions)
    project = CompilationProject(document_text=_DOCUMENT, specs=built)
    project.stage = ProjectStage.SPEC_VALIDATED
    project.spec_approval_status = ApprovalStatus.APPROVED
    if findings:
        project.validation_findings = {built[0].slug: list(findings)}
    return project


def _finding(message: str, severity: Severity = Severity.BLOCKING) -> SpecFinding:
    return SpecFinding(severity=severity, workflow=_SLUG, message=message)


def _agenda(question: str, *options: str) -> DraftedQuestions:
    return DraftedQuestions(
        questions=[
            DraftedQuestion(
                slug=_SLUG,
                question=question,
                section="Outputs",
                options=[SuggestedOption(label=o) for o in options],
            )
        ]
    )


def _patch_plan() -> AnswerPlan:
    return AnswerPlan(
        patches=[
            Patch(
                action=PatchAction.ADD,
                target="activity",
                payload={"name": "Notify the customer"},
            )
        ]
    )


# --------------------------------------------------------------------------- #
# Suggested options
# --------------------------------------------------------------------------- #


async def test_options_reach_the_session_and_the_prompt() -> None:
    project = _project(findings=[_finding("Payment Confirmed is never consumed.")])
    provider = MockProvider(
        structured=[_agenda("Where does a confirmed payment go?", "To shipping.", "To billing.")]
    )

    session = await DialogueEngine(provider).start(project)

    question = session.current
    assert question is not None
    assert [o.label for o in question.options] == ["To shipping.", "To billing."]
    # prompt_options mirrors prompt: no follow-up open, so these are the question's.
    assert question.prompt_options == question.options


async def test_blank_options_are_dropped() -> None:
    """A model that pads its list with empties must not produce empty buttons."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(structured=[_agenda("Where do outputs go?", "To shipping.", "   ")])

    session = await DialogueEngine(provider).start(project)

    assert session.current is not None
    assert [o.label for o in session.current.options] == ["To shipping."]


async def test_choosing_an_option_is_interpreted_like_typed_prose() -> None:
    """Picking is a shortcut for typing, not a second apply path."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(
        structured=[_agenda("Where do outputs go?", "To shipping."), _patch_plan()]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(
        project, session, "To shipping.", chosen_option="To shipping."
    )

    assert outcome.applied
    assert outcome.question.chosen_option == "To shipping."
    assert outcome.question.answer == "To shipping."
    # The option text went through the interpreter — the second LLM call is the
    # interpretation, exactly as it would be for a typed answer.
    assert "To shipping." in provider.calls[1][1]


async def test_an_option_that_was_never_offered_is_not_recorded() -> None:
    """The audit trail must not claim the user accepted a suggestion they never saw."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(
        structured=[_agenda("Where do outputs go?", "To shipping."), _patch_plan()]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(
        project, session, "Somewhere else entirely.", chosen_option="Somewhere else entirely."
    )

    assert outcome.question.chosen_option is None
    assert outcome.question.answer == "Somewhere else entirely."


async def test_typed_answers_record_no_chosen_option() -> None:
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(
        structured=[_agenda("Where do outputs go?", "To shipping."), _patch_plan()]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "They go to the warehouse team.")

    assert outcome.question.chosen_option is None


async def test_followup_carries_its_own_options() -> None:
    """The vague-answer path is where concrete choices help most."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(
        structured=[
            _agenda("Where do outputs go?"),
            AnswerPlan(
                needs_followup=True,
                followup_question="Which team picks it up?",
                followup_options=[
                    SuggestedOption(label="The warehouse team."),
                    SuggestedOption(label="Support."),
                    SuggestedOption(label=""),
                ],
            ),
        ]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "depends")

    assert outcome.followup == "Which team picks it up?"
    assert [o.label for o in outcome.followup_options] == ["The warehouse team.", "Support."]
    question = session.current
    assert question is not None
    # prompt_options follows prompt onto the follow-up, so the client never has
    # to work out which set it is showing.
    assert question.prompt == "Which team picks it up?"
    assert [o.label for o in question.prompt_options] == ["The warehouse team.", "Support."]


async def test_choosing_a_followup_option_is_recorded() -> None:
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(
        structured=[
            _agenda("Where do outputs go?"),
            AnswerPlan(
                needs_followup=True,
                followup_question="Which team picks it up?",
                followup_options=[SuggestedOption(label="The warehouse team.")],
            ),
            _patch_plan(),
        ]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)
    await engine.answer(project, session, "depends")

    outcome = await engine.answer(
        project, session, "The warehouse team.", chosen_option="The warehouse team."
    )

    assert outcome.applied
    assert outcome.question.chosen_option == "The warehouse team."


# --------------------------------------------------------------------------- #
# The agenda fingerprint
# --------------------------------------------------------------------------- #


def test_fingerprint_is_stable_across_finding_order() -> None:
    """Reordering findings is not new material and must not throw an agenda away."""
    one = _finding("First problem.")
    two = _finding("Second problem.", severity=Severity.WARNING)

    assert agenda_fingerprint(_project(findings=[one, two])) == agenda_fingerprint(
        _project(findings=[two, one])
    )


def test_fingerprint_ignores_info_findings() -> None:
    """INFO never earns a question, so it cannot invalidate an agenda either."""
    warning = _finding("Outputs are unconsumed.", severity=Severity.WARNING)
    with_info = _project(
        findings=[warning, _finding("folded in 2 edits", severity=Severity.INFO)]
    )

    assert agenda_fingerprint(with_info) == agenda_fingerprint(_project(findings=[warning]))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda p: p.validation_findings.__setitem__(_SLUG, [_finding("Something new.")]),
            id="findings-changed",
        ),
        pytest.param(
            lambda p: p.specs[0].open_questions.append(SpecItem(text="Who approves?")),
            id="open-question-added",
        ),
        pytest.param(
            lambda p: p.specs.append(_spec("account-provisioning")),
            id="workflow-added",
        ),
    ],
)
def test_fingerprint_notices_material_changes(mutate: object) -> None:
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    before = agenda_fingerprint(project)

    mutate(project)  # type: ignore[operator]

    assert agenda_fingerprint(project) != before


def test_fingerprint_notices_a_spec_version_bump() -> None:
    """A spec edited to the same findings is still new material."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    before = agenda_fingerprint(project)

    project.specs[0].metadata = project.specs[0].metadata.model_copy(
        update={"version": "0.1.1"}
    )

    assert agenda_fingerprint(project) != before


def test_fingerprint_ignores_changes_that_ask_nothing_new() -> None:
    """Timestamps and approval state move constantly and mean nothing here."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    before = agenda_fingerprint(project)

    project.touch()
    project.spec_approval_status = ApprovalStatus.PENDING
    project.stage = ProjectStage.SPEC_DRAFTED
    project.stage_timings["validate:order-fulfillment"] = 12.5

    assert agenda_fingerprint(project) == before


def test_has_anything_to_ask() -> None:
    assert not has_anything_to_ask(_project())
    assert has_anything_to_ask(_project(findings=[_finding("Outputs are unconsumed.")]))
    assert has_anything_to_ask(_project(open_questions=[SpecItem(text="Who approves?")]))
    # INFO alone is nothing to ask about.
    assert not has_anything_to_ask(
        _project(findings=[_finding("folded in 2 edits", severity=Severity.INFO)])
    )


# --------------------------------------------------------------------------- #
# Pre-drafting
# --------------------------------------------------------------------------- #


async def test_prepare_drafts_without_opening_a_session() -> None:
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(structured=[_agenda("Where do outputs go?", "To shipping.")])

    prepared = await DialogueEngine(provider).prepare(project)

    assert prepared is not None
    assert [q.text for q in prepared.questions] == ["Where do outputs go?"]
    assert [o.label for o in prepared.questions[0].options] == ["To shipping."]
    assert prepared.fingerprint == agenda_fingerprint(project)
    # Preparing must not look like resolving: no session, nothing applied.
    assert project.dialogue_session is None


async def test_prepare_returns_none_when_there_is_nothing_to_ask() -> None:
    """An empty agenda is not persisted — it would look prepared and start empty."""
    provider = MockProvider(structured=[])

    assert await DialogueEngine(provider).prepare(_project()) is None


async def test_start_consumes_a_fresh_prepared_agenda_without_an_llm_call() -> None:
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(structured=[_agenda("Where do outputs go?", "To shipping.")])
    engine = DialogueEngine(provider)
    project.prepared_dialogue = await engine.prepare(project)
    assert prepared_agenda_is_fresh(project)
    drafting_calls = len(provider.calls)

    session = await engine.start(project)

    assert [q.text for q in session.questions] == ["Where do outputs go?"]
    assert [o.label for o in session.questions[0].options] == ["To shipping."]
    assert len(provider.calls) == drafting_calls, "a prepared agenda must not re-draft"
    # Consumed: it is a session now, and a second session must be drafted afresh.
    assert project.prepared_dialogue is None


async def test_start_ignores_a_stale_prepared_agenda_and_redrafts() -> None:
    """The spec moved under the agenda — asking its questions would be wrong."""
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    project.prepared_dialogue = PreparedAgenda(
        fingerprint="stale",
        questions=[DialogueQuestion(slug=_SLUG, text="Old question?")],
    )
    provider = MockProvider(structured=[_agenda("Where do outputs go?")])

    session = await DialogueEngine(provider).start(project)

    assert [q.text for q in session.questions] == ["Where do outputs go?"]
    assert project.prepared_dialogue is None


async def test_prepared_agenda_goes_stale_when_the_findings_change() -> None:
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    provider = MockProvider(structured=[_agenda("Where do outputs go?")])
    project.prepared_dialogue = await DialogueEngine(provider).prepare(project)
    assert prepared_agenda_is_fresh(project)

    project.validation_findings[_SLUG] = [_finding("Something else entirely.")]

    assert not prepared_agenda_is_fresh(project)


async def test_start_still_refuses_when_a_prepared_agenda_is_stale_and_empty() -> None:
    """Falling back to live drafting must not lose the 'nothing to resolve' guard."""
    project = _project()
    project.prepared_dialogue = PreparedAgenda(fingerprint="stale")
    provider = MockProvider(structured=[])

    with pytest.raises(CompilationError, match="Nothing to resolve"):
        await DialogueEngine(provider).start(project)


def test_legacy_projects_load_without_a_prepared_agenda() -> None:
    """Project JSON written before this feature must still deserialize."""
    legacy = _project(findings=[_finding("Outputs are unconsumed.")]).model_dump(mode="json")
    legacy.pop("prepared_dialogue", None)

    restored = CompilationProject.model_validate(legacy)

    assert restored.prepared_dialogue is None
    assert not prepared_agenda_is_fresh(restored)


# --------------------------------------------------------------------------- #
# The compiler's guard: drafting is slow, and the specs can move under it
# --------------------------------------------------------------------------- #


class _MutatingProvider(MockProvider):
    """A provider that changes the stored project while "drafting".

    Stands in for what really happens over the minutes a drafting run takes: the
    free-form chat or a hand edit writes to the same project.
    """

    def __init__(self, responses: list[object], on_call: object) -> None:
        super().__init__(structured=responses)
        self._on_call = on_call
        self._fired = False

    async def structured(self, prompt, schema, *, system=None, temperature=0.0):  # type: ignore[no-untyped-def]
        if not self._fired:
            self._fired = True
            await self._on_call()  # type: ignore[operator]
        return await super().structured(
            prompt, schema, system=system, temperature=temperature
        )


def _compiler(provider: MockProvider, store: InMemoryProjectStore) -> ProjectCompiler:
    return ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=WorkflowCompiler(
            llm_provider=provider,
            state_store=InMemoryStateStore(),
            review=ReviewConfig(enabled=False),
        ),
        project_store=store,
        segmentation_review=False,
    )


async def test_prepare_dialogue_stores_the_agenda_on_the_current_project() -> None:
    store = InMemoryProjectStore()
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    await store.save(project)
    provider = MockProvider(structured=[_agenda("Where do outputs go?", "To shipping.")])

    result = await _compiler(provider, store).prepare_dialogue(project.project_id)

    assert result.prepared_dialogue is not None
    assert [q.text for q in result.prepared_dialogue.questions] == ["Where do outputs go?"]
    # Persisted, not just returned — the next request loads it from the store.
    reloaded = await store.load(project.project_id)
    assert reloaded.prepared_dialogue is not None
    assert prepared_agenda_is_fresh(reloaded)
    assert "dialogue:prepare" in reloaded.stage_timings


async def test_prepare_dialogue_discards_an_agenda_the_project_has_outrun() -> None:
    """A stale agenda that looks prepared is worse than none at all."""
    store = InMemoryProjectStore()
    project = _project(findings=[_finding("Outputs are unconsumed.")])
    await store.save(project)

    async def edit_the_spec_midway() -> None:
        concurrent = await store.load(project.project_id)
        concurrent.specs[0].open_questions.append(SpecItem(text="Who signs this off?"))
        await store.save(concurrent)

    provider = _MutatingProvider(
        [_agenda("Where do outputs go?")], edit_the_spec_midway
    )

    result = await _compiler(provider, store).prepare_dialogue(project.project_id)

    assert result.prepared_dialogue is None
    reloaded = await store.load(project.project_id)
    assert reloaded.prepared_dialogue is None
    # And the concurrent edit survived — saving the in-memory copy would have
    # silently rolled it back.
    assert [q.text for q in reloaded.specs[0].open_questions] == ["Who signs this off?"]


async def test_prepare_dialogue_persists_nothing_when_there_is_nothing_to_ask() -> None:
    store = InMemoryProjectStore()
    project = _project()
    await store.save(project)
    provider = MockProvider(structured=[])

    result = await _compiler(provider, store).prepare_dialogue(project.project_id)

    assert result.prepared_dialogue is None
    assert (await store.load(project.project_id)).prepared_dialogue is None


# --------------------------------------------------------------------------- #
# Cross-workflow dependencies: asked about, and resolvable conversationally
# --------------------------------------------------------------------------- #


def _xref(confirmed: bool = False) -> CrossReference:
    return CrossReference(
        source_workflow=_SLUG,
        output_field="customer_record_id",
        output_type="str",
        target_workflow="account-provisioning",
        input_field="customer_record_id",
        input_type="str",
        description="provisioning consumes the record id",
        user_confirmed=confirmed,
    )


def _linked_project(confirmed: bool = False) -> CompilationProject:
    project = _project(specs=[_spec(), _spec("account-provisioning")])
    project.cross_references = [_xref(confirmed)]
    return project


def _op(action: PatchAction | str, **overrides: object) -> XrefOp:
    ref = _xref().model_copy(update=overrides)  # type: ignore[arg-type]
    return XrefOp(action=WiringAction(action), reference=ref)


def test_an_unconfirmed_dependency_earns_a_finding() -> None:
    """It is a hard stop at approval, so validate must not report green on it."""
    compiler = _compiler(MockProvider(structured=[]), InMemoryProjectStore())

    findings = compiler._validate_triggers_and_dependencies(_linked_project())

    unconfirmed = [f for f in findings if "not been confirmed" in f.message]
    assert len(unconfirmed) == 1
    assert unconfirmed[0].severity is Severity.WARNING  # reaches the dialogue agenda
    assert unconfirmed[0].workflow == _SLUG  # asked once, from the source side
    assert unconfirmed[0].section == "Cross-Workflow Dependencies"


def test_a_confirmed_dependency_earns_no_finding() -> None:
    compiler = _compiler(MockProvider(structured=[]), InMemoryProjectStore())

    findings = compiler._validate_triggers_and_dependencies(_linked_project(confirmed=True))

    assert not [f for f in findings if "not been confirmed" in f.message]


def test_the_unconfirmed_dependency_reaches_the_question_agenda() -> None:
    """The whole point: a hard blocker the user is actually asked about.

    Before this, approve raised on an unconfirmed dependency while validate
    reported green and the agenda — built from findings — never mentioned it.
    """
    compiler = _compiler(MockProvider(structured=[]), InMemoryProjectStore())
    project = _linked_project()
    project.validation_findings = {
        _SLUG: compiler._validate_triggers_and_dependencies(project)
    }

    agenda_sources = askable_findings(project, _SLUG)

    assert any("not been confirmed" in f.as_string() for f in agenda_sources)
    assert has_anything_to_ask(project)


async def test_confirming_a_dependency_clears_the_approval_blocker() -> None:
    project = _linked_project()
    project.validation_findings = {_SLUG: [_finding("dependency not confirmed.")]}
    provider = MockProvider(
        structured=[
            _agenda("Is that hand-off real?"),
            AnswerPlan(xref_ops=[_op("modify")]),
        ]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "yes, that's right")

    assert outcome.applied
    assert project.cross_references[0].user_confirmed is True
    assert any("confirmed dependency" in c for c in outcome.changes)
    # A dependency renders into the spec, so its version must move with it or a
    # prepared agenda fingerprinted against it would still look fresh.
    assert any("version bumped" in c for c in outcome.changes)
    assert project.spec_for(_SLUG).metadata.version == "0.1.1"  # type: ignore[union-attr]


async def test_denying_a_dependency_removes_it() -> None:
    project = _linked_project()
    project.validation_findings = {_SLUG: [_finding("dependency not confirmed.")]}
    provider = MockProvider(
        structured=[
            _agenda("Is that hand-off real?"),
            AnswerPlan(xref_ops=[_op("remove")]),
        ]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "no, it reads that from the CRM")

    assert outcome.applied
    assert project.cross_references == []


async def test_a_dependency_op_that_cannot_be_applied_parks_instead_of_raising() -> None:
    """A session must survive an operation the project will not accept."""
    project = _linked_project()
    project.validation_findings = {_SLUG: [_finding("dependency not confirmed.")]}
    provider = MockProvider(
        structured=[
            _agenda("Is that hand-off real?"),
            # Names a workflow this project does not have.
            AnswerPlan(xref_ops=[_op("remove", target_workflow="does-not-exist")]),
        ]
    )
    engine = DialogueEngine(provider)
    session = await engine.start(project)

    outcome = await engine.answer(project, session, "point it at the other one")

    assert not outcome.applied, "nothing changed, so it must not report an application"
    assert outcome.parked_as, "the user's answer is kept, not discarded"
    assert any("dependency change skipped" in w for w in outcome.warnings)
    # And the project is untouched.
    assert project.cross_references == [_xref()]
