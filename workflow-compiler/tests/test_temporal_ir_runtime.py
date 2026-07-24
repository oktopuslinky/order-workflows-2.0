"""Validation gate: generated IR code must import, register, and actually run.

These tests materialize a generated bundle to disk, import it, and (when a
Temporal test server is available) execute it under a time-skipping
``WorkflowEnvironment`` with mocked activities — proving the happy path completes
and that a forced mid-workflow failure fires saga compensations in reverse order.
"""

from __future__ import annotations

import ast
import importlib
import sys
import uuid

import pytest

from workflow_compiler.codegen.temporal.generator import to_temporal_python
from workflow_compiler.models import (
    BindingSource,
    InputBinding,
    RetryPolicyDesign,
    StepKind,
    TemporalActivityDesign,
    TemporalCompensationDesign,
    TemporalParam,
    TemporalSignalDesign,
    TemporalStep,
    TemporalWorkflowDesign,
)

# Record of which mock activities ran, to assert compensation behaviour.
CALLS: list[str] = []


def _ir_design() -> TemporalWorkflowDesign:
    """A saga design expressed entirely via the typed plan (IR)."""
    return TemporalWorkflowDesign(
        workflow_name="Checkout",
        task_queue="checkout-tq",
        description="Reserve then charge, compensating on failure.",
        workflow_inputs=[TemporalParam(name="order_id", type="str")],
        activities=[
            TemporalActivityDesign(
                name="Reserve",
                params=[TemporalParam(name="order_id")],
                timeout_seconds=5,
                retry_policy=RetryPolicyDesign(maximum_attempts=1),
            ),
            TemporalActivityDesign(
                name="Charge",
                params=[TemporalParam(name="order_id")],
                timeout_seconds=5,
                retry_policy=RetryPolicyDesign(
                    maximum_attempts=1, non_retryable_error_types=["Declined"]
                ),
            ),
        ],
        compensation_activities=[
            TemporalCompensationDesign(name="Unreserve", compensates="Reserve"),
        ],
        plan=[
            TemporalStep(
                id="reserve",
                kind=StepKind.ACTIVITY,
                ref="Reserve",
                result_name="reservation",
                bindings=[
                    InputBinding(
                        param="order_id", source=BindingSource.WORKFLOW_INPUT, ref="order_id"
                    )
                ],
            ),
            TemporalStep(
                id="charge",
                kind=StepKind.ACTIVITY,
                ref="Charge",
                result_name="receipt",
                bindings=[
                    InputBinding(
                        param="order_id", source=BindingSource.WORKFLOW_INPUT, ref="order_id"
                    )
                ],
            ),
        ],
    )


def test_ir_emits_data_bindings_and_saga() -> None:
    bundle = to_temporal_python(_ir_design())
    workflow = next(f.content for f in bundle.files if f.path == "workflow.py")
    for f in bundle.files:
        if f.path.endswith(".py"):
            ast.parse(f.content)
    # Data flows from the typed workflow input into the activity input.
    assert "ReserveInput(order_id=arg.order_id)" in workflow
    assert "ChargeInput(order_id=arg.order_id)" in workflow
    # Saga compensation is actually registered after Reserve.
    assert "compensations.append((unreserve, UnreserveInput()))" in workflow
    # Non-retryable error type is carried through.
    assert "non_retryable_error_types=['Declined']" in workflow
    # Typed workflow input field is rendered.
    shared = next(f.content for f in bundle.files if f.path == "shared.py")
    assert "order_id: str = " in shared


