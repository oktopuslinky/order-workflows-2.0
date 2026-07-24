"""Unit tests for FactExtractionAgent."""

from __future__ import annotations

import pytest

from workflow_compiler.agents import FactExtractionAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm import MockProvider
from workflow_compiler.models import CompilationStage, FactCategory, WorkflowState

_FULL = {
    "inputs": ["Order request", "Customer details"],
    "outputs": ["Shipment confirmation"],
    "activities": ["Validate payment", "Pick items", "Ship order"],
    "decisions": ["Is payment valid?"],
    "rules": ["Orders over $1000 require manager approval"],
    "events": ["OrderSubmitted", "OrderShipped"],
    "apis": ["POST /payments", "GET /inventory"],
    "systems": ["Payment Gateway", "Warehouse Management System"],
    "exceptions": ["Payment declined"],
    "state_transitions": ["Received -> Validated", "Validated -> Shipped"],
    "timers": ["Cancel if unpaid after 24h"],
    "retries": ["Retry payment up to 3 times"],
    "compensation_candidates": ["Refund payment"],
    "confidence": 0.8,
}


def _state(text: str = "Order workflow document with many details.") -> WorkflowState:
    return WorkflowState(document_text=text)


async def test_fact_extraction_happy_path() -> None:
    agent = FactExtractionAgent(MockProvider(structured=[_FULL]))
    state = await agent.run(_state())

    facts = state.workflow_facts
    assert facts is not None
    # All 13 categories populated.
    assert {f.category for f in facts.facts} == set(FactCategory) - {
        FactCategory.ACTOR,
        FactCategory.ACTION,
        FactCategory.CONDITION,
        FactCategory.DATA,
        FactCategory.TRIGGER,
        FactCategory.CONSTRAINT,
        FactCategory.OUTCOME,
        FactCategory.OTHER,
    }
    apis = facts.by_category(FactCategory.API)
    assert [f.statement for f in apis] == ["POST /payments", "GET /inventory"]
    assert [f.id for f in apis] == ["api-1", "api-2"]

    assert state.stage is CompilationStage.FACTS_EXTRACTED
    assert state.confidence_scores is not None
    assert state.confidence_scores.facts == pytest.approx(0.9)  # 0.5*0.8 + 0.5*1.0
    assert "facts" in state.confidence_scores.notes


async def test_fact_extraction_dedupes_within_category() -> None:
    payload = {"inputs": ["Order", "order", "  ORDER  "], "confidence": 0.5}
    agent = FactExtractionAgent(MockProvider(structured=[payload]))
    state = await agent.run(_state())
    inputs = state.workflow_facts.by_category(FactCategory.INPUT)
    assert len(inputs) == 1
    assert inputs[0].statement == "Order"
    assert "2 duplicate(s) removed" in state.confidence_scores.notes["facts"]


async def test_fact_extraction_normalizes_statements() -> None:
    payload = {"activities": ['  "Validate   payment".  '], "confidence": 0.5}
    agent = FactExtractionAgent(MockProvider(structured=[payload]))
    state = await agent.run(_state())
    activity = state.workflow_facts.by_category(FactCategory.ACTIVITY)[0]
    assert activity.statement == "Validate payment"


async def test_fact_extraction_drops_empty_items() -> None:
    payload = {"systems": ["", "   ", "CRM"], "confidence": 0.5}
    agent = FactExtractionAgent(MockProvider(structured=[payload]))
    state = await agent.run(_state())
    systems = state.workflow_facts.by_category(FactCategory.SYSTEM)
    assert [f.statement for f in systems] == ["CRM"]


async def test_fact_extraction_confidence_lower_when_sparse() -> None:
    payload = {"activities": ["Do one thing"], "confidence": 0.6}
    agent = FactExtractionAgent(MockProvider(structured=[payload]))
    state = await agent.run(_state())
    expected = round(0.5 * 0.6 + 0.5 * (1 / 13), 4)
    assert state.confidence_scores.facts == pytest.approx(expected)


async def test_fact_extraction_requires_llm() -> None:
    with pytest.raises(CompilationError):
        await FactExtractionAgent(llm=None).run(_state())


async def test_fact_extraction_requires_document_text() -> None:
    agent = FactExtractionAgent(MockProvider(structured=[_FULL]))
    with pytest.raises(CompilationError):
        await agent.run(WorkflowState(document_text="   "))


async def test_fact_extraction_preserves_prior_confidence_scores() -> None:
    from workflow_compiler.models import ConfidenceScores

    agent = FactExtractionAgent(MockProvider(structured=[_FULL]))
    state = _state()
    state.confidence_scores = ConfidenceScores(metadata=0.7)
    state = await agent.run(state)
    assert state.confidence_scores.metadata == 0.7
    assert state.confidence_scores.facts is not None
