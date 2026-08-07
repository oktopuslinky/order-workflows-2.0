"""Unit tests for TemporalGeneratorAgent."""

from __future__ import annotations

import pytest

from workflow_compiler.agents import TemporalDesignOutput, TemporalGeneratorAgent
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    CompilationStage,
    CVPAClassification,
    CVPANodeAssignment,
    CVPAPhase,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowMetadata,
    WorkflowNode,
    WorkflowState,
)


def _graph() -> WorkflowGraph:
    return WorkflowGraph(
        nodes=[
            WorkflowNode(id="start", label="Start", node_type=NodeType.START),
            WorkflowNode(id="work", label="Process order", node_type=NodeType.TASK),
            WorkflowNode(id="end", label="Done", node_type=NodeType.END),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="work"),
            WorkflowEdge(id="e2", source="work", target="end"),
        ],
    )


def _cvpa() -> CVPAClassification:
    return CVPAClassification(
        assignments=[
            CVPANodeAssignment(node_id="start", phase=CVPAPhase.CAPTURE, confidence=0.9),
            CVPANodeAssignment(node_id="work", phase=CVPAPhase.PROCESS, confidence=0.9),
            CVPANodeAssignment(node_id="end", phase=CVPAPhase.ACTIVATE, confidence=0.9),
        ]
    )


def _state(*, with_meta: bool = True) -> WorkflowState:
    state = WorkflowState(document_text="doc")
    state.workflow_graph = _graph()
    state.cvpa_classification = _cvpa()
    if with_meta:
        state.workflow_metadata = WorkflowMetadata(name="Order Fulfillment", purpose="Fulfill.")
    return state


def _full_output() -> TemporalDesignOutput:
    return TemporalDesignOutput.model_validate(
        {
            "workflow_name": "Order Fulfillment",
            "task_queue": "orders",
            "description": "Fulfill customer orders.",
            "activities": [
                {
                    "name": "process order",
                    "source_node_id": "work",
                    "description": "Process the order.",
                    "inputs": ["order_id"],
                    "outputs": ["receipt"],
                    "timeout_seconds": 30,
                    "retry_policy": {"maximum_attempts": 5, "backoff_coefficient": 2.0},
                }
            ],
            "signals": [{"name": "cancel", "description": "Cancel order", "payload": ["reason"]}],
            "queries": [{"name": "status", "returns": "OrderStatus"}],
            "child_workflows": [
                {"name": "ship order", "source_node_id": "work", "inputs": ["order_id"]}
            ],
            "timers": [{"name": "sla", "duration_seconds": 3600, "description": "SLA"}],
            "compensation_activities": [
                {"name": "refund order", "compensates": "ProcessOrder", "source_node_id": "work"}
            ],
            "default_retry_policy": {"maximum_attempts": 3},
            "confidence": 0.9,
        }
    )


async def test_generates_full_design() -> None:
    provider = MockProvider(structured=[_full_output()])
    state = await TemporalGeneratorAgent(provider).run(_state())

    design = state.temporal_design
    assert design is not None
    assert design.workflow_name == "OrderFulfillment"  # slugged
    assert design.task_queue == "orders"
    assert len(design.activities) == 1
    assert design.activities[0].name == "ProcessOrder"
    assert design.activities[0].retry_policy is not None
    assert design.activities[0].retry_policy.maximum_attempts == 5
    assert len(design.signals) == 1
    assert len(design.queries) == 1
    assert len(design.child_workflows) == 1
    assert len(design.timers) == 1
    assert len(design.compensation_activities) == 1
    assert design.compensation_activities[0].compensates == "ProcessOrder"
    assert design.default_retry_policy is not None
    assert state.stage is CompilationStage.TEMPORAL_DESIGNED
    assert state.confidence_scores is not None
    assert state.confidence_scores.temporal is not None


async def test_workflow_name_falls_back_to_metadata() -> None:
    output = TemporalDesignOutput.model_validate({"activities": []})
    provider = MockProvider(structured=[output])
    state = await TemporalGeneratorAgent(provider).run(_state())
    assert state.temporal_design.workflow_name == "OrderFulfillment"
    # Task queue defaults from the workflow name.
    assert state.temporal_design.task_queue == "OrderFulfillment-task-queue"