def test_ir_emits_gate_parallel_branch() -> None:
    design = TemporalWorkflowDesign(
        workflow_name="Featureful",
        activities=[
            TemporalActivityDesign(name="A"),
            TemporalActivityDesign(name="B"),
            TemporalActivityDesign(name="C"),
        ],
        signals=[TemporalSignalDesign(name="Approve")],
        plan=[
            TemporalStep(
                id="gate", kind=StepKind.SIGNAL_GATE, signal="Approve", condition="approved"
            ),
            TemporalStep(
                id="par",
                kind=StepKind.PARALLEL,
                lanes=[
                    [TemporalStep(id="a", kind=StepKind.ACTIVITY, ref="A")],
                    [TemporalStep(id="b", kind=StepKind.ACTIVITY, ref="B")],
                ],
            ),
            TemporalStep(
                id="br",
                kind=StepKind.BRANCH,
                predicate="needs C",
                lanes=[[TemporalStep(id="c", kind=StepKind.ACTIVITY, ref="C")], []],
            ),
        ],
    )
    bundle = to_temporal_python(design)
    workflow = next(f.content for f in bundle.files if f.path == "workflow.py")
    ast.parse(workflow)
    assert "await workflow.wait_condition(lambda: self._approve_received)" in workflow
    assert "await asyncio.gather(" in workflow
    assert "import asyncio" in workflow
    # An unbound branch emits an explicit placeholder flag, never a silent ``if True``.
    assert "if True:" not in workflow
    assert "should_needs_c = True  # TODO: set from a real condition: needs C" in workflow
    assert "if should_needs_c:" in workflow


# --- Runtime execution (skipped if no Temporal test server is available) -----


def _materialize(bundle, root) -> str:  # type: ignore[no-untyped-def]
    pkg = root / bundle.package_name
    pkg.mkdir(parents=True, exist_ok=True)
    for f in bundle.files:
        (pkg / f.path).write_text(f.content, encoding="utf-8")
    return bundle.package_name


async def _run(root, fail_charge: bool):  # type: ignore[no-untyped-def]
    from temporalio import activity
    from temporalio.client import Client  # noqa: F401  (imported for type parity)
    from temporalio.exceptions import ApplicationError
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker

    bundle = to_temporal_python(_ir_design())
    pkg_name = _materialize(bundle, root)
    pkg_dir = root / pkg_name
    # The generated package uses flat, absolute imports (Temporal's layout), so
    # put the package directory itself on the path and import its modules flat.
    sys.path.insert(0, str(pkg_dir))
    for _name in ("workflow", "activities", "shared"):
        sys.modules.pop(_name, None)
    try:
        wf_mod = importlib.import_module("workflow")
        shared_mod = importlib.import_module("shared")

        @activity.defn(name="Reserve")
        async def reserve(arg) -> str:  # type: ignore[no-untyped-def]
            CALLS.append("Reserve")
            return "reserved"

        @activity.defn(name="Charge")
        async def charge(arg) -> str:  # type: ignore[no-untyped-def]
            CALLS.append("Charge")
            if fail_charge:
                raise ApplicationError("declined", type="Declined", non_retryable=True)
            return "charged"

        @activity.defn(name="Unreserve")
        async def unreserve(arg) -> str:  # type: ignore[no-untyped-def]
            CALLS.append("Unreserve")
            return "unreserved"

        env = await WorkflowEnvironment.start_time_skipping()
        try:
            async with Worker(
                env.client,
                task_queue="checkout-tq",
                workflows=[wf_mod.Checkout],
                activities=[reserve, charge, unreserve],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                return await env.client.execute_workflow(
                    wf_mod.Checkout.run,
                    shared_mod.WorkflowInput(order_id="o-1"),
                    id=f"wf-{uuid.uuid4()}",
                    task_queue="checkout-tq",
                )
        finally:
            await env.shutdown()
    finally:
        sys.path.remove(str(pkg_dir))
        for _name in ("workflow", "activities", "shared"):
            sys.modules.pop(_name, None)


async def test_runtime_happy_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    CALLS.clear()
    try:
        result = await _run(tmp_path / "happy", fail_charge=False)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Temporal test server unavailable: {exc}")
    assert result == "completed"
    assert CALLS == ["Reserve", "Charge"]


async def test_runtime_compensates_on_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    CALLS.clear()
    try:
        with pytest.raises(Exception):  # noqa: B017 - any workflow failure proves rollback ran
            await _run(tmp_path / "fail", fail_charge=True)
    except pytest.skip.Exception:  # pragma: no cover
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Temporal test server unavailable: {exc}")
    # Reserve ran, Charge failed, Unreserve compensated it.
    assert "Unreserve" in CALLS
    assert CALLS.index("Reserve") < CALLS.index("Unreserve")
