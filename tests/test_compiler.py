"""Tests for the WorkflowCompiler review workflow.

The compiler runs the agent pipeline up to the approval gate, reviews the
generated graph, persists state, and exposes approve/reject transitions.
"""

from __future__ import annotations

import pytest

from workflow_compiler import WorkflowCompiler
from workflow_compiler.agents import (
    CVPAOutput,
    FactExtraction,
    TemporalDesignOutput,
    WorkflowDiscovery,
)
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.exceptions import ApprovalError, StateNotFoundError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import ApprovalStatus, CompilationStage, WorkflowState
from workflow_compiler.storage import InMemoryStateStore

# These tests drive an exact MockProvider queue; the sequential review pipeline
# (default-on, covered in tests/test_review_pipeline.py) is disabled here so it
# does not consume extra queued responses.
_NO_REVIEW = ReviewConfig(enabled=False)


def _discovery() -> WorkflowDiscovery:
    return WorkflowDiscovery(
        name="Order Fulfillment",
        purpose="Fulfill customer orders.",
        actors=["Customer", "Warehouse"],
        systems=["OMS"],
        trigger_events=["Order submitted"],
        start_states=["Order received"],
        end_states=["Order fulfilled"],
        confidence=0.9,
    )


def _extraction() -> FactExtraction:
    return FactExtraction(
        activities=["Validate payment", "Process order", "Notify warehouse"],
        decisions=["Is payment valid?"],
        exceptions=["Payment declined"],
    )


def _cvpa() -> CVPAOutput:
    return CVPAOutput.model_validate(
        {
            "assignments": [
                {"node_id": "start", "phase": "capture", "confidence": 0.9},
                {"node_id": "end", "phase": "activate", "confidence": 0.9},
            ]
        }
    )


def _temporal() -> TemporalDesignOutput:
    return TemporalDesignOutput.model_validate(
        {"workflow_name": "OrderFulfillment", "activities": [{"name": "process order"}]}
    )


def _provider() -> MockProvider:
    """Seed discovery + facts (compile) and CVPA + Temporal (approve)."""
    return MockProvider(
        structured=[_discovery(), _extraction(), _cvpa(), _temporal()]
    )


@pytest.fixture
def compiler() -> WorkflowCompiler:
    return WorkflowCompiler(
        llm_provider=_provider(),
        state_store=InMemoryStateStore(),
        review=_NO_REVIEW,
    )


def test_compiler_constructs(compiler: WorkflowCompiler) -> None:
    assert isinstance(compiler, WorkflowCompiler)


async def test_compile_document_stops_after_review(
    compiler: WorkflowCompiler, sample_document: str
) -> None:
    state = await compiler.compile_document(sample_document)

    assert state.stage is CompilationStage.REVIEWED
    assert state.approval_status is ApprovalStatus.PENDING
    assert state.workflow_graph is not None
    assert state.review_report is not None
    # Stops before downstream production.
    assert state.cvpa_classification is None
    assert state.temporal_design is None


async def test_compile_document_persists_state(
    compiler: WorkflowCompiler, sample_document: str
) -> None:
    state = await compiler.compile_document(sample_document)
    loaded = await compiler.load_state(state.workflow_id)
    assert loaded.workflow_id == state.workflow_id
    assert loaded.workflow_graph is not None


async def test_compile_document_rejects_empty(compiler: WorkflowCompiler) -> None:
    from workflow_compiler.exceptions import CompilationError

    with pytest.raises(CompilationError):
        await compiler.compile_document("   ")


async def test_approve_graph_transitions_to_approved(
    compiler: WorkflowCompiler, sample_document: str
) -> None:
    state = await compiler.compile_document(sample_document)
    approved = await compiler.approve_graph(state.workflow_id, reviewer="alice")

    assert approved.approval_status is ApprovalStatus.APPROVED
    assert approved.review_report is not None
    assert approved.review_report.reviewer == "alice"
    # Approval runs the downstream pipeline.
    assert approved.cvpa_classification is not None
    assert approved.temporal_design is not None
    assert approved.stage is CompilationStage.COMPLETED

    reloaded = await compiler.load_state(state.workflow_id)
    assert reloaded.approval_status is ApprovalStatus.APPROVED
    assert reloaded.temporal_design is not None


async def test_reject_graph_records_reason(
    compiler: WorkflowCompiler, sample_document: str
) -> None:
    state = await compiler.compile_document(sample_document)
    rejected = await compiler.reject_graph(
        state.workflow_id, reviewer="bob", reason="missing branch"
    )

    assert rejected.approval_status is ApprovalStatus.REJECTED
    assert "missing branch" in (rejected.review_report.summary or "")


async def test_approve_unknown_workflow_raises(compiler: WorkflowCompiler) -> None:
    with pytest.raises(StateNotFoundError):
        await compiler.approve_graph("does-not-exist")


async def test_review_graph_refreshes_report(
    compiler: WorkflowCompiler, sample_document: str
) -> None:
    state = await compiler.compile_document(sample_document)
    report = await compiler.review_graph(state.workflow_id)
    assert report.health_score is not None


async def test_save_and_load_state_round_trip(compiler: WorkflowCompiler) -> None:
    state = WorkflowState(document_text="hello")
    await compiler.save_state(state)
    loaded = await compiler.load_state(state.workflow_id)
    assert loaded.document_text == "hello"


async def test_approve_without_graph_raises() -> None:
    store = InMemoryStateStore()
    compiler = WorkflowCompiler(
        llm_provider=_provider(), state_store=store, review=_NO_REVIEW
    )
    state = WorkflowState(document_text="no graph yet")
    await store.save(state)
    with pytest.raises(ApprovalError):
        await compiler.approve_graph(state.workflow_id)


async def test_compile_emits_timed_progress_events(compiler: WorkflowCompiler) -> None:
    events: list = []
    state = await compiler.compile_document(
        "A workflow document.", review_mode=False, persist=False, progress=events.append
    )

    # Every step emits a start immediately followed by its matching done.
    assert events and len(events) % 2 == 0
    for start, done in zip(events[0::2], events[1::2], strict=False):
        assert start.status == "start"
        assert done.status == "done"
        assert start.name == done.name

    dones = [e for e in events if e.status == "done"]
    # 3 pre-approval agents + review + approve + 3 post-approval agents.
    assert len(dones) == 8
    # done events are timed; agent steps report the resulting stage.
    assert all(e.seconds is not None and e.seconds >= 0 for e in dones)
    assert all(e.stage for e in dones if e.phase == "agent")
    # All three pipeline phases are observable.
    assert {"agent", "review", "approve"} <= {e.phase for e in events}
    assert state.stage is CompilationStage.COMPLETED