async def test_invalid_entries_are_dropped() -> None:
    output = TemporalDesignOutput.model_validate(
        {
            "workflow_name": "W",
            "activities": [{"name": ""}, {"name": "do thing"}],
            "timers": [
                {"name": "bad", "duration_seconds": 0},
                {"name": "ok", "duration_seconds": 5},
            ],
        }
    )
    provider = MockProvider(structured=[output])
    state = await TemporalGeneratorAgent(provider).run(_state())
    design = state.temporal_design
    assert [a.name for a in design.activities] == ["DoThing"]
    assert [t.name for t in design.timers] == ["ok"]


async def test_retry_policy_is_normalized() -> None:
    output = TemporalDesignOutput.model_validate(
        {
            "workflow_name": "W",
            "default_retry_policy": {"maximum_attempts": -2, "backoff_coefficient": 0.5},
        }
    )
    provider = MockProvider(structured=[output])
    state = await TemporalGeneratorAgent(provider).run(_state())
    policy = state.temporal_design.default_retry_policy
    assert policy is not None
    assert policy.maximum_attempts == 0  # clamped from -2
    assert policy.backoff_coefficient == 1.0  # clamped up to the >=1 floor


async def test_does_not_emit_executable_code_fields() -> None:
    # The design surface is specification-only: there is no field that could
    # carry executable Temporal code (no `code`, `source`, or `body`).
    provider = MockProvider(structured=[_full_output()])
    state = await TemporalGeneratorAgent(provider).run(_state())
    dumped = state.temporal_design.model_dump()
    forbidden = {"code", "source_code", "body", "implementation"}
    assert forbidden.isdisjoint(dumped)


async def test_requires_graph_and_cvpa() -> None:
    provider = MockProvider(structured=[_full_output(), _full_output()])
    no_graph = WorkflowState(document_text="doc")
    with pytest.raises(CompilationError):
        await TemporalGeneratorAgent(provider).run(no_graph)

    no_cvpa = WorkflowState(document_text="doc")
    no_cvpa.workflow_graph = _graph()
    with pytest.raises(CompilationError):
        await TemporalGeneratorAgent(provider).run(no_cvpa)


async def test_requires_llm() -> None:
    with pytest.raises(CompilationError):
        await TemporalGeneratorAgent(None).run(_state())


# --- Stage A: prune signal gates that wait on the workflow's own output -----


def _emit_graph() -> WorkflowGraph:
    """A graph whose activity emits an ``order_id`` event (an output)."""
    return WorkflowGraph(
        nodes=[
            WorkflowNode(id="start", label="Start", node_type=NodeType.START),
            WorkflowNode(id="activity_1", label="Create order", node_type=NodeType.TASK),
            WorkflowNode(
                id="event_1", label="[ev1] order_id emitted", node_type=NodeType.EVENT
            ),
            WorkflowNode(id="end", label="End", node_type=NodeType.END),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="activity_1"),
            WorkflowEdge(id="e2", source="activity_1", target="event_1", label="emits"),
        ],
    )


def _design_with_gate(*, timers):  # type: ignore[no-untyped-def]
    from workflow_compiler.models import (
        StepKind,
        TemporalSignalDesign,
        TemporalStep,
        TemporalWorkflowDesign,
    )

    return TemporalWorkflowDesign(
        workflow_name="Placement",
        signals=[TemporalSignalDesign(name="order_id_emitted")],
        timers=timers,
        plan=[
            TemporalStep(id="a", kind=StepKind.ACTIVITY, ref="CreateOrder"),
            TemporalStep(id="g", kind=StepKind.SIGNAL_GATE, signal="order_id_emitted"),
        ],
    )


def test_prune_drops_unbounded_self_output_gate() -> None:
    agent = TemporalGeneratorAgent(MockProvider())
    design = _design_with_gate(timers=[])
    pruned = agent._prune_ungrounded_signal_gates(design, _emit_graph())
    kinds = [s.kind.value for s in pruned.plan]
    assert "signal_gate" not in kinds  # the self-output wait is gone
    assert pruned.signals == []  # orphaned signal declaration removed


