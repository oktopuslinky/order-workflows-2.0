"""Unit tests for WorkflowReviewAgent and GraphReviewer."""

from __future__ import annotations

import pytest

from workflow_compiler.agents import GraphBuilderAgent, WorkflowReviewAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.graph import GraphReviewer
from workflow_compiler.models import (
    CompilationStage,
    EdgeType,
    FactCategory,
    NodeType,
    ReviewSeverity,
    WorkflowEdge,
    WorkflowFact,
    WorkflowFacts,
    WorkflowGraph,
    WorkflowNode,
    WorkflowState,
)


def _graph(nodes: list[WorkflowNode], edges: list[WorkflowEdge]) -> WorkflowGraph:
    return WorkflowGraph(nodes=nodes, edges=edges)


def _n(node_id: str, label: str, node_type: NodeType = NodeType.TASK) -> WorkflowNode:
    return WorkflowNode(id=node_id, label=label, node_type=node_type)


def _e(edge_id: str, src: str, dst: str, et: EdgeType = EdgeType.SEQUENCE) -> WorkflowEdge:
    return WorkflowEdge(id=edge_id, source=src, target=dst, edge_type=et)


def _messages(report) -> str:
    return " | ".join(i.message for i in report.issues)


# ---------------------------------------------------------------------------
# Missing start / end
# ---------------------------------------------------------------------------


def test_missing_start_is_error() -> None:
    graph = _graph(
        [_n("a", "A"), _n("end", "End", NodeType.END)],
        [_e("e1", "a", "end")],
    )
    report = GraphReviewer().review(graph)
    assert any("no start node" in e.message for e in report.errors)


def test_missing_end_is_error() -> None:
    graph = _graph(
        [_n("start", "Start", NodeType.START), _n("a", "A")],
        [_e("e1", "start", "a")],
    )
    report = GraphReviewer().review(graph)
    assert any("no end node" in e.message for e in report.errors)


# ---------------------------------------------------------------------------
# Structural defects
# ---------------------------------------------------------------------------


def test_orphan_node_detected() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a", "A"),
            _n("orphan", "Orphan"),
            _n("end", "End", NodeType.END),
        ],
        [_e("e1", "start", "a"), _e("e2", "a", "end"), _e("e3", "orphan", "end")],
    )
    report = GraphReviewer().review(graph)
    assert any("Orphan" in w.message and "incoming" in w.message for w in report.warnings)


def test_disconnected_isolated_node_detected() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a", "A"),
            _n("island", "Island"),
            _n("end", "End", NodeType.END),
        ],
        [_e("e1", "start", "a"), _e("e2", "a", "end")],
    )
    report = GraphReviewer().review(graph)
    assert any("disconnected" in w.message for w in report.warnings)


def test_unreachable_subgraph_detected() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a", "A"),
            _n("x", "X"),
            _n("y", "Y"),
            _n("end", "End", NodeType.END),
        ],
        [
            _e("e1", "start", "a"),
            _e("e2", "a", "end"),
            _e("e3", "x", "y"),  # detached subgraph x -> y
        ],
    )
    report = GraphReviewer().review(graph)
    assert any("unreachable" in w.message.lower() for w in report.warnings)


def test_dead_end_node_detected() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a", "A"),
            _n("dead", "Dead"),
            _n("end", "End", NodeType.END),
        ],
        [_e("e1", "start", "a"), _e("e2", "a", "end"), _e("e3", "a", "dead")],
    )
    report = GraphReviewer().review(graph)
    assert any("Dead-end" in w.message for w in report.warnings)


def test_duplicate_nodes_detected() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a1", "Validate payment"),
            _n("a2", "validate   payment"),
            _n("end", "End", NodeType.END),
        ],
        [
            _e("e1", "start", "a1"),
            _e("e2", "a1", "a2"),
            _e("e3", "a2", "end"),
        ],
    )
    report = GraphReviewer().review(graph)
    assert any("Duplicate" in w.message for w in report.warnings)


def test_missing_branch_on_decision_detected() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("d", "Valid?", NodeType.DECISION),
            _n("end", "End", NodeType.END),
        ],
        [_e("e1", "start", "d"), _e("e2", "d", "end")],  # only one branch
    )
    report = GraphReviewer().review(graph)
    assert any("branch" in w.message for w in report.warnings)


def test_unexpected_cycle_flagged_but_retry_loop_is_not() -> None:
    # Sequence cycle a -> b -> a is unexpected.
    seq_cycle = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a", "A"),
            _n("b", "B"),
            _n("end", "End", NodeType.END),
        ],
        [
            _e("e1", "start", "a"),
            _e("e2", "a", "b"),
            _e("e3", "b", "a"),
            _e("e4", "b", "end"),
        ],
    )
    seq_warnings = GraphReviewer().review(seq_cycle).warnings
    assert any("cycle" in w.message.lower() for w in seq_warnings)

    # Same loop but the back-edge is a RETRY -> intended, not flagged.
    retry_loop = _graph(
        seq_cycle.nodes,
        [
            _e("e1", "start", "a"),
            _e("e2", "a", "b"),
            _e("e3", "b", "a", EdgeType.RETRY),
            _e("e4", "b", "end"),
        ],
    )
    retry_warnings = GraphReviewer().review(retry_loop).warnings
    assert not any("cycle" in w.message.lower() for w in retry_warnings)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_healthy_graph_scores_high() -> None:
    graph = _graph(
        [
            _n("start", "Start", NodeType.START),
            _n("a", "A"),
            _n("b", "B"),
            _n("end", "End", NodeType.END),
        ],
        [_e("e1", "start", "a"), _e("e2", "a", "b"), _e("e3", "b", "end")],
    )
    report = GraphReviewer().review(graph)
    assert report.errors == []
    assert report.health_score == 1.0
    assert 0.0 < report.confidence <= 1.0


def test_health_score_drops_with_errors() -> None:
    graph = _graph([_n("a", "A")], [])  # no start, no end, isolated node
    report = GraphReviewer().review(graph)
    assert report.health_score < 1.0
    assert report.suggested_fixes  # fixes are suggested


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


def _facts(**by_category: list[str]) -> WorkflowFacts:
    facts: list[WorkflowFact] = []
    for category_name, statements in by_category.items():
        category = FactCategory(category_name)
        for i, statement in enumerate(statements, start=1):
            facts.append(
                WorkflowFact(
                    id=f"{category_name}-{i}",
                    statement=statement,
                    category=category,
                    confidence=1.0,
                )
            )
    return WorkflowFacts(facts=facts)


async def test_agent_updates_state_without_llm() -> None:
    state = WorkflowState(document_text="doc")
    state.workflow_facts = _facts(activity=["A", "B"], decision=["valid?"], exception=["fail"])
    state = await GraphBuilderAgent().run(state)
    state = await WorkflowReviewAgent().run(state)

    assert state.review_report is not None
    assert state.review_report.reviewer == "workflow-review"
    assert state.review_report.health_score is not None
    assert state.review_report.reviewed_at is not None
    assert state.stage is CompilationStage.REVIEWED
    assert "review" in state.confidence_scores.notes


async def test_agent_requires_graph() -> None:
    with pytest.raises(CompilationError):
        await WorkflowReviewAgent().run(WorkflowState(document_text="doc"))


def test_issue_ids_are_sequential() -> None:
    graph = _graph([_n("a", "A")], [])
    report = GraphReviewer().review(graph)
    expected = [f"issue-{n}" for n in range(1, len(report.issues) + 1)]
    assert [i.id for i in report.issues] == expected
    assert all(i.severity in set(ReviewSeverity) for i in report.issues)
