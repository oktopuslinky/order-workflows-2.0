"""FactExtractionAgent: extract detailed, categorized workflow facts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CompilationStage,
    ConfidenceScores,
    FactCategory,
    WorkflowFact,
    WorkflowFacts,
    WorkflowState,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "extract_facts"
_SYSTEM = (
    "You are a meticulous workflow analyst. Extract only facts supported by the "
    "document and respond with strict JSON."
)

#: Maps each structured-output field to its target fact category, in stable order.
_CATEGORY_FIELDS: tuple[tuple[str, FactCategory], ...] = (
    ("inputs", FactCategory.INPUT),
    ("outputs", FactCategory.OUTPUT),
    ("activities", FactCategory.ACTIVITY),
    ("decisions", FactCategory.DECISION),
    ("rules", FactCategory.RULE),
    ("events", FactCategory.EVENT),
    ("apis", FactCategory.API),
    ("systems", FactCategory.SYSTEM),
    ("exceptions", FactCategory.EXCEPTION),
    ("state_transitions", FactCategory.STATE_TRANSITION),
    ("timers", FactCategory.TIMER),
    ("retries", FactCategory.RETRY),
    ("compensation_candidates", FactCategory.COMPENSATION),
)


class FactExtraction(BaseModel):
    """Structured LLM output for detailed fact extraction."""

    model_config = ConfigDict(extra="ignore")

    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    state_transitions: list[str] = Field(default_factory=list)
    timers: list[str] = Field(default_factory=list)
    retries: list[str] = Field(default_factory=list)
    compensation_candidates: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, description="Self-reported confidence (0-1).")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize(statement: str) -> str:
    """Collapse whitespace and strip surrounding quotes / trailing punctuation.

    Stripping is applied repeatedly until stable so mixed wrappers such as
    ``"text".`` are fully reduced to ``text``.
    """
    text = " ".join(statement.split())
    previous = ""
    while text != previous:
        previous = text
        text = text.strip().strip("\"'").rstrip(".").strip()
    return text


class FactExtractionAgent(BaseAgent):
    """Extract :class:`WorkflowFacts` from ``WorkflowState.document_text``.

    Performs normalization, duplicate detection, and confidence scoring.
    Depends only on :class:`BaseLLMProvider`.
    """

    name = "fact-extraction"

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
        """Extract facts, normalize/dedupe, score, and update ``state``."""
        if self._llm is None:
            raise CompilationError("FactExtractionAgent requires an LLM provider.")
        if not state.document_text or not state.document_text.strip():
            raise CompilationError("Cannot extract facts from empty document_text.")

        prompt = self._prompts.render(_PROMPT_NAME, document_text=state.document_text)
        extraction = await self._llm.structured(prompt, FactExtraction, system=_SYSTEM)

        facts, duplicates_removed, populated_categories = self._build_facts(extraction)
        confidence = self._score(extraction, populated_categories)

        state.workflow_facts = WorkflowFacts(facts=facts)
        scores = state.confidence_scores or ConfidenceScores()
        notes = {
            **scores.notes,
            "facts": (
                f"{len(facts)} facts across {populated_categories} categories; "
                f"{duplicates_removed} duplicate(s) removed."
            ),
        }
        state.confidence_scores = scores.model_copy(
            update={"facts": confidence, "notes": notes}
        )
        state.stage = CompilationStage.FACTS_EXTRACTED
        state.touch()
        return state

    # -- internals ----------------------------------------------------------

    def _build_facts(self, extraction: FactExtraction) -> tuple[list[WorkflowFact], int, int]:
        """Flatten categories into normalized, de-duplicated facts.

        Returns ``(facts, duplicates_removed, populated_categories)``.
        """
        per_fact_confidence = round(_clamp(extraction.confidence), 4)
        facts: list[WorkflowFact] = []
        duplicates_removed = 0
        populated_categories = 0

        for field_name, category in _CATEGORY_FIELDS:
            raw_items: list[str] = getattr(extraction, field_name)
            seen: set[str] = set()
            index = 0
            category_had_item = False
            for raw in raw_items:
                statement = _normalize(raw)
                if not statement:
                    continue
                key = statement.lower()
                if key in seen:
                    duplicates_removed += 1
                    continue
                seen.add(key)
                index += 1
                category_had_item = True
                facts.append(
                    WorkflowFact(
                        id=f"{category.value}-{index}",
                        statement=statement,
                        category=category,
                        confidence=per_fact_confidence,
                    )
                )
            if category_had_item:
                populated_categories += 1

        return facts, duplicates_removed, populated_categories

    def _score(self, extraction: FactExtraction, populated_categories: int) -> float:
        """Blend self-reported confidence with category coverage."""
        coverage = populated_categories / len(_CATEGORY_FIELDS)
        self_reported = _clamp(extraction.confidence)
        return round(_clamp(0.5 * self_reported + 0.5 * coverage), 4)
