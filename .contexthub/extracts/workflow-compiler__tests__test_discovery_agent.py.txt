"""Unit tests for WorkflowDiscoveryAgent."""

from __future__ import annotations

import pytest

from workflow_compiler.agents import WorkflowDiscoveryAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm import MockProvider
from workflow_compiler.models import CompilationStage, WorkflowState

_FULL_DISCOVERY = {
    "name": "Order Fulfillment",
    "purpose": "Fulfill customer orders from intake to delivery.",
    "actors": ["Customer", "Warehouse Operator"],
    "systems": ["Order Portal", "Payment Gateway"],
    "trigger_events": ["Order submitted"],
    "start_states": ["Order received"],
    "end_states": ["Order delivered", "Order cancelled"],
    "confidence": 0.9,
}


def _state(text: str = "When a customer submits an order, fulfill it.") -> WorkflowState:
    return WorkflowState(document_text=text)


async def test_discovery_happy_path() -> None:
    agent = WorkflowDiscoveryAgent(MockProvider(structured=[_FULL_DISCOVERY]))
    state = await agent.run(_state())

    metadata = state.workflow_metadata
    assert metadata is not None
    assert metadata.name == "Order Fulfillment"
    assert metadata.purpose.startswith("Fulfill customer orders")
    assert metadata.actors == ["Customer", "Warehouse Operator"]
    assert metadata.systems == ["Order Portal", "Payment Gateway"]
    assert metadata.trigger_events == ["Order submitted"]
    assert metadata.start_states == ["Order received"]
    assert metadata.end_states == ["Order delivered", "Order cancelled"]

    assert state.stage is CompilationStage.METADATA_EXTRACTED
    assert state.confidence_scores is not None
    # All fields populated + 0.9 self-confidence -> high score.
    assert state.confidence_scores.metadata == pytest.approx(0.95)


async def test_discovery_cleans_and_dedupes_lists() -> None:
    payload = dict(_FULL_DISCOVERY)
    payload["actors"] = ["Customer", " customer ", "", "Warehouse Operator"]
    agent = WorkflowDiscoveryAgent(MockProvider(structured=[payload]))
    state = await agent.run(_state())
    assert state.workflow_metadata.actors == ["Customer", "Warehouse Operator"]


async def test_discovery_confidence_lower_when_sparse() -> None:
    sparse = {
        "name": "Mystery Process",
        "purpose": "",
        "actors": [],
        "systems": [],
        "trigger_events": [],
        "start_states": [],
        "end_states": [],
        "confidence": 0.4,
    }
    agent = WorkflowDiscoveryAgent(MockProvider(structured=[sparse]))
    state = await agent.run(_state())
    # Only name populated (1/7) and 0.4 self-confidence.
    expected = round(0.5 * 0.4 + 0.5 * (1 / 7), 4)
    assert state.confidence_scores.metadata == pytest.approx(expected)


async def test_discovery_missing_name_raises() -> None:
    payload = dict(_FULL_DISCOVERY)
    payload["name"] = "   "
    agent = WorkflowDiscoveryAgent(MockProvider(structured=[payload]))
    with pytest.raises(CompilationError):
        await agent.run(_state())


async def test_discovery_requires_llm() -> None:
    agent = WorkflowDiscoveryAgent(llm=None)
    with pytest.raises(CompilationError):
        await agent.run(_state())


async def test_discovery_requires_document_text() -> None:
    agent = WorkflowDiscoveryAgent(MockProvider(structured=[_FULL_DISCOVERY]))
    with pytest.raises(CompilationError):
        await agent.run(WorkflowState(document_text="   "))


async def test_discovery_clamps_overconfident_self_report() -> None:
    payload = dict(_FULL_DISCOVERY)
    payload["confidence"] = 5.0  # out of range; should clamp to 1.0
    agent = WorkflowDiscoveryAgent(MockProvider(structured=[payload]))
    state = await agent.run(_state())
    assert state.confidence_scores.metadata == pytest.approx(1.0)
    assert state.workflow_metadata.extra["self_reported_confidence"] == "1.000"
