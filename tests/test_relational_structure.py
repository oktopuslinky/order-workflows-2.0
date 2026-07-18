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


def _node_by_label(graph, label):  # type: ignore[no-untyped-def]
    return next(n.id for n in graph.nodes if n.label == label)


# --- Upstream normalization: parallel / decision / orphan guardrails ---------


def test_validated_strips_parallel_group_from_decision_anchor_only() -> None:
    """A decision's anchor is ordered (its result feeds the decision) and must
    leave its parallel group; a branch *target* keeps its group — the decision
    gates the whole group (the builder routes the branch edge to the fork)."""
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Reprovision", parallel_group="g"),
            ActivityNode(id="a2", name="Update inventory", parallel_group="g"),
            ActivityNode(id="a3", name="Send events", parallel_group="g"),
        ],
        decisions=[
            DecisionNode(id="d1", question="ok?", after="a1", yes_target="a2", no_target="end")
        ],
    )
    clean, warnings = structure.validated()
    groups = {a.id: a.parallel_group for a in clean.activities}
    assert groups["a1"] is None  # gated as the decision anchor
    assert groups["a2"] == "g"  # branch target: the decision gates the group
    assert groups["a3"] == "g"  # genuinely parallel — left intact
    assert any("parallel group" in w for w in warnings)


def test_validated_repairs_degenerate_decision() -> None:
    """A decision whose yes/no targets are identical reroutes 'no' to its exception."""
    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Validate promo")],
        decisions=[
            DecisionNode(id="d1", question="valid?", after="a1", yes_target="a2", no_target="a2")
        ],
        # a2 is not declared, so keep_target nulls it; declare it to isolate B3.
    )
    structure = structure.model_copy(
        update={"activities": [*structure.activities, ActivityNode(id="a2", name="Apply promo")]}
    )
    structure = structure.model_copy(
        update={"exceptions": [ExceptionNode(id="x1", reason="Invalid promo", raised_by="a1")]}
    )
    clean, warnings = structure.validated()
    decision = clean.decisions[0]
    assert decision.yes_target == "a2"
    assert decision.no_target == "x1"  # rerouted to the gated activity's exception
    assert any("identical yes/no" in w for w in warnings)


def _unrouted(exceptions: list[ExceptionNode]) -> WorkflowStructure:
    """A decision with no 'no' branch, gated by a1, over the given exceptions."""
    return WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate cart"),
            ActivityNode(id="a2", name="Reserve inventory"),
        ],
        decisions=[
            DecisionNode(id="d1", question="eligible?", after="a1", yes_target="a2")
        ],
        exceptions=exceptions,
    )


def test_validated_routes_an_unwired_no_branch_to_the_sole_exception() -> None:
    """A missing 'no' branch is wired to the one exception the gated activity raises."""
    structure = _unrouted([ExceptionNode(id="e1", reason="CartNotEligible", raised_by="a1")])
    clean, warnings = structure.validated()
    assert clean.decisions[0].no_target == "e1"
    assert any("no 'no' branch" in w for w in warnings)


def test_validated_leaves_an_ambiguous_no_branch_unwired() -> None:
    """Two candidate exceptions (or none) means guessing — leave it for the gate."""
    ambiguous = _unrouted(
        [
            ExceptionNode(id="e1", reason="CartNotEligible", raised_by="a1"),
            ExceptionNode(id="e2", reason="CartExpired", raised_by="a1"),
        ]
    )
    assert ambiguous.validated()[0].decisions[0].no_target is None

    # And an exception that names no activity is no candidate at all — this is the
    # shape that produced the uncompiled order-placement workflow.
    unattached = _unrouted([ExceptionNode(id="e1", reason="CartNotEligible")])
    assert unattached.validated()[0].decisions[0].no_target is None