def test_prune_keeps_timer_bounded_gate() -> None:
    from workflow_compiler.models import TemporalTimerDesign

    agent = TemporalGeneratorAgent(MockProvider())
    # A gate whose event pairs with a timer is bounded — it times out, never hangs.
    design = _design_with_gate(
        timers=[TemporalTimerDesign(name="OrderIdEmittedTimeout", duration_seconds=60)]
    )
    pruned = agent._prune_ungrounded_signal_gates(design, _emit_graph())
    assert any(s.kind.value == "signal_gate" for s in pruned.plan)
    assert pruned.signals  # declaration retained


# -- deterministic cross-workflow trigger injection ---------------------------


def test_outgoing_triggers_injected_into_design() -> None:
    from workflow_compiler.models import (
        BindingSource,
        StepKind,
        TriggerInputBinding,
        TriggerMode,
        WorkflowTrigger,
    )

    agent = TemporalGeneratorAgent(MockProvider())
    base = agent._to_design(_full_output(), _state())
    triggers = [
        WorkflowTrigger(
            source_workflow="order-fulfillment",
            target_workflow="account-provisioning",
            mode=TriggerMode.BLOCKING,
            input_map=[
                TriggerInputBinding(
                    target_input="customer_record_id",
                    source=BindingSource.STEP_OUTPUT,
                    source_ref="a1",
                    type="str",
                )
            ],
            result_binding="provisioning_result",
            user_confirmed=True,
        ),
        WorkflowTrigger(
            source_workflow="order-fulfillment",
            target_workflow="audit-log",
            mode=TriggerMode.FIRE_AND_FORGET,
            condition="order.amount > 100",
            user_confirmed=True,
        ),
    ]
    design = agent._inject_triggers(base, triggers)

    # Declarations: one per trigger, carrying the typed input params.
    assert [t.name for t in design.triggers] == ["StartAccountProvisioning", "StartAuditLog"]
    blocking = design.triggers[0]
    assert blocking.target_workflow_name == "AccountProvisioning"
    assert blocking.target_slug == "account-provisioning"
    assert blocking.mode == "blocking"
    assert [p.name for p in blocking.params] == ["customer_record_id"]

    # Plan: unconditional trigger appended as a TRIGGER step with bindings +
    # result; conditional one wrapped in a BRANCH whose then-lane triggers.
    trigger_step = next(s for s in design.plan if s.kind is StepKind.TRIGGER)
    assert trigger_step.ref == "StartAccountProvisioning"
    assert trigger_step.result_name == "provisioning_result"
    assert trigger_step.bindings[0].param == "customer_record_id"
    assert trigger_step.bindings[0].source is BindingSource.STEP_OUTPUT
    branch = next(
        s for s in design.plan
        if s.kind is StepKind.BRANCH and s.predicate == "order.amount > 100"
    )
    assert branch.lanes[0][0].kind is StepKind.TRIGGER
    assert branch.lanes[0][0].ref == "StartAuditLog"
    assert branch.lanes[1] == []


async def test_run_injects_state_outgoing_triggers() -> None:
    from workflow_compiler.models import StepKind, TriggerMode, WorkflowTrigger

    provider = MockProvider(structured=[_full_output()])
    state = _state()
    state.outgoing_triggers = [
        WorkflowTrigger(
            source_workflow="order-fulfillment",
            target_workflow="reporting",
            mode=TriggerMode.FIRE_AND_FORGET,
            user_confirmed=True,
        )
    ]
    state = await TemporalGeneratorAgent(provider).run(state)
    design = state.temporal_design
    assert design is not None
    assert [t.name for t in design.triggers] == ["StartReporting"]
    assert any(s.kind is StepKind.TRIGGER for s in design.plan)


# --- deterministic rejection-lane termination -------------------------------


def _rejection_structure():
    from workflow_compiler.models import (
        ActivityNode,
        DecisionNode,
        ExceptionNode,
        WorkflowStructure,
    )

    return WorkflowStructure(
        activities=[
            ActivityNode(id="a1", name="Validate Order"),
            ActivityNode(id="a2", name="Reserve Inventory"),
        ],
        decisions=[
            DecisionNode(
                id="d1", question="Is the order settleable?",
                after="a1", yes_target="a2", no_target="e1",
            )
        ],
        exceptions=[ExceptionNode(id="e1", reason="OrderNotSettleable", raised_by="a1")],
    )


