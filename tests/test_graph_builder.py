"""Unit tests for the deterministic GraphBuilderAgent and builder."""

from __future__ import annotations

import networkx as nx
import pytest

from workflow_compiler.agents import GraphBuilderAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.graph import WorkflowGraphBuilder, to_mermaid
from workflow_compiler.models import (
    CompilationStage,
    EdgeType,
    FactCategory,
    NodeType,
    WorkflowFact,
    WorkflowFacts,
    WorkflowState,
)


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


def _edge(graph, source, target, edge_type):
    return next(
        (
            e
            for e in graph.edges
            if e.source == source and e.target == target and e.edge_type is edge_type
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Builder structure
# ---------------------------------------------------------------------------


def test_linear_activities_form_a_spine() -> None:
    graph, nxg = WorkflowGraphBuilder().build(_facts(activity=["A", "B", "C"]))
    ids = graph.node_ids
    assert {"start", "end", "activity_1", "activity_2", "activity_3"} <= ids
    assert _edge(graph, "start", "activity_1", EdgeType.SEQUENCE)
    assert _edge(graph, "activity_3", "end", EdgeType.SEQUENCE)
    assert nx.has_path(nxg, "start", "end")


def test_decision_creates_conditional_branches() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(activity=["A", "B"], decision=["Is it valid?"], exception=["Validation failed"])
    )
    decisions = [n for n in graph.nodes if n.node_type is NodeType.DECISION]
    assert decisions
    dec_id = decisions[0].id
    conditionals = [
        e for e in graph.edges if e.source == dec_id and e.edge_type is EdgeType.CONDITIONAL
    ]
    assert {e.condition for e in conditionals} == {"yes", "no"}
    # The "no" branch routes to the failure (exception) node.
    no_edge = next(e for e in conditionals if e.condition == "no")
    assert no_edge.target.startswith("exception_")


def test_failure_path_uses_error_edge() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(activity=["Charge card"], exception=["Card declined"])
    )
    error_edges = [e for e in graph.edges if e.edge_type is EdgeType.ERROR]
    assert error_edges
    assert error_edges[0].source == "activity_1"
    assert error_edges[0].target == "exception_1"


def test_retry_path_creates_retry_edge() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(
            activity=["Charge card"],
            exception=["Card declined"],
            retry=["Retry charge up to 3 times"],
        )
    )
    retry_edges = [e for e in graph.edges if e.edge_type is EdgeType.RETRY]
    assert retry_edges
    assert retry_edges[0].source == "exception_1"
    assert retry_edges[0].target == "activity_1"


def test_compensation_path() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(
            activity=["Reserve stock"],
            exception=["Reservation failed"],
            compensation=["Release stock"],
        )
    )
    comp_nodes = [n for n in graph.nodes if n.attributes.get("role") == "compensation"]
    assert comp_nodes
    comp_id = comp_nodes[0].id
    assert _edge(graph, "exception_1", comp_id, EdgeType.COMPENSATION)
    assert _edge(graph, comp_id, "end", EdgeType.SEQUENCE)


def test_parallel_branches_create_gateways() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(
            activity=[
                "Receive order",
                "Notify warehouse in parallel",
                "Charge card concurrently",
                "Close order",
            ]
        )
    )
    gateways = [n for n in graph.nodes if n.node_type is NodeType.GATEWAY]
    assert {n.id for n in gateways} == {"gateway_fork", "gateway_join"}
    parallel_edges = [e for e in graph.edges if e.label == "parallel"]
    assert parallel_edges
    assert all(e.source == "gateway_fork" or e.target == "gateway_join" for e in parallel_edges)


def test_state_transitions_become_edges() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(
            activity=["Process"],
            state_transition=["Received -> Validated", "Validated -> Shipped"],
        )
    )
    transition_edges = [e for e in graph.edges if e.label == "transition"]
    assert len(transition_edges) == 2
    # "Validated" is reused across both transitions (single node).
    labels = {n.label for n in graph.nodes}
    assert {"Received", "Validated", "Shipped"} <= labels


def test_empty_facts_still_produce_minimal_graph() -> None:
    graph, nxg = WorkflowGraphBuilder().build(WorkflowFacts(facts=[]))
    assert graph.node_ids == {"start", "end"}
    assert nx.has_path(nxg, "start", "end")


# ---------------------------------------------------------------------------
# Mermaid
# ---------------------------------------------------------------------------


def test_mermaid_rendering() -> None:
    graph, _ = WorkflowGraphBuilder().build(
        _facts(activity=["A", "B"], decision=["valid?"], exception=["failed"])
    )
    diagram = to_mermaid(graph)
    assert diagram.source.startswith("flowchart TD")
    assert 'activity_1["A"]' in diagram.source
    assert "-->" in diagram.source
    assert "-.->" in diagram.source  # error/dotted edge
    # Edge labels use the bare |label| form (no surrounding quotes).
    assert "|yes|" in diagram.source
    assert '|"yes"|' not in diagram.source


def test_mermaid_avoids_reserved_end_keyword() -> None:
    graph, _ = WorkflowGraphBuilder().build(_facts(activity=["A"]))
    source = to_mermaid(graph).source
    # The reserved id "end" must be rewritten; no line may declare or target it.
    assert "end_node" in source
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("end(")
        assert not stripped.endswith("--> end")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


async def test_agent_updates_state_without_llm() -> None:
    state = WorkflowState(document_text="doc")
    state.workflow_facts = _facts(activity=["A", "B"], decision=["valid?"])
    agent = GraphBuilderAgent()  # no LLM provided
    state = await agent.run(state)

    assert state.workflow_graph is not None
    assert state.mermaid_diagram is not None
    assert state.mermaid_diagram.source.startswith("flowchart TD")
    assert state.stage is CompilationStage.GRAPH_BUILT
    assert state.confidence_scores is not None
    assert 0.0 < state.confidence_scores.graph <= 1.0


async def test_agent_requires_facts() -> None:
    with pytest.raises(CompilationError):
        await GraphBuilderAgent().run(WorkflowState(document_text="doc"))


async def test_build_is_deterministic() -> None:
    facts = _facts(
        activity=["A", "B in parallel", "C concurrently", "D"],
        decision=["valid?"],
        exception=["failed"],
        retry=["retry"],
        compensation=["undo"],
        event=["Order submitted"],
        state_transition=["X -> Y"],
    )
    g1, _ = WorkflowGraphBuilder().build(facts)
    g2, _ = WorkflowGraphBuilder().build(facts)
    assert [n.id for n in g1.nodes] == [n.id for n in g2.nodes]
    assert [(e.source, e.target, e.edge_type) for e in g1.edges] == [
        (e.source, e.target, e.edge_type) for e in g2.edges
    ]
