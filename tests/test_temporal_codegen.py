"""Tests for deterministic Temporal Python code generation."""

from __future__ import annotations

import ast

import pytest

from workflow_compiler.agents import TemporalCodeGeneratorAgent
from workflow_compiler.codegen.temporal import TemporalPythonCodeGenerator
from workflow_compiler.codegen.temporal.generator import to_temporal_python
from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.models import (
    CompilationStage,
    NodeType,
    RetryPolicyDesign,
    TemporalActivityDesign,
    TemporalChildWorkflowDesign,
    TemporalCompensationDesign,
    TemporalQueryDesign,
    TemporalSignalDesign,
    TemporalTimerDesign,
    TemporalWorkflowDesign,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


def _graph() -> WorkflowGraph:
    return WorkflowGraph(
        nodes=[
            WorkflowNode(id="start", label="Start", node_type=NodeType.START),
            WorkflowNode(id="validate", label="Validate", node_type=NodeType.TASK),
            WorkflowNode(id="work", label="Process", node_type=NodeType.TASK),
            WorkflowNode(id="ship", label="Ship", node_type=NodeType.SUBPROCESS),
            WorkflowNode(id="end", label="Done", node_type=NodeType.END),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="validate"),
            WorkflowEdge(id="e2", source="validate", target="work"),
            WorkflowEdge(id="e3", source="work", target="ship"),
            WorkflowEdge(id="e4", source="ship", target="end"),
        ],
    )


def _design() -> TemporalWorkflowDesign:
    return TemporalWorkflowDesign(
        workflow_name="OrderFulfillment",
        task_queue="orders",
        description="Fulfill customer orders.",
        activities=[
            # Declared out of execution order on purpose: the graph orders them.
            TemporalActivityDesign(
                name="ProcessOrder",
                source_node_id="work",
                inputs=["order_id", "customer id"],
                timeout_seconds=30,
                retry_policy=RetryPolicyDesign(maximum_attempts=5),
            ),
            TemporalActivityDesign(
                name="ValidateOrder", source_node_id="validate", inputs=["order_id"]
            ),
        ],
        signals=[TemporalSignalDesign(name="cancel order", payload=["reason"])],
        queries=[TemporalQueryDesign(name="status", returns="OrderStatus")],
        child_workflows=[
            TemporalChildWorkflowDesign(
                name="ShipOrder", source_node_id="ship", task_queue="shipping"
            )
        ],
        timers=[TemporalTimerDesign(name="sla", duration_seconds=3600, description="SLA")],
        compensation_activities=[
            TemporalCompensationDesign(
                name="RefundOrder", compensates="ProcessOrder", source_node_id="work"
            )
        ],
        default_retry_policy=RetryPolicyDesign(maximum_attempts=3),
    )


def _parse_all(bundle) -> None:  # type: ignore[no-untyped-def]
    for generated in bundle.files:
        if generated.path.endswith(".py"):
            ast.parse(generated.content)


def test_generate_produces_expected_files() -> None:
    bundle = to_temporal_python(_design(), graph=_graph())
    assert bundle.target == "python"
    assert bundle.package_name == "order_fulfillment"
    assert [f.path for f in bundle.files] == [
        "shared.py",
        "activities.py",
        "workflow.py",
        "worker.py",
        "starter.py",
        "README.md",
    ]


def test_generated_python_is_valid() -> None:
    _parse_all(to_temporal_python(_design(), graph=_graph()))


def test_activities_ordered_by_graph() -> None:
    workflow = _file(to_temporal_python(_design(), graph=_graph()), "workflow.py")
    # validate_order is declared second but must run first per the graph spine.
    # Match call sites (the input dataclass follows the fn name), not imports.
    assert workflow.index("validate_order,\n                ValidateOrderInput") < workflow.index(
        "process_order,\n                ProcessOrderInput"
    )


def test_saga_compensation_registered_after_its_activity() -> None:
    workflow = _file(to_temporal_python(_design(), graph=_graph()), "workflow.py")
    assert "compensations.append(" in workflow
    assert "refund_order," in workflow
    # Compensation registration follows the ProcessOrder call.
    assert workflow.index("process_order,") < workflow.index("refund_order,")
    assert "for _comp_fn, _comp_arg in reversed(compensations):" in workflow


def test_signals_queries_and_timers_rendered() -> None:
    workflow = _file(to_temporal_python(_design(), graph=_graph()), "workflow.py")
    assert "@workflow.signal" in workflow
    assert "def cancel_order(self, reason: str) -> None:" in workflow
    assert "@workflow.query" in workflow
    assert "def status(self) -> str:" in workflow
    assert "SLA = timedelta(seconds=3600)" in workflow


def test_child_workflow_stub_and_invocation() -> None:
    workflow = _file(to_temporal_python(_design(), graph=_graph()), "workflow.py")
    assert "await workflow.execute_child_workflow(" in workflow
    assert "ShipOrder.run," in workflow
    assert 'task_queue="shipping",' in workflow
    # A stub class for the child workflow is emitted.
    assert "class ShipOrder:" in workflow


def test_retry_policy_is_rendered() -> None:
    workflow = _file(to_temporal_python(_design(), graph=_graph()), "workflow.py")
    assert "retry_policy=RetryPolicy(" in workflow
    assert "maximum_attempts=5" in workflow


def test_names_are_sanitized() -> None:
    shared = _file(to_temporal_python(_design(), graph=_graph()), "shared.py")
    # "customer id" -> snake field; class names are PascalCase.
    assert "customer_id: str = " in shared
    assert "class ProcessOrderInput:" in shared


def test_empty_design_still_generates_valid_code() -> None:
    bundle = to_temporal_python(TemporalWorkflowDesign(workflow_name="Empty"))
    _parse_all(bundle)
    workflow = _file(bundle, "workflow.py")
    assert "pass  # TODO: no activities were derived" in workflow


def test_works_without_a_graph() -> None:
    # Falls back to declared order; still valid Python.
    _parse_all(to_temporal_python(_design(), graph=None))


def _file(bundle, path: str) -> str:  # type: ignore[no-untyped-def]
    return next(f.content for f in bundle.files if f.path == path)


# --- Agent ------------------------------------------------------------------


async def test_agent_populates_state() -> None:
    from workflow_compiler.models import WorkflowState

    state = WorkflowState(document_text="doc")
    state.workflow_graph = _graph()
    state.temporal_design = _design()

    state = await TemporalCodeGeneratorAgent().run(state)

    assert state.temporal_code is not None
    assert state.temporal_code.package_name == "order_fulfillment"
    assert state.stage is CompilationStage.CODE_GENERATED
    assert state.confidence_scores is not None
    assert "temporal_code" in state.confidence_scores.notes


async def test_agent_requires_design() -> None:
    from workflow_compiler.models import WorkflowState

    with pytest.raises(CompilationError):
        await TemporalCodeGeneratorAgent().run(WorkflowState(document_text="doc"))


def test_default_post_approval_pipeline_includes_code_generator() -> None:
    compiler = WorkflowCompiler(llm_provider=MockProvider())
    agents = compiler._post_approval_agents
    assert any(isinstance(a, TemporalCodeGeneratorAgent) for a in agents)


def test_custom_generator_is_used() -> None:
    sentinel = TemporalPythonCodeGenerator()
    agent = TemporalCodeGeneratorAgent(generator=sentinel)
    assert agent._generator is sentinel
