"""DialogueEngine: the deterministic half of conversational spec resolution.

The agent proposes (questions, and readings of answers); this engine disposes.
It owns every decision that must be reproducible:

* **which** unresolved items become an agenda (blocking + warning findings, plus
  unresolved open questions — never INFO findings);
* **when** an answer changes the spec (patches present → apply immediately, one
  version bump per answered question);
* **what happens when it does not** (one clarifying follow-up, then park the
  answer as a new open question — never discard, never abort the session).

Patches are applied through :class:`~workflow_compiler.spec.edit_applier.EditPatchApplier`,
so answers inherit the edit path's human-authority semantics: additions need no
document grounding and are marked ``HUMAN_PROVIDED``. Applying is *pure* —
a new spec is returned and swapped in, never mutated in place.

The agenda is a snapshot taken at ``start``. Answers applied mid-session change
the specs underneath it, but the agenda does not grow, so a session always
terminates. Re-validating afterwards produces the next round.

Drafting that agenda is the slow half — one LLM call per spec, serially, before
the user sees anything — so :meth:`DialogueEngine.prepare` runs the same drafting
without opening a session, for the background pre-draft that fires when
validation finishes. ``start`` then consumes the prepared agenda if it still
matches the material it was drafted from (see
:mod:`workflow_compiler.dialogue.agenda`) and drafts live if it does not. The two
paths produce the same questions; only the waiting differs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from workflow_compiler.agents.change_spec import ChangeSpecAgent
from workflow_compiler.agents.dialogue import DialogueAgent
from workflow_compiler.dialogue.agenda import (
    SEVERITY_ORDER as _SEVERITY_ORDER,
)
from workflow_compiler.dialogue.agenda import (
    agenda_fingerprint,
    askable_findings,
)
from workflow_compiler.dialogue.change_ops import (
    apply_component_updates,
    park_change_question,
    replace_change_spec,
)
from workflow_compiler.dialogue.spec_ops import (
    apply_patches,
    bump_patch_version,
    park_as_open_question,
    replace_spec,
    reset_to_spec_gate,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CHANGES_SLUG,
    ChangeAnswerPlan,
    ChangeSpec,
    CompilationProject,
    SpecItem,
    WorkflowSpec,
)
from workflow_compiler.models.dialogue import (
    AnswerPlan,
    DialogueQuestion,
    DialogueSession,
    DraftedQuestion,
    PreparedAgenda,
    QuestionOrigin,
    QuestionStatus,
    SuggestedOption,
)
from workflow_compiler.models.findings import Severity, SpecFinding
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec.change_renderer import render_change_spec
from workflow_compiler.spec.edit_applier import EditPatchApplier
from workflow_compiler.spec.renderer import render_spec
from workflow_compiler.spec.wiring import apply_xref_op


@dataclass
class AnswerOutcome:
    """What one answer did, for the caller to report back to the user."""

    #: The question that was answered.
    question: DialogueQuestion
    #: Set when a clarifying follow-up is now awaiting an answer.
    followup: str | None = None
    #: Candidate answers to that follow-up, when it carries any.
    followup_options: list[SuggestedOption] = field(default_factory=list)
    #: Human-readable lines describing the spec changes applied.
    changes: list[str] = field(default_factory=list)
    #: Set when the answer was recorded as a new open question instead.
    parked_as: str | None = None
    #: Non-fatal issues from the applier (e.g. pruned dangling references).
    warnings: list[str] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        """True when the answer changed the specification."""
        return bool(self.changes)


class DialogueEngine:
    """Run a question-and-answer session over a project's unresolved items."""

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None = None,
        *,
        agent: DialogueAgent | None = None,
        change_agent: ChangeSpecAgent | None = None,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Wire the drafting/interpreting agents and the deterministic applier.

        ``change_agent`` handles the change spec (``changes.md``, slug
        :data:`CHANGES_SLUG`) of a knowledge-graph-grounded project; its
        questions and answers go through the same session as the workflow
        specs', but its updates are component rows rather than patches.
        """
        self._agent = agent or DialogueAgent(llm_provider, prompt_manager=prompt_manager)
        self._change_agent = change_agent or ChangeSpecAgent(
            llm_provider, prompt_manager=prompt_manager
        )
        self._applier = EditPatchApplier()

    # ------------------------------------------------------------------ #
    # Building the agenda
    # ------------------------------------------------------------------ #

    async def start(self, project: CompilationProject) -> DialogueSession:
        """Open a session over every spec with unresolved items.

        Uses the project's pre-drafted agenda when one is present and still
        matches the material it was drafted from; drafts live otherwise. Either
        way the prepared agenda is consumed — it has become a session, and a
        second session must be drafted against whatever the first one left behind.

        Raises :class:`CompilationError` when there is nothing to ask about, so
        the caller can say so rather than opening an empty session.
        """
        prepared = project.prepared_dialogue
        project.prepared_dialogue = None
        if prepared is not None and prepared.fingerprint == agenda_fingerprint(project):
            questions = [q.model_copy(deep=True) for q in prepared.questions]
        else:
            questions = await self._draft_agenda(project)
        if not questions:
            raise CompilationError(
                "Nothing to resolve: no blocking or warning findings and no open "
                "questions. Run validate first if the specs have changed."
            )
        session = DialogueSession(questions=questions)
        session.touch()
        return session

    async def prepare(self, project: CompilationProject) -> PreparedAgenda | None:
        """Draft the agenda ahead of time, without opening a session.

        Returns ``None`` when there is nothing to ask — the caller records
        nothing rather than persisting an empty agenda that would look prepared.

        The fingerprint is taken **before** drafting, over the material actually
        fed to the model. Taking it afterwards would fold in any change that
        happened during the (minutes-long) drafting run and stamp a stale agenda
        as fresh.
        """
        fingerprint = agenda_fingerprint(project)
        questions = await self._draft_agenda(project)
        if not questions:
            return None
        return PreparedAgenda(fingerprint=fingerprint, questions=questions)

    async def _draft_agenda(self, project: CompilationProject) -> list[DialogueQuestion]:
        """One drafting call per spec that has anything unresolved, in order."""
        agenda: list[DialogueQuestion] = []
        for spec in project.specs:
            findings = askable_findings(project, spec.slug)
            questions = spec.unresolved_questions()
            if not findings and not questions:
                continue
            drafted = await self._agent.draft_questions(
                slug=spec.slug,
                findings_block=self._findings_block(findings),
                questions_block=self._questions_block(questions),
                current_spec=render_spec(spec, project.cross_references, project.triggers),
            )
            agenda.extend(
                self._to_questions(spec.slug, drafted.questions, findings, questions)
            )
        change_spec = project.change_spec
        if change_spec is not None:
            findings = askable_findings(project, CHANGES_SLUG)
            questions = change_spec.unresolved_questions()
            if findings or questions:
                drafted = await self._change_agent.draft_questions(
                    findings_block=self._findings_block(findings),
                    questions_block=self._questions_block(questions),
                    current_changes=render_change_spec(change_spec),
                )
                agenda.extend(
                    self._to_questions(CHANGES_SLUG, drafted.questions, findings, questions)
                )
        return agenda

    @staticmethod
    def _findings_block(findings: list[SpecFinding]) -> str:
        """Render findings as the one-line projection the drafting prompt reads."""
        return "\n".join(f.as_string() for f in findings)

    @staticmethod
    def _questions_block(questions: list[SpecItem]) -> str:
        """Render unresolved open questions as plain lines."""
        return "\n".join(f"- {q.text}" for q in questions)

    def _to_questions(
        self,
        slug: str,
        drafted: Sequence[DraftedQuestion],
        findings: list[SpecFinding],
        open_questions: list[SpecItem],
    ) -> list[DialogueQuestion]:
        """Convert drafted questions into session questions, dropping empties.

        Severity is inherited from the most severe finding a question covers, so
        the agenda can be ordered without re-asking the model. A question that
        covers nothing recognisable still stands — the text is what the user
        sees — but it sorts as a warning.
        """
        by_message = {f.as_string(): f for f in findings}
        known_questions = {q.text for q in open_questions}
        built: list[DialogueQuestion] = []
        for item in drafted:
            text = item.question.strip()
            if not text:
                continue
            covers = list(item.covers)
            severity = Severity.WARNING
            for ref in covers:
                finding = by_message.get(ref)
                if finding is not None and (
                    _SEVERITY_ORDER[finding.severity] < _SEVERITY_ORDER[severity]
                ):
                    severity = finding.severity
            origin = (
                QuestionOrigin.OPEN_QUESTION
                if covers and all(c in known_questions for c in covers)
                else QuestionOrigin.FINDING
            )
            built.append(
                DialogueQuestion(
                    slug=slug,
                    text=text,
                    origin=origin,
                    severity=severity,
                    section=item.section,
                    covers=covers,
                    options=[o for o in item.options if o.label.strip()],
                )
            )
        built.sort(key=lambda q: _SEVERITY_ORDER[q.severity])
        return built

    # ------------------------------------------------------------------ #
    # Answering
    # ------------------------------------------------------------------ #

    async def answer(
        self,
        project: CompilationProject,
        session: DialogueSession,
        answer: str,
        *,
        chosen_option: str | None = None,
    ) -> AnswerOutcome:
        """Apply one prose ``answer`` to the current question.

        Mutates ``project`` and ``session`` in place (the caller persists). The
        spec itself is replaced wholesale with a new validated instance rather
        than edited, so a failed apply cannot leave a half-changed spec.

        ``chosen_option`` names a suggested option the user accepted verbatim, if
        they took one. It is **recorded, not trusted**: the answer still goes
        through the same interpretation path as typed prose, and a label that
        does not match an option actually offered is dropped rather than stored.
        The record exists so the audit trail can tell what the user wrote from
        what they merely agreed to — the suggestions come from the model, and the
        applied result is stamped ``HUMAN_PROVIDED`` either way.
        """
        question = session.current
        if question is None:
            raise CompilationError("The dialogue session has no question awaiting an answer.")
        text = answer.strip()
        if not text:
            raise CompilationError("An answer cannot be empty.")

        if question.slug == CHANGES_SLUG:
            return await self._answer_change(
                project, session, question, text, chosen_option=chosen_option
            )

        spec = project.spec_for(question.slug)
        if spec is None:
            # The workflow was removed underneath the session; skip rather than fail.
            question.status = QuestionStatus.SKIPPED
            session.advance()
            return AnswerOutcome(
                question=question,
                warnings=[f"workflow '{question.slug}' no longer exists — question skipped"],
            )

        offered = {o.label for o in question.prompt_options}
        prior_followup = question.followups[-1] if question.followups else None
        plan = await self._agent.interpret_answer(
            slug=question.slug,
            question=question.text,
            answer=text,
            current_spec=render_spec(spec, project.cross_references, project.triggers),
            prior_followup=prior_followup,
        )
        question.answer = text
        question.chosen_option = chosen_option if chosen_option in offered else None
        return self._dispose(project, session, question, spec, plan, text)

    def _dispose(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        spec: WorkflowSpec,
        plan: AnswerPlan,
        answer: str,
    ) -> AnswerOutcome:
        """Resolve one interpreted answer: apply, follow up, or park.

        Precedence is fixed and deliberate — patches beat a follow-up request,
        and a follow-up is only ever asked once (the agent enforces the same
        rule, but the engine does not depend on it doing so).
        """
        if plan.has_effect():
            summary, warnings = self._apply_changes(project, spec, plan)
            if summary:
                self._mark_dirty(project, session, question.slug)
                question.status = QuestionStatus.ANSWERED
                question.changes = summary
                session.advance()
                return AnswerOutcome(
                    question=question, changes=summary, warnings=warnings
                )
            # Everything the plan asked for was dropped — an unknown workflow, a
            # dependency that is not there. Reporting "applied" with no changes
            # would be a lie, so fall through and park, carrying the reasons.
            return self._park(
                project, session, question, spec, plan, answer, warnings=warnings
            )

        if plan.needs_followup and not question.followups:
            followup = (plan.followup_question or "").strip()
            if followup:
                question.followups.append(followup)
                question.followup_options = [
                    o for o in plan.followup_options if o.label.strip()
                ]
                session.touch()
                return AnswerOutcome(
                    question=question,
                    followup=followup,
                    followup_options=question.followup_options,
                )

        return self._park(project, session, question, spec, plan, answer)

    def _apply_changes(
        self,
        project: CompilationProject,
        spec: WorkflowSpec,
        plan: AnswerPlan,
    ) -> tuple[list[str], list[str]]:
        """Carry out an answer's changes; return ``(summary, warnings)``.

        Two kinds of change, and the split is structural rather than incidental:
        patches act on the spec, dependency operations act on the *project*,
        because a cross-workflow reference belongs to no single workflow.

        A dependency operation that cannot be carried out is reported and
        skipped, never raised. A session must survive an operation the project
        will not accept (decision 8) — the alternative loses the user's answer
        to a 500.
        """
        summary: list[str] = []
        warnings: list[str] = []
        current = spec
        if plan.has_patches():
            current, patch_summary, patch_warnings = apply_patches(
                project, spec, plan.patches, self._applier
            )
            summary.extend(patch_summary)
            warnings.extend(patch_warnings)
        wired = 0
        for op in plan.xref_ops:
            try:
                summary.append(apply_xref_op(project, op))
                wired += 1
            except CompilationError as exc:
                warnings.append(f"dependency change skipped — {exc}")
        if wired and not plan.has_patches():
            # Dependencies render into the spec, so its Markdown changed even
            # though no patch touched it. The version has to move with it, or a
            # prepared agenda fingerprinted against it would still look fresh.
            bumped = bump_patch_version(current.metadata.version)
            if bumped is not None:
                current.metadata = current.metadata.model_copy(
                    update={"version": bumped}
                )
                replace_spec(project, current)
                summary.append(f"version bumped to {bumped}")
        return summary, warnings

    def _park(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        spec: WorkflowSpec,
        plan: AnswerPlan,
        answer: str,
        *,
        warnings: list[str] | None = None,
    ) -> AnswerOutcome:
        """Record an unmappable answer as a new open question on the spec.

        The user told us something real; it just is not a spec change yet. It is
        stored ``HUMAN_PROVIDED`` and unresolved, so the validator will flag it
        for confirmation but never silently drop it.
        """
        note = (plan.park_note or "").strip() or answer
        park_as_open_question(
            project, spec, note, ref=f"dialogue:{question.question_id}"
        )
        self._mark_dirty(project, session, question.slug)

        question.status = QuestionStatus.PARKED
        question.parked_as = note
        session.advance()
        return AnswerOutcome(
            question=question, parked_as=note, warnings=warnings or []
        )

    # ------------------------------------------------------------------ #
    # Answering about the change spec (changes.md)
    # ------------------------------------------------------------------ #

    async def _answer_change(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        text: str,
        *,
        chosen_option: str | None,
    ) -> AnswerOutcome:
        """The :data:`CHANGES_SLUG` twin of :meth:`answer`.

        Same three dispositions, same precedence (updates beat a follow-up,
        one follow-up at most, park otherwise); the deterministic half is
        :mod:`workflow_compiler.dialogue.change_ops` instead of the patch applier.
        """
        change_spec = project.change_spec
        if change_spec is None:
            question.status = QuestionStatus.SKIPPED
            session.advance()
            return AnswerOutcome(
                question=question,
                warnings=["the project has no change spec any more — question skipped"],
            )
        offered = {o.label for o in question.prompt_options}
        prior_followup = question.followups[-1] if question.followups else None
        plan = await self._change_agent.interpret_answer(
            question=question.text,
            answer=text,
            current_changes=render_change_spec(change_spec),
            prior_followup=prior_followup,
        )
        question.answer = text
        question.chosen_option = chosen_option if chosen_option in offered else None
        return self._dispose_change(project, session, question, change_spec, plan, text)

    def _dispose_change(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        change_spec: ChangeSpec,
        plan: ChangeAnswerPlan,
        answer: str,
    ) -> AnswerOutcome:
        if plan.updates or plan.resolve_questions:
            new_spec, summary, warnings = apply_component_updates(
                change_spec, plan.updates, resolve_questions=plan.resolve_questions
            )
            if summary:
                replace_change_spec(project, new_spec)
                self._mark_dirty(project, session, CHANGES_SLUG)
                question.status = QuestionStatus.ANSWERED
                question.changes = summary
                session.advance()
                return AnswerOutcome(question=question, changes=summary, warnings=warnings)
            return self._park_change(
                project, session, question, change_spec, plan, answer, warnings=warnings
            )
        if plan.needs_followup and not question.followups:
            followup = (plan.followup_question or "").strip()
            if followup:
                question.followups.append(followup)
                question.followup_options = [
                    o for o in plan.followup_options if o.label.strip()
                ]
                session.touch()
                return AnswerOutcome(
                    question=question,
                    followup=followup,
                    followup_options=question.followup_options,
                )
        return self._park_change(project, session, question, change_spec, plan, answer)

    def _park_change(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        change_spec: ChangeSpec,
        plan: ChangeAnswerPlan,
        answer: str,
        *,
        warnings: list[str] | None = None,
    ) -> AnswerOutcome:
        note = (plan.park_note or "").strip() or answer
        replace_change_spec(
            project,
            park_change_question(change_spec, note, ref=f"dialogue:{question.question_id}"),
        )
        self._mark_dirty(project, session, CHANGES_SLUG)
        question.status = QuestionStatus.PARKED
        question.parked_as = note
        session.advance()
        return AnswerOutcome(question=question, parked_as=note, warnings=warnings or [])

    def skip(self, session: DialogueSession) -> DialogueQuestion:
        """Pass on the current question, leaving the spec untouched."""
        question = session.current
        if question is None:
            raise CompilationError("The dialogue session has no question awaiting an answer.")
        question.status = QuestionStatus.SKIPPED
        session.advance()
        return question

    # ------------------------------------------------------------------ #
    # Project bookkeeping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _mark_dirty(
        project: CompilationProject, session: DialogueSession, slug: str
    ) -> None:
        """Record that a spec changed and return the project to the spec gate.

        ``validation_findings`` is deliberately **left in place** while the
        session runs: it is the agenda's source, and clearing it mid-session
        would erase the context of questions still to be asked. Ending the
        session clears it (see :meth:`finish`), which is what forces a
        re-validate before approval.
        """
        if slug not in session.applied_specs:
            session.applied_specs.append(slug)
        reset_to_spec_gate(project)
        session.touch()

    @staticmethod
    def finish(project: CompilationProject, session: DialogueSession) -> None:
        """Close out a session, dropping findings the answers have invalidated.

        Only the specs the session actually changed lose their findings — an
        untouched workflow's findings are still accurate and worth keeping.
        """
        for slug in session.applied_specs:
            project.validation_findings.pop(slug, None)
        project.touch()
        session.touch()

    @staticmethod
    def _replace_spec(project: CompilationProject, spec: WorkflowSpec) -> None:
        """Swap ``spec`` in by slug, preserving order."""
        replace_spec(project, spec)
