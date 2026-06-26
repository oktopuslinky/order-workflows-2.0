"""Tests for relational fact extraction: referential integrity + semantic wiring.

These cover the two levers that kill the positional-wiring hallucinations:
(1) ``WorkflowStructure.validated`` drops dangling id references, and
(2) ``WorkflowGraphBuilder.build_from_structure`` wires edges from the explicit
links (decision→activity, exception→activity, compensation→activity, parallel
groups, event emitter) instead of pairing facts by array position.
"""

from __future__ import annotations

from workflow_compiler.agents import FactExtractionAgent
from workflow_compiler.graph import WorkflowGraphBuilder
from workflow_compiler.llm import MockProvider
from workflow_compiler.models import (
    ActivityNode,
    CompensationNode,
    DecisionNode,
    EdgeType,
    EventNode,
    ExceptionNode,
    FactCategory,
    NodeType,
    TransitionEdge,
    WorkflowState,
    WorkflowStructure,
)


def _edge(graph, source, target, edge_type=None):  # type: ignore[no-untyped-def]
    return next(
        (
            e
            for e in graph.edges
            if e.source == source
            and e.target == target
            and (edge_type is None or e.edge_type is edge_type)
        ),
        None,
    )


# --- Lever 2: referential integrity -----------------------------------------


def test_validated_drops_dangling_references() -> None:
    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Reserve")],
        decisions=[
            DecisionNode(
                id="d1", question="ok?", after="a9", yes_target="a1", no_target="e9"
            )
        ],
        exceptions=[ExceptionNode(id="e1", reason="Boom", raised_by="a9")],
        compensations=[CompensationNode(id="c1", name="Undo", compensates="a9")],
    )
    clean, warnings = structure.validated()

    # Unknown references are nulled; valid ones are kept.
    assert clean.decisions[0].after is None  # a9 not declared
    assert clean.decisions[0].no_target is None  # e9 not declared
    assert clean.decisions[0].yes_target == "a1"  # a1 is a real activity
    assert clean.exceptions[0].raised_by is None  # a9 not declared
    assert clean.compensations[0].compensates is None  # a9 not declared
    assert len(warnings) == 4


def test_validated_drops_entity_id_transitions() -> None:
    # The model sometimes leaks the step flow (a1 -> a2 -> d1) into the state
    # transitions; those must be dropped, but real state-name transitions kept.
    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Reserve"), ActivityNode(id="a2", name="Charge")],
        decisions=[DecisionNode(id="d1", question="ok?")],
        transitions=[
            TransitionEdge(source="a1", target="a2"),  # entity-id leak
            TransitionEdge(source="d1", target="a2"),  # entity-id leak
            TransitionEdge(source="active", target="charged"),  # real state names
        ],
    )
    clean, warnings = structure.validated()
    assert [(t.source, t.target) for t in clean.transitions] == [("active", "charged")]
    assert sum("references an entity id" in w for w in warnings) == 2


def test_non_compensated_exception_terminates_instead_of_dangling() -> None:
    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Check eligibility")],
        exceptions=[ExceptionNode(id="e1", reason="NOT_ELIGIBLE", raised_by="a1")],
    )
    graph, _ = WorkflowGraphBuilder().build_from_structure(structure)
    exc = next(n.id for n in graph.nodes if n.label == "NOT_ELIGIBLE")
    assert _edge(graph, "activity_1", exc, EdgeType.ERROR) is not None
    # The exception now routes to a terminal — it is no longer a dead-end.
    assert _edge(graph, exc, "end", EdgeType.SEQUENCE) is not None
    assert [e for e in graph.edges if e.source == exc]


# --- Lever 1: semantic wiring -----------------------------------------------


