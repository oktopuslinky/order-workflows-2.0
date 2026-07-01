"""IdealProseAgent: grounding-checked prose polish for authored sections.

The deterministic renderer (:mod:`workflow_compiler.authoring.ideal_render`) is
authoritative and terse ("The workflow performs **Validate order**."). This optional
LLM pass rewrites each activity into one natural sentence, but every rewrite must
**ground** in the source document (reference-free token/substring support, reused from
the ensemble merge) or it is discarded in favour of the deterministic wording. It only
ever touches activity descriptions — decision branches, parallelism, and compensation
phrasing stay deterministic — so it can improve readability without changing meaning.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.agents.ensemble_merge import local_grounder
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "polish_activities"
_SYSTEM = (
    "You are a precise technical writer. Describe each activity in one grounded "
    "sentence using only what the document supports, and respond with strict JSON."
)

#: Minimum reference-free support score for a polished sentence to be accepted.
_GROUNDING_THRESHOLD = 0.6


class _ActivityProse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="")
    description: str = Field(default="")


class IdealProseOutput(BaseModel):
    """Structured LLM output: one natural description per activity."""

    model_config = ConfigDict(extra="ignore")

    activities: list[_ActivityProse] = Field(default_factory=list)


class IdealProseAgent:
    """Produce grounded, natural one-sentence descriptions for activities."""

    name = "ideal-prose"

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Store the LLM provider and an optional prompt manager."""
        self._llm = llm
        self._prompts = prompt_manager or PromptManager()

    async def describe_activities(
        self, *, activity_names: list[str], source_text: str
    ) -> dict[str, str]:
        """Return ``{activity_name: sentence}`` for activities that ground.

        Only descriptions whose text is supported by ``source_text`` (substring or
        sufficient token overlap) are kept; ungrounded rewrites are dropped so the
        caller falls back to the deterministic wording. Never raises on a weak model
        response — it simply returns fewer (or no) descriptions.
        """
        if self._llm is None:
            raise CompilationError("IdealProseAgent requires an LLM provider.")
        if not activity_names:
            return {}

        prompt = self._prompts.render(
            _PROMPT_NAME,
            activities="\n".join(f"- {name}" for name in activity_names),
            document_text=source_text,
        )
        result = await self._llm.structured(prompt, IdealProseOutput, system=_SYSTEM)

        grounder = local_grounder(source_text)
        wanted = {name.strip().lower(): name for name in activity_names}
        out: dict[str, str] = {}
        for item in result.activities:
            canonical = wanted.get(item.name.strip().lower())
            sentence = item.description.strip()
            if not canonical or not sentence:
                continue
            if grounder(sentence) >= _GROUNDING_THRESHOLD:
                out[canonical] = sentence
        return out
