"""ChangeAnalystAgent: the LLM half of the change-request wizard.

Every method renders one ``prompts/templates/change_*.md`` template with a
*drafting brief* assembled by :class:`~workflow_compiler.change.engine.ChangeWizardEngine`
(BCR text, knowledge-graph excerpts, deterministic impact table, prior
approved artifacts, the requester's answers) and returns a permissive pydantic
plan. It never assigns ids, never renders markdown and never persists anything
— the engine does all of that deterministically ("the LLM specifies; code
emits").
"""

from __future__ import annotations

from collections.abc import Sequence

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models.change import (
    STEP_LABELS,
    AnswerNote,
    ArtifactKind,
    DraftedWizardQuestions,
    EpicDraft,
    ImpactCoverageDraft,
    ImpactDraft,
    Revision,
    StoriesDraft,
    TddDraft,
)
from workflow_compiler.prompts import PromptManager

_SYSTEM_ANALYST = (
    "You are a meticulous business/systems analyst working from an existing "
    "system's documentation and code. You never invent components, documents, "
    "identifiers or file paths that the material does not contain; when "
    "something is missing you say so. Respond with strict JSON only."
)

_SYSTEM_INTERPRET = (
    "You turn a requester's plain-language answer into one precise brief line "
    "for a document drafter. The requester carries authority: never second-guess "
    "them and never add decisions they did not make. Respond with strict JSON only."
)

_SYSTEM_REVISE = (
    "You edit a markdown document exactly as instructed while preserving its "
    "heading structure, tables and metadata. Respond with strict JSON only."
)

STEP_GOALS: dict[ArtifactKind, str] = {
    ArtifactKind.IMPACT: (
        "an Impact Analysis: per-requirement impact, the affected components / "
        "documents / tests table, design impacts, risks and open decisions."
    ),
    ArtifactKind.EPIC: (
        "a new EPIC in the house style (statement, business value, capabilities, "
        "definition of done, story map, NFRs, dependencies, risks)."
    ),
    ArtifactKind.STORIES: (
        "one user story per story-map row (As/I want/so that, Given-style "
        "acceptance criteria, notes citing requirements, TDD sections, test cases)."
    ),
    ArtifactKind.TDD: (
        "a technical design document with, per section of the existing TDD, the "
        "existing design and the proposed change (states, data contracts, "
        "activities, saga, idempotency, signals/queries, timeouts, testing)."
    ),
}


class ChangeAnalystAgent:
    """Draft questions, interpret answers, draft and revise change artifacts."""

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._llm = llm_provider
        self._prompts = prompt_manager or PromptManager()

    def _require_llm(self) -> BaseLLMProvider:
        if self._llm is None:
            raise CompilationError("ChangeAnalystAgent requires an LLM provider.")
        return self._llm

    # ------------------------------------------------------------ questions
    async def draft_questions(self, step: ArtifactKind, brief: str) -> DraftedWizardQuestions:
        prompt = self._prompts.render(
            "change_questions",
            step_label=STEP_LABELS[step],
            step_goal=STEP_GOALS[step],
            brief=brief,
        )
        return await self._require_llm().structured(
            prompt, DraftedWizardQuestions, system=_SYSTEM_ANALYST
        )

    async def interpret_answer(
        self,
        step: ArtifactKind,
        *,
        question: str,
        answer: str,
        brief_context: str,
        prior_followup: str | None = None,
    ) -> AnswerNote:
        followup_context = (
            "\nA clarifying follow-up was ALREADY asked for this question:\n"
            f"{prior_followup}\n"
            "Do not ask another — resolve with the best brief line you can.\n"
            if prior_followup
            else ""
        )
        prompt = self._prompts.render(
            "change_answer",
            step_label=STEP_LABELS[step],
            question=question,
            answer=answer,
            followup_context=followup_context,
            brief_context=brief_context,
        )
        note = await self._require_llm().structured(prompt, AnswerNote, system=_SYSTEM_INTERPRET)
        # One follow-up at most — enforce here as well as in the prompt so the
        # engine can rely on it.
        if prior_followup and not note.resolved:
            note = note.model_copy(
                update={
                    "resolved": True,
                    "followup_question": None,
                    "followup_options": [],
                    "note": note.note or answer,
                }
            )
        if not note.resolved and not note.followup_question:
            note = note.model_copy(update={"resolved": True, "note": note.note or answer})
        return note

    # --------------------------------------------------------------- drafts
    async def draft_impact(self, brief: str) -> ImpactDraft:
        prompt = self._prompts.render("change_impact", brief=brief)
        return await self._require_llm().structured(prompt, ImpactDraft, system=_SYSTEM_ANALYST)

    async def draft_impact_coverage(
        self, brief: str, *, affected_block: str, candidates_block: str
    ) -> ImpactCoverageDraft:
        """Classify traversal candidates the first impact pass left out."""
        prompt = self._prompts.render(
            "change_impact_coverage",
            brief=brief,
            affected_block=affected_block,
            candidates_block=candidates_block,
        )
        return await self._require_llm().structured(
            prompt, ImpactCoverageDraft, system=_SYSTEM_ANALYST
        )

    async def draft_epic(self, brief: str, *, epic_id: str, story_id_hint: str) -> EpicDraft:
        prompt = self._prompts.render(
            "change_epic", brief=brief, epic_id=epic_id, story_id_hint=story_id_hint
        )
        return await self._require_llm().structured(prompt, EpicDraft, system=_SYSTEM_ANALYST)

    async def draft_stories(
        self, brief: str, *, epic_ref: str, stories: Sequence[tuple[str, str]]
    ) -> StoriesDraft:
        """Draft the given ``(id, title)`` stories (the engine batches them)."""
        block = "\n".join(f"- {sid}: {title}" for sid, title in stories)
        prompt = self._prompts.render(
            "change_stories", brief=brief, stories_block=block, epic_ref=epic_ref
        )
        return await self._require_llm().structured(prompt, StoriesDraft, system=_SYSTEM_ANALYST)

    async def draft_tdd_sections(
        self,
        brief: str,
        *,
        tdd_id: str,
        prior_tdd_id: str,
        sections: Sequence[tuple[str, str, str]],
    ) -> TddDraft:
        """Draft the given ``(key, number, title)`` sections (the engine chunks them)."""
        block = "\n".join(f"- `{key}` — {number} {title}" for key, number, title in sections)
        prompt = self._prompts.render(
            "change_tdd",
            brief=brief,
            sections_block=block,
            tdd_id=tdd_id,
            prior_tdd_id=prior_tdd_id or "the current TDD",
        )
        return await self._require_llm().structured(prompt, TddDraft, system=_SYSTEM_ANALYST)

    # --------------------------------------------------------------- revise
    async def revise(
        self,
        step: ArtifactKind,
        *,
        markdown: str,
        instruction: str,
        brief_context: str,
    ) -> Revision:
        prompt = self._prompts.render(
            "change_revise",
            step_label=STEP_LABELS[step],
            instruction=instruction,
            artifact_markdown=markdown,
            brief_context=brief_context,
        )
        return await self._require_llm().structured(prompt, Revision, system=_SYSTEM_REVISE)
