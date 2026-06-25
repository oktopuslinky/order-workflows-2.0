"""WorkflowDiscoveryAgent: extract high-level metadata from a document."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CompilationStage,
    ConfidenceScores,
    WorkflowMetadata,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "discover_workflow"
_SYSTEM = (
    "You are a precise business-process analyst. Extract only what the document "
    "supports and respond with strict JSON."
)

#: Fields that contribute to the completeness component of the confidence score.
_SCORED_FIELDS = (
    "name",
    "purpose",
    "actors",
    "systems",
    "trigger_events",
    "start_states",
    "end_states",
)


class WorkflowDiscovery(BaseModel):
    """Structured LLM output for workflow discovery.

    Uses a permissive config (extra keys ignored) so minor model deviations do
    not fail validation; the agent performs its own cleaning and scoring.
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", description="Workflow name.")
    purpose: str = Field(default="", description="Business intent.")
    actors: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    trigger_events: list[str] = Field(default_factory=list)
    start_states: list[str] = Field(default_factory=list)
    end_states: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, description="Self-reported confidence (0-1).")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _clean_list(items: list[str]) -> list[str]:
    """Strip, drop empties, and de-duplicate (case-insensitively) a string list."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        text = item.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


class WorkflowDiscoveryAgent(BaseAgent):
    """Discover :class:`WorkflowMetadata` from ``WorkflowState.document_text``.

    Depends only on :class:`BaseLLMProvider`, so any provider is usable.
    """

    name = "workflow-discovery"

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Store the LLM provider and an optional prompt manager."""
        super().__init__(llm)
        self._prompts = prompt_manager or PromptManager()

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Extract metadata, score confidence, and update ``state`` in place."""
        if self._llm is None:
            raise CompilationError("WorkflowDiscoveryAgent requires an LLM provider.")
        if not state.document_text or not state.document_text.strip():
            raise CompilationError("Cannot discover a workflow from empty document_text.")

        prompt = self._prompts.render(_PROMPT_NAME, document_text=state.document_text)
        discovery = await self._llm.structured(prompt, WorkflowDiscovery, system=_SYSTEM)

        metadata = self._to_metadata(discovery)
        confidence = self._score(discovery, metadata)

        state.workflow_metadata = metadata
        scores = state.confidence_scores or ConfidenceScores()
        state.confidence_scores = scores.model_copy(update={"metadata": confidence})
        state.stage = CompilationStage.METADATA_EXTRACTED
        state.touch()
        return state

    # -- internals ----------------------------------------------------------

    def _to_metadata(self, discovery: WorkflowDiscovery) -> WorkflowMetadata:
        """Validate and normalize a discovery result into WorkflowMetadata."""
        name = discovery.name.strip()
        if not name:
            raise CompilationError(
                "Workflow discovery failed validation: no workflow name was extracted."
            )
        purpose = discovery.purpose.strip() or None
        return WorkflowMetadata(
            name=name,
            purpose=purpose,
            description=purpose,
            actors=_clean_list(discovery.actors),
            systems=_clean_list(discovery.systems),
            trigger_events=_clean_list(discovery.trigger_events),
            start_states=_clean_list(discovery.start_states),
            end_states=_clean_list(discovery.end_states),
            extra={"self_reported_confidence": f"{_clamp(discovery.confidence):.3f}"},
        )

    def _score(self, discovery: WorkflowDiscovery, metadata: WorkflowMetadata) -> float:
        """Blend self-reported confidence with extraction completeness."""
        populated = 0
        for field in _SCORED_FIELDS:
            value = getattr(metadata, field)
            if isinstance(value, list):
                populated += 1 if value else 0
            else:
                populated += 1 if value else 0
        completeness = populated / len(_SCORED_FIELDS)
        self_reported = _clamp(discovery.confidence)
        return round(_clamp(0.5 * self_reported + 0.5 * completeness), 4)