def test_rejection_lane_gets_raise_step() -> None:
    from workflow_compiler.models import StepKind, TemporalStep, TemporalWorkflowDesign

    design = TemporalWorkflowDesign(
        workflow_name="Settle",
        plan=[
            TemporalStep(
                id="s1", kind=StepKind.ACTIVITY, ref="ValidateOrder",
                result_name="is_settleable",
            ),
            TemporalStep(
                id="s2", kind=StepKind.BRANCH, predicate="is_settleable",
                lanes=[
                    [TemporalStep(id="s3", kind=StepKind.ACTIVITY, ref="ReserveInventory")],
                    [],
                ],
            ),
        ],
    )
    out = TemporalGeneratorAgent._terminate_rejection_lanes(design, _rejection_structure())
    branch = out.plan[1]
    assert branch.lanes[1], "else lane must gain a RAISE step"
    assert branch.lanes[1][0].kind is StepKind.RAISE
    assert branch.lanes[1][0].ref == "OrderNotSettleable"


def test_rejection_raise_not_injected_without_anchor_match() -> None:
    """A branch that doesn't immediately follow its decision's anchor is untouched."""
    from workflow_compiler.models import StepKind, TemporalStep, TemporalWorkflowDesign

    design = TemporalWorkflowDesign(
        workflow_name="Settle",
        plan=[
            TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="SomethingElse"),
            TemporalStep(
                id="s2", kind=StepKind.BRANCH, predicate="whatever",
                lanes=[
                    [TemporalStep(id="s3", kind=StepKind.ACTIVITY, ref="ReserveInventory")],
                    [],
                ],
            ),
        ],
    )
    out = TemporalGeneratorAgent._terminate_rejection_lanes(design, _rejection_structure())
    assert out.plan[1].lanes[1] == []


def test_rejection_raise_not_injected_when_else_lane_populated() -> None:
    from workflow_compiler.models import StepKind, TemporalStep, TemporalWorkflowDesign

    design = TemporalWorkflowDesign(
        workflow_name="Settle",
        plan=[
            TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="ValidateOrder"),
            TemporalStep(
                id="s2", kind=StepKind.BRANCH, predicate="is_settleable",
                lanes=[
                    [TemporalStep(id="s3", kind=StepKind.ACTIVITY, ref="ReserveInventory")],
                    [TemporalStep(id="s4", kind=StepKind.ACTIVITY, ref="NotifyRejection")],
                ],
            ),
        ],
    )
    out = TemporalGeneratorAgent._terminate_rejection_lanes(design, _rejection_structure())
    assert [s.id for s in out.plan[1].lanes[1]] == ["s4"]


def test_misplaced_raises_are_pruned() -> None:
    """RAISE steps survive only inside a branch's else-lane."""
    from workflow_compiler.models import StepKind, TemporalStep, TemporalWorkflowDesign

    design = TemporalWorkflowDesign(
        workflow_name="Settle",
        plan=[
            TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="ValidateOrder"),
            TemporalStep(
                id="s2", kind=StepKind.BRANCH, predicate="ok",
                lanes=[
                    [  # then-lane: raise here fails every successful run
                        TemporalStep(id="s3", kind=StepKind.ACTIVITY, ref="Reserve"),
                        TemporalStep(id="bad1", kind=StepKind.RAISE, ref="Nope"),
                    ],
                    [TemporalStep(id="ok1", kind=StepKind.RAISE, ref="Rejected")],
                ],
            ),
            TemporalStep(id="bad2", kind=StepKind.RAISE, ref="AlsoNope"),
        ],
    )
    out = TemporalGeneratorAgent._prune_misplaced_raises(design)
    assert [s.id for s in out.plan] == ["s1", "s2"]
    assert [s.id for s in out.plan[1].lanes[0]] == ["s3"]
    assert [s.id for s in out.plan[1].lanes[1]] == ["ok1"]