def _subscription_like() -> WorkflowStructure:
    return WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate request payload"),
            ActivityNode(id="a2", name="Resolve target plan"),
            ActivityNode(id="a3", name="Check subscription eligibility"),
            ActivityNode(id="a4", name="Calculate proration amount"),
            ActivityNode(id="a5", name="Pre-authorise proration charge"),
            ActivityNode(id="a6", name="Update entitlements"),
            ActivityNode(id="a7", name="Send upgrade confirmation", parallel_group="g1"),
            ActivityNode(id="a8", name="Record upgrade audit trail", parallel_group="g1"),
        ],
        decisions=[
            DecisionNode(
                id="d1", question="Eligible?", after="a3", yes_target="a4", no_target="e1"
            ),
            DecisionNode(
                id="d2", question="Pre-auth ok?", after="a5", yes_target="a6", no_target="e2"
            ),
        ],
        exceptions=[
            ExceptionNode(id="e1", reason="SUBSCRIPTION_NOT_UPGRADEABLE", raised_by="a3"),
            ExceptionNode(id="e2", reason="PAYMENT_PRE_AUTH_FAILED", raised_by="a5"),
            ExceptionNode(id="e3", reason="Entitlement update failure", raised_by="a6"),
        ],
        compensations=[
            CompensationNode(id="c1", name="Release pre-authorisation", compensates="a5"),
            CompensationNode(id="c2", name="Restore old entitlements", compensates="a6"),
        ],
        events=[EventNode(id="v1", name="oms.subscription.upgrade.started", emitted_by="a6")],
    )


def test_semantic_wiring_attaches_relations_to_the_right_nodes() -> None:
    graph, _ = WorkflowGraphBuilder().build_from_structure(_subscription_like())

    nid = {n.label: n.id for n in graph.nodes}
    eligibility = nid["Check subscription eligibility"]  # activity_3
    entitlements = nid["Update entitlements"]  # activity_6

    # Decision sits AFTER its activity, not at activity_1.
    decision_1 = next(n.id for n in graph.nodes if n.label == "Eligible?")
    assert _edge(graph, eligibility, decision_1) is not None
    no_edge = next(
        e for e in graph.edges if e.source == decision_1 and e.condition == "no"
    )
    assert graph_label(graph, no_edge.target) == "SUBSCRIPTION_NOT_UPGRADEABLE"

    # Exception is raised by the activity that owns it.
    sub_exc = next(n.id for n in graph.nodes if n.label == "SUBSCRIPTION_NOT_UPGRADEABLE")
    from workflow_compiler.models import EdgeType

    assert _edge(graph, eligibility, sub_exc, EdgeType.ERROR) is not None

    # Compensation hangs off the exception of the activity it reverses (a5/a6),
    # never blanket-routed to compensation_1.
    preauth_exc = next(n.id for n in graph.nodes if n.label == "PAYMENT_PRE_AUTH_FAILED")
    release = next(n.id for n in graph.nodes if n.label == "Release pre-authorisation")
    assert _edge(graph, preauth_exc, release, EdgeType.COMPENSATION) is not None

    # Event emitted by its specific activity (a6), not the last one.
    started = next(n.id for n in graph.nodes if "started" in n.label)
    assert _edge(graph, entitlements, started, EdgeType.SIGNAL) is not None

    # Parallel group becomes fork/join.
    gateways = {n.node_type for n in graph.nodes if n.node_type is NodeType.GATEWAY}
    assert gateways == {NodeType.GATEWAY}
    assert any(e.label == "parallel" for e in graph.edges)


def graph_label(graph, node_id):  # type: ignore[no-untyped-def]
    return next(n.label for n in graph.nodes if n.id == node_id)


# --- Agent integration ------------------------------------------------------


async def test_agent_builds_validated_structure() -> None:
    payload = {
        "activity_nodes": [
            {"id": "a1", "name": "Reserve stock"},
            {"id": "a2", "name": "Charge card"},
        ],
        "exception_nodes": [{"id": "e1", "reason": "Declined", "raised_by": "a2"}],
        "compensation_nodes": [
            {"id": "c1", "name": "Release stock", "compensates": "a1"},
            {"id": "c2", "name": "Bad ref", "compensates": "a99"},  # dangling
        ],
        "confidence": 0.7,
    }
    agent = FactExtractionAgent(MockProvider(structured=[payload]))
    state = await agent.run(WorkflowState(document_text="doc"))

    structure = state.workflow_facts.structure
    assert structure is not None
    assert {a.id for a in structure.activities} == {"a1", "a2"}
    # Dangling compensation reference was dropped by validation.
    bad = next(c for c in structure.compensations if c.id == "c2")
    assert bad.compensates is None
    assert "dangling reference(s) dropped" in state.confidence_scores.notes["facts"]

    # Flat facts are still derived for downstream consumers.
    comps = [f.statement for f in state.workflow_facts.by_category(FactCategory.COMPENSATION)]
    assert "Release stock compensates Reserve stock" in comps