def test_event_kinds_wire_distinctly() -> None:
    """trigger / signal_wait / output_emit each wire to a different shape."""
    from workflow_compiler.models import EventKind, NodeType

    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Dispatch shipment"),
            ActivityNode(id="a2", name="Capture payment"),
        ],
        events=[
            EventNode(id="v1", name="order.fulfil", emitted_by="start",
                      kind=EventKind.TRIGGER),
            EventNode(id="v2", name="carrier.picked_up", emitted_by="a1",
                      kind=EventKind.SIGNAL_WAIT),
            EventNode(id="v3", name="shipment_id", emitted_by="a2",
                      kind=EventKind.OUTPUT_EMIT),
        ],
    )
    graph, _ = WorkflowGraphBuilder().build_from_structure(structure)
    by_label = {n.label: n for n in graph.nodes}
    wait = by_label["carrier.picked_up"]
    # The signal-wait is a SIGNAL node, inline (has an outgoing edge — not a dead-end).
    assert wait.node_type is NodeType.SIGNAL
    assert any(e.source == wait.id for e in graph.edges), "wait must not be a dead-end"
    assert any(
        e.target == wait.id and e.source == by_label["Dispatch shipment"].id
        for e in graph.edges
    )
    # The trigger enters from start; the output-emit is a plain event emitted by a2.
    assert by_label["order.fulfil"].node_type is NodeType.EVENT
    assert any(e.source == "start" and e.target == by_label["order.fulfil"].id
               for e in graph.edges)
    emit = by_label["shipment_id"]
    assert emit.node_type is NodeType.EVENT
    assert any(
        e.source == by_label["Capture payment"].id and e.target == emit.id
        and e.label == "emits"
        for e in graph.edges
    )


def test_orphan_activity_reconnected_to_predecessor() -> None:
    """An activity stranded when a decision replaces its spine edge gets an inbound edge."""
    structure = WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="First"),
            ActivityNode(id="a2", name="Second"),
            ActivityNode(id="a3", name="Audit"),
        ],
        decisions=[
            DecisionNode(id="d1", question="ok?", after="a2", yes_target="end", no_target="end")
        ],
    )
    graph, _nx = WorkflowGraphBuilder().build_from_structure(structure)
    audit = _node_by_label(graph, "Audit")
    assert [e for e in graph.edges if e.target == audit], "Audit must not be an orphan"


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


def test_trigger_nodes_wire_into_graph() -> None:
    """TriggerNodes appear as NodeType.TRIGGER, wired off their anchor —
    conditional triggers with a CONDITIONAL edge, unconditional with SEQUENCE —
    and decisions may target trigger ids directly."""
    from workflow_compiler.models import TriggerNode

    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Validate order")],
        decisions=[
            DecisionNode(id="d1", question="Escalate?", after="a1",
                         yes_target="t1", no_target="t2"),
        ],
        triggers=[
            TriggerNode(id="t1", target_workflow="escalation", mode="blocking"),
            TriggerNode(id="t2", target_workflow="archival",
                        condition="order.value < 10", after="a1"),
        ],
    )
    graph, _ = WorkflowGraphBuilder().build_from_structure(structure)
    by_label = {n.label: n for n in graph.nodes}
    esc = by_label["Trigger escalation"]
    arc = by_label["Trigger archival"]
    assert esc.node_type is NodeType.TRIGGER and arc.node_type is NodeType.TRIGGER
    assert esc.attributes["target_workflow"] == "escalation"
    assert esc.attributes["mode"] == "blocking"
    # Both trigger nodes are decision branch targets (yes → t1, no → t2), so the
    # standalone attach loop must not add duplicate inbound edges.
    decision = by_label["Escalate?"]
    yes = [e for e in graph.edges if e.source == decision.id and e.condition == "yes"]
    no = [e for e in graph.edges if e.source == decision.id and e.condition == "no"]
    assert yes[0].target == esc.id and no[0].target == arc.id
    assert len([e for e in graph.edges if e.target == esc.id]) == 1


def test_unanchored_conditional_trigger_gets_conditional_edge() -> None:
    from workflow_compiler.models import EdgeType, TriggerNode

    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Process")],
        triggers=[
            TriggerNode(id="t1", target_workflow="reporting",
                        condition="total > 100", after="a1"),
        ],
    )
    graph, _ = WorkflowGraphBuilder().build_from_structure(structure)
    by_label = {n.label: n for n in graph.nodes}
    edge = next(e for e in graph.edges if e.target == by_label["Trigger reporting"].id)
    assert edge.edge_type is EdgeType.CONDITIONAL
    assert edge.condition == "total > 100"
    assert edge.source == by_label["Process"].id


def test_validated_nulls_dangling_trigger_anchor() -> None:
    from workflow_compiler.models import TriggerNode

    structure = WorkflowStructure(
        activities=[ActivityNode(id="a1", name="Work")],
        triggers=[TriggerNode(id="t1", target_workflow="x", after="a99")],
    )
    clean, warnings = structure.validated()
    assert clean.triggers[0].after is None
    assert any("trigger t1" in w for w in warnings)
