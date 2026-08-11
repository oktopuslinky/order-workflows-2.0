"""SpecChatAgent: read a free-form instruction as deterministic spec patches.

The LLM-backed half of the free-form spec chat. It mirrors
:class:`~workflow_compiler.agents.dialogue.DialogueAgent` — the model
*specifies*, deterministic code in :mod:`workflow_compiler.dialogue.chat`
*disposes* — with one structural difference: an instruction does not arrive
attached to a question, so the agent is also asked *which* workflow it concerns.

The agent never applies anything and never picks a disposition. It proposes one.
"""

from __future__ import annotations

from collections.abc import Sequence

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models.spec_chat import ChatRole, InstructionPlan, SpecChatTurn
from workflow_compiler.prompts import PromptManager

_INTERPRET_PROMPT = "interpret_spec_instruction"

_INTERPRET_SYSTEM = (
    "You edit a workflow specification on a user's behalf. You translate their "
    "plain-language instructions into minimal deterministic patch operations. "
    "The user carries human authority: never refuse or second-guess them, and "
    "never invent changes they did not ask for. When an instruction is too "
    "vague to act on, ask one specific clarifying question; when it cannot "
    "become a spec change at all, restate it for the record instead of "
    "discarding it. Respond with strict JSON only."
)


class SpecChatAgent:
    """Interpret free-form spec-editing instructions."""

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
            raise CompilationError("SpecChatAgent requires an LLM provider.")
        return self._llm

    async def interpret_instruction(
        self,
        *,
        instruction: str,
        target_slug: str,
        slugs: Sequence[str],
        current_spec: str,
        transcript: Sequence[SpecChatTurn] = (),
        pending_instruction: str | None = None,
        pending_question: str | None = None,
    ) -> InstructionPlan:
        """Return the plan for one instruction.

        ``pending_instruction`` / ``pending_question`` carry the clarification
        already asked, if any. Their presence both reframes the prompt (the new
        message is a *reply*, not a fresh instruction) and forbids a second
        clarification — which is what bounds the exchange.
        """
        prompt = self._prompts.render(
            _INTERPRET_PROMPT,
            instruction=instruction,
            target_slug=target_slug,
            slug_block=self._slug_block(slugs),
            transcript_block=self._transcript_block(transcript),
            clarification_context=self._clarification_context(
                pending_instruction, pending_question
            ),
            current_spec=current_spec,
        )
        plan = await self._require_llm().structured(
            prompt, InstructionPlan, system=_INTERPRET_SYSTEM
        )
        # A second clarification would let the exchange loop forever. The engine
        # relies on this being impossible, so enforce it here too rather than
        # trusting the prompt alone.
        if pending_question and plan.needs_clarification:
            return plan.model_copy(
                update={
                    "needs_clarification": False,
                    "clarifying_question": None,
                    "park_note": plan.park_note or instruction,
                }
            )
        return plan

    @staticmethod
    def _slug_block(slugs: Sequence[str]) -> str:
        """Render the project's workflow slugs as plain lines."""
        return "\n".join(f"- {slug}" for slug in slugs) or "(none)"

    @staticmethod
    def _transcript_block(transcript: Sequence[SpecChatTurn]) -> str:
        """Render recent turns as a readable exchange.

        Only ``role: text`` — the structured disposition of each turn is the
        engine's business, and feeding it back would invite the model to
        second-guess decisions already applied to the spec.
        """
        lines = [
            f"{'User' if turn.role == ChatRole.USER else 'You'}: {turn.text.strip()}"
            for turn in transcript
            if turn.text.strip()
        ]
        return "\n".join(lines) or "(nothing yet)"

    @staticmethod
    def _clarification_context(
        pending_instruction: str | None, pending_question: str | None
    ) -> str:
        """Frame the message as a reply when a clarification is outstanding."""
        if not pending_question:
            return ""
        return (
            "\nThis message is a REPLY. The user originally asked for:\n"
            f"{pending_instruction}\n"
            "You asked them:\n"
            f"{pending_question}\n"
            "Read the two together. Do NOT ask another clarifying question — "
            "either map it to patches now or park it.\n"
        )
