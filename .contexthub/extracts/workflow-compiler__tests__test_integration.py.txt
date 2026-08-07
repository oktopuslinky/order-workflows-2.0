"""End-to-end integration tests for the full compilation pipeline.

These run the complete pipeline — Document → Discovery → Facts → Graph → Review
→ Approval → CVPA → Temporal — against a deterministic :class:`MockProvider`,
with no network access, exercising the real agents, review manager, graph
builder, editor, and state store together.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_compiler import WorkflowCompiler
from workflow_compiler.agents import (
    CVPAOutput,
    FactExtraction,
    TemporalDesignOutput,
    WorkflowDiscovery,
)
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import ApprovalStatus, CompilationStage, CVPAPhase
from workflow_compiler.review import GraphEditor
from workflow_compiler.storage import FileStateStore, InMemoryStateStore

# These end-to-end tests drive an exact MockProvider response queue, so they run
# with the sequential review pipeline disabled (it is covered in
# tests/test_review_pipeline.py). Review-on would consume extra queued responses.
_NO_REVIEW = ReviewConfig(enabled=False)

_DOCUMENT = """
# Order Fulfillment

When a customer submits an order, the system validates the payment details.
If the payment is valid, the warehouse processes the order and ships it.
If the payment is declined, the order is cancelled and the customer is notified.
"""


def _discovery() -> WorkflowDiscovery:
    return WorkflowDiscovery(
        name="Order Fulfillment",
        purpose="Fulfill customer orders end to end.",
        actors=["Customer", "Warehouse"],
        systems=["Payment Gateway", "OMS"],
        trigger_events=["Order submitted"],
        start_states=["Order received"],
        end_states=["Order shipped", "Order cancelled"],
        confidence=0.9,
    )


def _facts() -> FactExtraction:
    return FactExtraction(
        activities=["Validate payment", "Process order", "Ship order", "Notify customer"],
        decisions=["Is payment valid?"],
        exceptions=["Payment declined"],
        events=["Order submitted"],
        confidence=0.85,
    )


def _cvpa() -> CVPAOutput:
    # Intentionally partial — the agent must fill the rest by fallback.
    return CVPAOutput.model_validate(
        {
            "assignments": [
                {"node_id": "start", "phase": "capture", "confidence": 0.95},
                {"node_id": "activity_1", "phase": "validate", "confidence": 0.8},
            ]
        }
    )


def _temporal() -> TemporalDesignOutput:
    return TemporalDesignOutput.model_validate(
        {
            "workflow_name": "Order Fulfillment",
            "task_queue": "orders",
            "activities": [
                {"name": "validate payment", "timeout_seconds": 10},
                {"name": "process order"},
                {"name": "ship order"},
            ],
            "signals": [{"name": "cancel"}],
            "compensation_activities": [{"name": "refund", "compensates": "ProcessOrder"}],
            "default_retry_policy": {"maximum_attempts": 3},
            "confidence": 0.9,
        }
    )


def _provider() -> MockProvider:
    return MockProvider(structured=[_discovery(), _facts(), _cvpa(), _temporal()])


async def test_full_pipeline_with_human_gate() -> None:
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=InMemoryStateStore(), review=_NO_REVIEW
    )

    # Compile stops at the approval gate.
    state = await compiler.compile_document(_DOCUMENT)
    assert state.stage is CompilationStage.REVIEWED
    assert state.approval_status is ApprovalStatus.PENDING
    assert state.workflow_metadata is not None
    assert state.workflow_facts is not None
    assert state.workflow_graph is not None
    assert state.mermaid_diagram is not None
    assert state.cvpa_classification is None  # gated
    assert state.temporal_design is None

    # Approve → downstream artifacts produced.
    final = await compiler.approve_graph(state.workflow_id, reviewer="reviewer-1")
    assert final.stage is CompilationStage.COMPLETED
    assert final.approval_status is ApprovalStatus.APPROVED

    # CVPA covers every node exactly once.
    node_ids = {n.id for n in final.workflow_graph.nodes}
    assigned = [a.node_id for a in final.cvpa_classification.assignments]
    assert set(assigned) == node_ids
    assert len(assigned) == len(node_ids)
    assert all(a.phase in set(CVPAPhase) for a in final.cvpa_classification.assignments)

    # Temporal design is populated.
    assert final.temporal_design is not None
    assert final.temporal_design.workflow_name == "OrderFulfillment"
    assert final.temporal_design.activities
    assert final.temporal_design.compensation_activities

    # Confidence scores recorded for every stage.
    scores = final.confidence_scores
    assert scores is not None
    assert scores.metadata is not None
    assert scores.facts is not None
    assert scores.graph is not None
    assert scores.cvpa is not None
    assert scores.temporal is not None


async def test_full_pipeline_auto_approve() -> None:
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    state = await compiler.compile_document(_DOCUMENT, review_mode=False)
    assert state.stage is CompilationStage.COMPLETED
    assert state.approval_status is ApprovalStatus.APPROVED
    assert state.cvpa_classification is not None
    assert state.temporal_design is not None


async def test_reject_halts_pipeline() -> None:
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    state = await compiler.compile_document(_DOCUMENT)
    rejected = await compiler.reject_graph(state.workflow_id, reason="incomplete")
    assert rejected.approval_status is ApprovalStatus.REJECTED
    assert rejected.cvpa_classification is None
    assert rejected.temporal_design is None


async def test_pipeline_persists_to_disk(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "states")
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=store, review=_NO_REVIEW
    )
    state = await compiler.compile_document(_DOCUMENT)

    # A brand-new compiler instance can load and approve the persisted state.
    # Approval only runs the downstream agents, so it needs just CVPA + Temporal.
    approve_provider = MockProvider(structured=[_cvpa(), _temporal()])
    compiler2 = WorkflowCompiler(
        llm_provider=approve_provider, state_store=FileStateStore(tmp_path / "states")
    )
    final = await compiler2.approve_graph(state.workflow_id)
    assert final.stage is CompilationStage.COMPLETED
    assert (tmp_path / "states" / f"{state.workflow_id}.json").is_file()


async def test_graph_editor_round_trips_through_store() -> None:
    """A reviewer edits the graph, saves, and the edit survives a reload."""
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    state = await compiler.compile_document(_DOCUMENT)

    edited = GraphEditor.add_node(state.workflow_graph, node_id="manual", label="Manual review")
    state.workflow_graph = edited
    await compiler.save_state(state)

    reloaded = await compiler.load_state(state.workflow_id)
    assert "manual" in reloaded.workflow_graph.node_ids


@pytest.mark.parametrize("review_mode", [True, False])
async def test_compile_is_deterministic_across_modes(review_mode: bool) -> None:
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    state = await compiler.compile_document(_DOCUMENT, review_mode=review_mode)
    assert state.workflow_graph is not None
    assert len(state.workflow_graph.nodes) >= 2
