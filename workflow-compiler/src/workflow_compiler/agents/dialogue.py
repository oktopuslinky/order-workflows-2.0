"""DialogueAgent: draft questions from findings, read prose answers as patches.

Two LLM-backed halves of the conversational spec gate, both narrowly scoped:

* :meth:`DialogueAgent.draft_questions` turns one workflow's unresolved
  findings and open questions into plain-language questions, grouping related
  ones. It never touches the spec.
* :meth:`DialogueAgent.interpret_answer` reads one prose answer and returns an
  :class:`~workflow_compiler.models.dialogue.AnswerPlan` — patches, a request
  for one clarifying follow-up, or a note to park. It never applies anything.

Both mirror ``EditInterpreterAgent``: the model *specifies*, deterministic code
in :mod:`workflow_compiler.dialogue.engine` *disposes*.
"""

from __future__ import annotations

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models.dialogue import AnswerPlan, DraftedQuestions
from workflow_compiler.prompts import PromptManager

_DRAFT_PROMPT = "draft_dialogue_questions"
_INTERPRET_PROMPT = "interpret_dialogue_answer"

_DRAFT_SYSTEM = (
    "You turn technical specification problems into plain questions a business "
    "user can answer in their own words. You group related problems into a "
    "single question rather than asking mechanically one-by-one, and you never "
    "ask about data structures — only about the business process. Respond with "
    "strict JSON only."
)

_INTERPRET_SYSTEM = (
    "You translate a user's plain-language answer into minimal deterministic "
    "patch operations against a workflow specification. The user carries human "
    "authority: never refuse or second-guess them, and never invent changes "
    "they did not describe. When an answer is too vague to act on, ask one "
    "specific clarifying question; when it cannot become a spec change at all, "
    "restate it for the record instead of discarding it. Respond with strict "
    "JSON only."
)


class DialogueAgent:
    """Draft dialogue questions and interpret the answers to them."""

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Wire the agent to a provider; prompts load from the shared manager."""
        self._llm = llm_provider
        self._prompts = prompt_manager or PromptManager()

    def _require_llm(self) -> BaseLLMProvider:
        if self._llm is None:
            raise CompilationError("DialogueAgent requires an LLM provider.")
        return self._llm

    async def draft_questions(
        self,
        *,
        slug: str,
        findings_block: str,
        questions_block: str,
        current_spec: str,
    ) -> DraftedQuestions:
        """Return the question agenda for one workflow's unresolved items."""
        prompt = self._prompts.render(
            _DRAFT_PROMPT,
            workflow_slug=slug,
            findings_block=findings_block or "(none)",
            questions_block=questions_block or "(none)",
            current_spec=current_spec,
        )
        return await self._require_llm().structured(
            prompt, DraftedQuestions, system=_DRAFT_SYSTEM
        )

    async def interpret_answer(
        self,
        *,
        slug: str,
        question: str,
        answer: str,
        current_spec: str,
        prior_followup: str | None = None,
    ) -> AnswerPlan:
        """Return the plan for one prose answer.

        ``prior_followup`` carries the clarifying question already asked, if
        any; the prompt uses it to forbid a second follow-up, which is what
        bounds the conversation.
        """
        followup_context = (
            "\nA clarifying follow-up was ALREADY asked for this question:\n"
            f"{prior_followup}\n"
            "Do not ask another — map the answer to patches or park it.\n"
            if prior_followup
            else ""
        )
        prompt = self._prompts.render(
            _INTERPRET_PROMPT,
            workflow_slug=slug,
            question=question,
            answer=answer,
            followup_context=followup_context,
            current_spec=current_spec,
        )
        plan = await self._require_llm().structured(
            prompt, AnswerPlan, system=_INTERPRET_SYSTEM
        )
        # A second follow-up would let the conversation loop forever; the engine
        # relies on this being impossible, so enforce it here too rather than
        # trusting the prompt alone.
        if prior_followup and plan.needs_followup:
            return plan.model_copy(
                update={
                    "needs_followup": False,
                    "followup_question": None,
                    "park_note": plan.park_note or answer,
                }
            )
        return plan
