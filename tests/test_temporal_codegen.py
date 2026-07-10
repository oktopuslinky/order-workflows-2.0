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
    BindingSource,
    CompilationStage,
    InputBinding,
    NodeType,
    RetryPolicyDesign,
    StepKind,
    TemporalActivityDesign,
    TemporalChildWorkflowDesign,
    TemporalCompensationDesign,
    TemporalParam,
    TemporalQueryDesign,
    TemporalSignalDesign,
    TemporalStep,
    TemporalTimerDesign,
    TemporalWorkflowDesign,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


def _workflow_src(design: TemporalWorkflowDesign) -> str:
    """Render ``design`` and return the generated ``workflow.py`` source."""
    bundle = to_temporal_python(design)
    src = next(f.content for f in bundle.files if f.path == "workflow.py")
    ast.parse(src)  # generated code must always be syntactically valid
    return src


def test_compensation_registers_bound_input() -> None:
    """A compensation receives the id it must undo via its bindings."""
    design = TemporalWorkflowDesign(
        workflow_name="Pay",
        workflow_inputs=[TemporalParam(name="order_id")],
        activities=[
            TemporalActivityDesign(name="Charge", params=[TemporalParam(name="order_id")])
        ],
        compensation_activities=[
            TemporalCompensationDesign(
                name="Refund",
                compensates="Charge",
                params=[TemporalParam(name="charge_id")],
                bindings=[
                    InputBinding(
                        param="charge_id", source=BindingSource.STEP_OUTPUT, ref="charge"
                    )
                ],
            )
        ],
        plan=[
            TemporalStep(
                id="charge",
                kind=StepKind.ACTIVITY,
                ref="Charge",
                result_name="charge_id",
                bindings=[
                    InputBinding(
                        param="order_id", source=BindingSource.WORKFLOW_INPUT, ref="order_id"
                    )
                ],
            )
        ],
    )
    src = _workflow_src(design)
    # Bound, not an empty ``RefundInput()``.
    assert "compensations.append((refund, RefundInput(charge_id=charge_id)))" in src
    shared = next(f.content for f in to_temporal_python(design).files if f.path == "shared.py")
    assert "charge_id: str = " in shared


def test_parallel_lane_compensation_registered_and_results_captured() -> None:
    """Compensations inside a parallel group are registered; gather results captured."""
    design = TemporalWorkflowDesign(
        workflow_name="Fan",
        activities=[TemporalActivityDesign(name="A"), TemporalActivityDesign(name="B")],
        compensation_activities=[
            TemporalCompensationDesign(name="Rollback", compensates="A")
        ],
        plan=[
            TemporalStep(
                id="par",
                kind=StepKind.PARALLEL,
                lanes=[
                    [TemporalStep(id="a", kind=StepKind.ACTIVITY, ref="A")],
                    [TemporalStep(id="b", kind=StepKind.ACTIVITY, ref="B")],
                ],
            )
        ],
    )
    src = _workflow_src(design)
    # Results are assigned (no discarded gather → no NameError on later binds).
    assert "= await asyncio.gather(" in src
    # The parallel activity's compensation is registered (A2 regression).
    assert "compensations.append((rollback, RollbackInput()))" in src


def test_run_body_symbols_match_declarations_despite_casing() -> None:
    """A plan ref with different word boundaries resolves to the declared symbol.

    Regression for the camelCase/snake_case mismatch: declarations were built from
    the (slug-collapsed) activity name while the run body used the raw plan ref, so
    the workflow referenced undefined names. The body must reuse declared symbols.
    """
    design = TemporalWorkflowDesign(
        workflow_name="Demo",
        # Declaration name is collapsed (as the old agent slug produced)...
        activities=[TemporalActivityDesign(name="Validaterequestpayload")],
        # ...while the plan ref keeps proper word boundaries.
        plan=[TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="ValidateRequestPayload")],
    )
    src = _workflow_src(design)  # also asserts the source parses
    # The body uses the *declared* symbol, never a mismatched snake form.
    assert "validate_request_payload" not in src
    assert "validaterequestpayload," in src  # imported and called with one name
    assert "ValidaterequestpayloadInput()" in src
    # Steps are logged so a run shows what is executing.
    assert 'workflow.logger.info("Running step: Validaterequestpayload")' in src


def test_step_output_binding_resolves_by_activity_name() -> None:
    """A binding that names the producing activity resolves to its result variable."""
    design = TemporalWorkflowDesign(
        workflow_name="Pay",
        activities=[TemporalActivityDesign(name="PreAuth")],
        compensation_activities=[
            TemporalCompensationDesign(
                name="Release",
                compensates="PreAuth",
                params=[TemporalParam(name="auth_id")],
                bindings=[
                    InputBinding(
                        param="auth_id", source=BindingSource.STEP_OUTPUT, ref="PreAuth"
                    )
                ],
            )
        ],
        plan=[TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="PreAuth", result_name="auth_id")],
    )
    src = _workflow_src(design)  # also asserts it parses (no undefined-name surprises)
    assert "compensations.append((release, ReleaseInput(auth_id=auth_id)))" in src


