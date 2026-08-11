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
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from workflow_compiler.agents.dialogue import DialogueAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CompilationProject,
    Provenance,
    SpecItem,
    WorkflowSpec,
)
from workflow_compiler.models.dialogue import (
    AnswerPlan,
    DialogueQuestion,
    DialogueSession,
    DraftedQuestion,
    QuestionOrigin,
    QuestionStatus,
)
from workflow_compiler.models.findings import Severity, SpecFinding
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec.edit_applier import EditPatchApplier
from workflow_compiler.spec.renderer import render_spec

#: Severities that earn a question. INFO records non-problems (e.g. a folded-in
#: edit) and would only pad the agenda.
_ASKED_SEVERITIES = frozenset({Severity.BLOCKING, Severity.WARNING})

#: Blocking findings sort ahead of warnings within a workflow's agenda.
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.BLOCKING: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


@dataclass
class AnswerOutcome:
    """What one answer did, for the caller to report back to the user."""

    #: The question that was answered.
    question: DialogueQuestion
    #: Set when a clarifying follow-up is now awaiting an answer.
    followup: str | None = None
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
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Wire the drafting/interpreting agent and the deterministic applier."""
        self._agent = agent or DialogueAgent(llm_provider, prompt_manager=prompt_manager)
        self._applier = EditPatchApplier()

    # ------------------------------------------------------------------ #
    # Building the agenda
    # ------------------------------------------------------------------ #

    async def start(self, project: CompilationProject) -> DialogueSession:
        """Draft the question agenda for every spec with unresolved items.

        Raises :class:`CompilationError` when there is nothing to ask about, so
        the caller can say so rather than opening an empty session.
        """
        session = DialogueSession()
        for spec in project.specs:
            findings = self._askable_findings(project, spec.slug)
            questions = spec.unresolved_questions()
            if not findings and not questions:
                continue
            drafted = await self._agent.draft_questions(
                slug=spec.slug,
                findings_block=self._findings_block(findings),
                questions_block=self._questions_block(questions),
                current_spec=render_spec(spec, project.cross_references, project.triggers),
            )
            session.questions.extend(
                self._to_questions(spec.slug, drafted.questions, findings, questions)
            )
        if not session.questions:
            raise CompilationError(
                "Nothing to resolve: no blocking or warning findings and no open "
                "questions. Run validate first if the specs have changed."
            )
        session.touch()
        return session

    @staticmethod
    def _askable_findings(project: CompilationProject, slug: str) -> list[SpecFinding]:
        """Blocking + warning findings for ``slug``, most severe first."""
        found = [
            f
            for f in project.validation_findings.get(slug, [])
            if f.severity in _ASKED_SEVERITIES
        ]
        return sorted(found, key=lambda f: _SEVERITY_ORDER[f.severity])

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
                )
            )
        built.sort(key=lambda q: _SEVERITY_ORDER[q.severity])
        return built

    # ------------------------------------------------------------------ #
    # Answering
    # ------------------------------------------------------------------ #

    async def answer(
        self, project: CompilationProject, session: DialogueSession, answer: str
    ) -> AnswerOutcome:
        """Apply one prose ``answer`` to the current question.

        Mutates ``project`` and ``session`` in place (the caller persists). The
        spec itself is replaced wholesale with a new validated instance rather
        than edited, so a failed apply cannot leave a half-changed spec.
        """
        question = session.current
        if question is None:
            raise CompilationError("The dialogue session has no question awaiting an answer.")
        text = answer.strip()
        if not text:
            raise CompilationError("An answer cannot be empty.")

        spec = project.spec_for(question.slug)
        if spec is None:
            # The workflow was removed underneath the session; skip rather than fail.
            question.status = QuestionStatus.SKIPPED
            session.advance()
            return AnswerOutcome(
                question=question,
                warnings=[f"workflow '{question.slug}' no longer exists — question skipped"],
            )

        prior_followup = question.followups[-1] if question.followups else None
        plan = await self._agent.interpret_answer(
            slug=question.slug,
            question=question.text,
            answer=text,
            current_spec=render_spec(spec, project.cross_references, project.triggers),
            prior_followup=prior_followup,
        )
        question.answer = text
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
        if plan.has_patches():
            return self._apply(project, session, question, spec, plan)

        if plan.needs_followup and not question.followups:
            followup = (plan.followup_question or "").strip()
            if followup:
                question.followups.append(followup)
                session.touch()
                return AnswerOutcome(question=question, followup=followup)

        return self._park(project, session, question, spec, plan, answer)

    def _apply(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        spec: WorkflowSpec,
        plan: AnswerPlan,
    ) -> AnswerOutcome:
        """Fold the answer's patches into the spec and bump its patch version."""
        effective = [p for p in plan.patches if not p.is_noop()]
        new_spec, summary, warnings = self._applier.apply(
            spec, effective, project.document_text
        )
        bumped = self._bump_patch_version(new_spec.metadata.version)
        if bumped is not None:
            new_spec.metadata = new_spec.metadata.model_copy(update={"version": bumped})
            summary.append(f"version bumped to {bumped}")
        self._replace_spec(project, new_spec)
        self._mark_dirty(project, session, question.slug)

        question.status = QuestionStatus.ANSWERED
        question.changes = summary
        session.advance()
        return AnswerOutcome(
            question=question, changes=summary, warnings=warnings
        )

    def _park(
        self,
        project: CompilationProject,
        session: DialogueSession,
        question: DialogueQuestion,
        spec: WorkflowSpec,
        plan: AnswerPlan,
        answer: str,
    ) -> AnswerOutcome:
        """Record an unmappable answer as a new open question on the spec.

        The user told us something real; it just is not a spec change yet. It is
        stored ``HUMAN_PROVIDED`` and unresolved, so the validator will flag it
        for confirmation but never silently drop it.
        """
        note = (plan.park_note or "").strip() or answer
        parked = SpecItem(
            text=note,
            provenance=Provenance.HUMAN_PROVIDED,
            resolved=False,
            ref=f"dialogue:{question.question_id}",
        )
        new_spec = spec.model_copy(deep=True)
        new_spec.open_questions = [*new_spec.open_questions, parked]
        self._replace_spec(project, new_spec)
        self._mark_dirty(project, session, question.slug)

        question.status = QuestionStatus.PARKED
        question.parked_as = note
        session.advance()
        return AnswerOutcome(question=question, parked_as=note)

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
        from workflow_compiler.models.enums import ApprovalStatus
        from workflow_compiler.models.project import ProjectStage

        if slug not in session.applied_specs:
            session.applied_specs.append(slug)
        project.spec_approval_status = ApprovalStatus.PENDING
        project.stage = ProjectStage.SPEC_DRAFTED
        project.touch()
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
        project.specs = [spec if s.slug == spec.slug else s for s in project.specs]

    @staticmethod
    def _bump_patch_version(version: str) -> str | None:
        """``X.Y.Z`` → ``X.Y.(Z+1)``; ``None`` when ``version`` is not semver."""
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
        if match is None:
            return None
        major, minor, patch = (int(g) for g in match.groups())
        return f"{major}.{minor}.{patch + 1}"
