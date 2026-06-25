"""Tests for the domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from workflow_compiler.models import (
    ApprovalStatus,
    CompilationStage,
    CVPAPhase,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowState,
)


def test_workflow_state_defaults(fresh_state: WorkflowState) -> None:
    assert fresh_state.document_text
    assert fresh_state.workflow_id
    assert fresh_state.approval_status is ApprovalStatus.PENDING
    assert fresh_state.stage is CompilationStage.INGESTED
    # All artifact fields start empty.
    assert fresh_state.workflow_metadata is None
    assert fresh_state.workflow_facts is None
    assert fresh_state.workflow_graph is None
    assert fresh_state.review_report is None
    assert fresh_state.cvpa_classification is None
    assert fresh_state.temporal_design is None
    assert fresh_state.mermaid_diagram is None
    assert fresh_state.confidence_scores is None


def test_workflow_state_requires_document_text() -> None:
    with pytest.raises(ValidationError):
        WorkflowState()  # type: ignore[call-arg]


def test_workflow_state_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        WorkflowState(document_text="x", bogus="nope")  # type: ignore[call-arg]


def test_touch_updates_timestamp(fresh_state: WorkflowState) -> None:
    before = fresh_state.updated_at
    fresh_state.touch()
    assert fresh_state.updated_at >= before


def test_graph_unique_node_ids() -> None:
    nodes = [
        WorkflowNode(id="a", label="A"),
        WorkflowNode(id="a", label="A duplicate"),
    ]
    with pytest.raises(ValidationError):
        WorkflowGraph(nodes=nodes)


def test_graph_node_ids_property() -> None:
    graph = WorkflowGraph(
        nodes=[WorkflowNode(id="a", label="A"), WorkflowNode(id="b", label="B")],
        edges=[WorkflowEdge(id="e1", source="a", target="b")],
    )
    assert graph.node_ids == {"a", "b"}


def test_node_default_cvpa_phase_unclassified() -> None:
    node = WorkflowNode(id="n", label="N")
    assert node.cvpa_phase is CVPAPhase.UNCLASSIFIED


def test_state_round_trip_serialization(fresh_state: WorkflowState) -> None:
    dumped = fresh_state.model_dump_json()
    restored = WorkflowState.model_validate_json(dumped)
    assert restored.workflow_id == fresh_state.workflow_id
    assert restored.document_text == fresh_state.document_text