def test_unresolved_step_output_binding_is_dropped() -> None:
    """A binding to a non-existent step is dropped — never an undefined ``<ref>_result``."""
    design = TemporalWorkflowDesign(
        workflow_name="Pay",
        activities=[TemporalActivityDesign(name="Do")],
        compensation_activities=[
            TemporalCompensationDesign(
                name="Undo",
                compensates="Do",
                params=[TemporalParam(name="ghost_id")],
                bindings=[
                    InputBinding(
                        param="ghost_id", source=BindingSource.STEP_OUTPUT, ref="NoSuchStep"
                    )
                ],
            )
        ],
        plan=[TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="Do")],
    )
    src = _workflow_src(design)
    assert "compensations.append((undo, UndoInput()))" in src
    assert "no_such_step_result" not in src


def test_activity_stub_returns_placeholder_not_raises() -> None:
    """Activity stubs return a typed placeholder so the bundle is runnable as-is."""
    design = TemporalWorkflowDesign(
        workflow_name="Demo",
        activities=[TemporalActivityDesign(name="Work", result_type="str")],
        plan=[TemporalStep(id="s1", kind=StepKind.ACTIVITY, ref="Work")],
    )
    acts = next(f.content for f in to_temporal_python(design).files if f.path == "activities.py")
    ast.parse(acts)
    assert "raise NotImplementedError" not in acts
    assert 'return ""' in acts


def test_rollback_loop_carries_retry_policy() -> None:
    """The saga rollback loop retries compensations using the default policy."""
    design = TemporalWorkflowDesign(
        workflow_name="Saga",
        default_retry_policy=RetryPolicyDesign(maximum_attempts=5),
        activities=[TemporalActivityDesign(name="Do")],
        compensation_activities=[TemporalCompensationDesign(name="Undo", compensates="Do")],
        plan=[TemporalStep(id="do", kind=StepKind.ACTIVITY, ref="Do")],
    )
    src = _workflow_src(design)
    _head, _sep, tail = src.partition("except Exception:")
    assert _sep, "expected a rollback except block"
    assert "for _comp_fn, _comp_arg in reversed(compensations):" in tail
    assert "retry_policy=RetryPolicy(" in tail
    assert "maximum_attempts=5" in tail


def test_signal_gate_bounded_by_matching_timer() -> None:
    """A signal gate paired with a declared timer waits with ``timeout=``."""
    design = TemporalWorkflowDesign(
        workflow_name="Fulfil",
        signals=[TemporalSignalDesign(name="carrier.picked_up")],
        timers=[
            TemporalTimerDesign(name="CarrierPickupTimeout", duration_seconds=43200),
            TemporalTimerDesign(name="RefundProcessingTimeout", duration_seconds=1800),
        ],
        plan=[
            TemporalStep(id="gate", kind=StepKind.SIGNAL_GATE, signal="carrier.picked_up")
        ],
    )
    src = _workflow_src(design)
    assert (
        "await workflow.wait_condition("
        "lambda: self._carrier_picked_up_received, timeout=CARRIER_PICKUP_TIMEOUT)" in src
    )


def test_signal_gate_explicit_timer_ref_wins() -> None:
    """A step's explicit ``timer`` ref outranks fuzzy name matching."""
    design = TemporalWorkflowDesign(
        workflow_name="Fulfil",
        signals=[TemporalSignalDesign(name="carrier.picked_up")],
        timers=[
            TemporalTimerDesign(name="CarrierPickupTimeout", duration_seconds=43200),
            TemporalTimerDesign(name="ShippingDeadline", duration_seconds=600),
        ],
        plan=[
            TemporalStep(
                id="gate",
                kind=StepKind.SIGNAL_GATE,
                signal="carrier.picked_up",
                timer="ShippingDeadline",
            )
        ],
    )
    src = _workflow_src(design)
    assert "timeout=SHIPPING_DEADLINE)" in src


def test_signal_gate_without_timer_stays_unbounded_with_todo() -> None:
    """No pairable timer → unbounded wait, flagged with an explicit TODO."""
    design = TemporalWorkflowDesign(
        workflow_name="Approve",
        signals=[TemporalSignalDesign(name="manager.approved")],
        plan=[
            TemporalStep(id="gate", kind=StepKind.SIGNAL_GATE, signal="manager.approved")
        ],
    )
    src = _workflow_src(design)
    assert "await workflow.wait_condition(lambda: self._manager_approved_received)" in src
    assert "TODO: pass timeout=" in src


def test_branch_predicate_resolves_to_step_result() -> None:
    """A simple predicate over a known result variable is emitted as code."""
    design = TemporalWorkflowDesign(
        workflow_name="Checkout",
        activities=[
            TemporalActivityDesign(name="ValidateCart"),
            TemporalActivityDesign(name="CreateOrder"),
        ],
        plan=[
            TemporalStep(
                id="v",
                kind=StepKind.ACTIVITY,
                ref="ValidateCart",
                result_name="eligibility",
            ),
            TemporalStep(
                id="b",
                kind=StepKind.BRANCH,
                predicate="eligibility == 'eligible'",
                lanes=[
                    [TemporalStep(id="c", kind=StepKind.ACTIVITY, ref="CreateOrder")],
                    [],
                ],
            ),
        ],
    )
    src = _workflow_src(design)
    assert "= eligibility == 'eligible'  # branch condition" in src
    assert "= True  # TODO: set from a real condition" not in src


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
        "test_stepthrough.py",
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
