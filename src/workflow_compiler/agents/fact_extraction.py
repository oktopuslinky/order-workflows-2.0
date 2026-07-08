"""FactExtractionAgent: extract detailed, categorized workflow facts.

The agent extracts two complementary layers in one structured call:

* **flat facts** (inputs, outputs, apis, systems, rules, timers, retries) — the
  scalar vocabulary, stored as :class:`WorkflowFacts`;
* **relational structure** (activities, decisions, exceptions, compensations,
  events, transitions) — id-referenced entities and the links between them,
  stored as a :class:`WorkflowStructure`.

When the relational layer is populated it is validated for referential integrity
(dangling id references are dropped) and the flat facts are derived from it.
Legacy callers that supply only the flat ``list[str]`` fields still work
unchanged — ``structure`` stays ``None`` and the positional graph path is used.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    CompilationStage,
    ConfidenceScores,
    DecisionNode,
    EventKind,
    EventNode,
    ExceptionNode,
    FactCategory,
    TransitionEdge,
    WorkflowFact,
    WorkflowFacts,
    WorkflowState,
    WorkflowStructure,
)
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "extract_facts"
_SYSTEM = (
    "You are a meticulous workflow analyst. Extract only facts supported by the "
    "document and respond with strict JSON. When you link entities (a decision to "
    "its activity, an exception to its raising activity, a compensation to what it "
    "reverses, an event to its emitter), reference the exact id you assigned — "
    "never invent an id you did not declare."
)

#: Maps each flat-output field to its target fact category, in stable order.
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


# --- Permissive relational LLM output schemas -------------------------------


class _ActivityNodeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    name: str = Field(default="")
    parallel_group: str | None = Field(default=None)


class _DecisionNodeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    question: str = Field(default="")
    after: str | None = Field(default=None)
    yes_target: str | None = Field(default=None)
    no_target: str | None = Field(default=None)


class _ExceptionNodeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    reason: str = Field(default="")
    raised_by: str | None = Field(default=None)


class _CompensationNodeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    name: str = Field(default="")
    compensates: str | None = Field(default=None)


class _EventNodeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    name: str = Field(default="")
    emitted_by: str | None = Field(default=None)
    kind: str = Field(default="output_emit")


class _TransitionEdgeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = Field(default="")
    target: str = Field(default="")
    trigger: str | None = Field(default=None)


class FactExtraction(BaseModel):
    """Structured LLM output: flat scalar facts plus relational structure."""

    model_config = ConfigDict(extra="ignore")

    # Flat scalar facts (no inter-entity relations needed).
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    timers: list[str] = Field(default_factory=list)
    retries: list[str] = Field(default_factory=list)

    # Legacy flat fields (still accepted; superseded by the *_nodes below).
    activities: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    state_transitions: list[str] = Field(default_factory=list)
    compensation_candidates: list[str] = Field(default_factory=list)

    # Relational structure (id-referenced).
    activity_nodes: list[_ActivityNodeOut] = Field(default_factory=list)
    decision_nodes: list[_DecisionNodeOut] = Field(default_factory=list)
    exception_nodes: list[_ExceptionNodeOut] = Field(default_factory=list)
    compensation_nodes: list[_CompensationNodeOut] = Field(default_factory=list)
    event_nodes: list[_EventNodeOut] = Field(default_factory=list)
    transition_edges: list[_TransitionEdgeOut] = Field(default_factory=list)

    confidence: float = Field(default=0.5, description="Self-reported confidence (0-1).")

    def has_structure(self) -> bool:
        """True when the relational layer was populated by the model."""
        return bool(
            self.activity_nodes
            or self.decision_nodes
            or self.exception_nodes
            or self.compensation_nodes
            or self.event_nodes
            or self.transition_edges
        )


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize(statement: str) -> str:
    """Collapse whitespace and strip surrounding quotes / trailing punctuation."""
    text = " ".join(statement.split())
    previous = ""
    while text != previous:
        previous = text
        text = text.strip().strip("\"'").rstrip(".").strip()
    return text


def _event_kind(value: object) -> EventKind:
    """Parse an event ``kind`` from the LLM output, defaulting to OUTPUT_EMIT."""
    try:
        return EventKind(str(value).strip().lower())
    except (ValueError, AttributeError):
        return EventKind.OUTPUT_EMIT


class FactExtractionAgent(BaseAgent):
    """Extract :class:`WorkflowFacts` (+ optional structure) from the document."""

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
        """Extract facts (+ structure), normalize/validate, score, update state."""
        if self._llm is None:
            raise CompilationError("FactExtractionAgent requires an LLM provider.")
        if not state.document_text or not state.document_text.strip():
            raise CompilationError("Cannot extract facts from empty document_text.")

        prompt = self._prompts.render(_PROMPT_NAME, document_text=state.document_text)
        extraction = await self._llm.structured(prompt, FactExtraction, system=_SYSTEM)

        structure: WorkflowStructure | None = None
        dropped_refs = 0
        if extraction.has_structure():
            structure = self._build_structure(extraction)
            structure, warnings = structure.validated()
            dropped_refs = len(warnings)
            facts, duplicates_removed, populated_categories = self._facts_from_structure(
                extraction, structure
            )
        else:
            facts, duplicates_removed, populated_categories = self._build_facts(extraction)

        confidence = self._score(extraction, populated_categories)

        state.workflow_facts = WorkflowFacts(facts=facts, structure=structure)
        scores = state.confidence_scores or ConfidenceScores()
        link_note = f"; {dropped_refs} dangling reference(s) dropped" if structure else ""
        notes = {
            **scores.notes,
            "facts": (
                f"{len(facts)} facts across {populated_categories} categories; "
                f"{duplicates_removed} duplicate(s) removed{link_note}."
            ),
        }
        state.confidence_scores = scores.model_copy(
            update={"facts": confidence, "notes": notes}
        )
        state.stage = CompilationStage.FACTS_EXTRACTED
        state.touch()
        return state

    # -- flat fact assembly -------------------------------------------------

    def _flatten(
        self,
        items_by_category: list[tuple[FactCategory, list[str]]],
        confidence: float,
    ) -> tuple[list[WorkflowFact], int, int]:
        """Normalize, dedupe, and id a category→items mapping into flat facts."""
        facts: list[WorkflowFact] = []
        duplicates_removed = 0
        populated_categories = 0
        for category, raw_items in items_by_category:
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
                        confidence=confidence,
                    )
                )
            if category_had_item:
                populated_categories += 1
        return facts, duplicates_removed, populated_categories

    def _build_facts(self, extraction: FactExtraction) -> tuple[list[WorkflowFact], int, int]:
        """Legacy path: flatten the flat ``list[str]`` fields."""
        per_fact_confidence = round(_clamp(extraction.confidence), 4)
        items = [
            (category, getattr(extraction, field_name))
            for field_name, category in _CATEGORY_FIELDS
        ]
        return self._flatten(items, per_fact_confidence)

    def _facts_from_structure(
        self, extraction: FactExtraction, structure: WorkflowStructure
    ) -> tuple[list[WorkflowFact], int, int]:
        """Derive flat facts from the relational structure + scalar fields."""
        per_fact_confidence = round(_clamp(extraction.confidence), 4)
        comp_target = {a.id: a.name for a in structure.activities}
        compensations = [
            (f"{c.name} compensates {comp_target[c.compensates]}" if c.compensates in comp_target
             else c.name)
            for c in structure.compensations
        ]
        items: list[tuple[FactCategory, list[str]]] = [
            (FactCategory.INPUT, extraction.inputs),
            (FactCategory.OUTPUT, extraction.outputs),
            (FactCategory.ACTIVITY, [a.name for a in structure.activities]),
            (FactCategory.DECISION, [d.question for d in structure.decisions]),
            (FactCategory.RULE, extraction.rules),
            (FactCategory.EVENT, [v.name for v in structure.events]),
            (FactCategory.API, extraction.apis),
            (FactCategory.SYSTEM, extraction.systems),
            (FactCategory.EXCEPTION, [x.reason for x in structure.exceptions]),
            (
                FactCategory.STATE_TRANSITION,
                [f"{t.source} -> {t.target}" for t in structure.transitions],
            ),
            (FactCategory.TIMER, extraction.timers),
            (FactCategory.RETRY, extraction.retries),
            (FactCategory.COMPENSATION, compensations),
        ]
        return self._flatten(items, per_fact_confidence)

    # -- relational structure assembly --------------------------------------

    def _build_structure(self, extraction: FactExtraction) -> WorkflowStructure:
        """Map the permissive relational output into the canonical structure."""
        activities = [
            ActivityNode(
                id=n.id.strip(),
                name=_normalize(n.name),
                parallel_group=(n.parallel_group or "").strip() or None,
            )
            for n in extraction.activity_nodes
            if n.id.strip() and _normalize(n.name)
        ]
        decisions = [
            DecisionNode(
                id=n.id.strip(),
                question=_normalize(n.question),
                after=(n.after or "").strip() or None,
                yes_target=(n.yes_target or "").strip() or None,
                no_target=(n.no_target or "").strip() or None,
            )
            for n in extraction.decision_nodes
            if n.id.strip() and _normalize(n.question)
        ]
        exceptions = [
            ExceptionNode(
                id=n.id.strip(),
                reason=_normalize(n.reason),
                raised_by=(n.raised_by or "").strip() or None,
            )
            for n in extraction.exception_nodes
            if n.id.strip() and _normalize(n.reason)
        ]
        compensations = [
            CompensationNode(
                id=n.id.strip(),
                name=_normalize(n.name),
                compensates=(n.compensates or "").strip() or None,
            )
            for n in extraction.compensation_nodes
            if n.id.strip() and _normalize(n.name)
        ]
        events = [
            EventNode(
                id=n.id.strip(),
                name=_normalize(n.name),
                emitted_by=(n.emitted_by or "").strip() or None,
                kind=_event_kind(n.kind),
            )
            for n in extraction.event_nodes
            if n.id.strip() and _normalize(n.name)
        ]
        transitions = [
            TransitionEdge(
                source=_normalize(n.source),
                target=_normalize(n.target),
                trigger=(n.trigger or "").strip() or None,
            )
            for n in extraction.transition_edges
            if _normalize(n.source) and _normalize(n.target)
        ]
        return WorkflowStructure(
            activities=activities,
            decisions=decisions,
            exceptions=exceptions,
            compensations=compensations,
            events=events,
            transitions=transitions,
        )

    def _score(self, extraction: FactExtraction, populated_categories: int) -> float:
        """Blend self-reported confidence with category coverage."""
        coverage = populated_categories / len(_CATEGORY_FIELDS)
        self_reported = _clamp(extraction.confidence)
        return round(_clamp(0.5 * self_reported + 0.5 * coverage), 4)
