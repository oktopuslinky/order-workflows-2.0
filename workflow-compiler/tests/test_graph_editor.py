"""Tests for GraphEditor: validated, immutable graph edits."""

from __future__ import annotations

import pytest

from workflow_compiler.exceptions import GraphEditError
from workflow_compiler.models import (
    EdgeType,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from workflow_compiler.review import GraphEditor


def _graph() -> WorkflowGraph:
    return WorkflowGraph(
        nodes=[
            WorkflowNode(id="start", label="Start", node_type=NodeType.START),
            WorkflowNode(id="a", label="A"),
            WorkflowNode(id="end", label="End", node_type=NodeType.END),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="a"),
            WorkflowEdge(id="e2", source="a", target="end"),
        ],
    )


def test_add_node() -> None:
    graph = GraphEditor.add_node(_graph(), node_id="b", label="B")
    assert "b" in graph.node_ids


def test_add_node_does_not_mutate_input() -> None:
    original = _graph()
    GraphEditor.add_node(original, node_id="b", label="B")
    assert "b" not in original.node_ids


def test_add_duplicate_node_raises() -> None:
    with pytest.raises(GraphEditError):
        GraphEditor.add_node(_graph(), node_id="a", label="dup")


def test_remove_node_drops_incident_edges() -> None:
    graph = GraphEditor.remove_node(_graph(), "a")
    assert "a" not in graph.node_ids
    assert all("a" not in (e.source, e.target) for e in graph.edges)


def test_remove_unknown_node_raises() -> None:
    with pytest.raises(GraphEditError):
        GraphEditor.remove_node(_graph(), "ghost")


def test_rename_node() -> None:
    graph = GraphEditor.rename_node(_graph(), "a", label="Approved")
    node = next(n for n in graph.nodes if n.id == "a")
    assert node.label == "Approved"


def test_modify_node_type() -> None:
    graph = GraphEditor.modify_node_type(_graph(), "a", node_type=NodeType.DECISION)
    node = next(n for n in graph.nodes if n.id == "a")
    assert node.node_type is NodeType.DECISION


def test_add_edge_auto_id() -> None:
    graph = GraphEditor.add_edge(_graph(), source="start", target="end")
    new_edges = [e for e in graph.edges if e.id not in {"e1", "e2"}]
    assert len(new_edges) == 1
    assert new_edges[0].id == "e3"


def test_add_edge_with_type_and_label() -> None:
    graph = GraphEditor.add_edge(
        _graph(), source="a", target="start", edge_type=EdgeType.RETRY, label="retry"
    )
    edge = next(e for e in graph.edges if e.label == "retry")
    assert edge.edge_type is EdgeType.RETRY


def test_add_edge_unknown_endpoint_raises() -> None:
    with pytest.raises(GraphEditError):
        GraphEditor.add_edge(_graph(), source="start", target="ghost")


def test_add_edge_duplicate_id_raises() -> None:
    with pytest.raises(GraphEditError):
        GraphEditor.add_edge(_graph(), source="start", target="end", edge_id="e1")


def test_remove_edge() -> None:
    graph = GraphEditor.remove_edge(_graph(), "e1")
    assert all(e.id != "e1" for e in graph.edges)


def test_remove_unknown_edge_raises() -> None:
    with pytest.raises(GraphEditError):
        GraphEditor.remove_edge(_graph(), "ghost")


def test_edits_chain() -> None:
    graph = _graph()
    graph = GraphEditor.add_node(graph, node_id="d", label="Valid?", node_type=NodeType.DECISION)
    graph = GraphEditor.add_edge(graph, source="a", target="d")
    graph = GraphEditor.add_edge(graph, source="d", target="end", label="yes")
    assert "d" in graph.node_ids
    assert len([e for e in graph.edges if e.source == "d"]) == 1
