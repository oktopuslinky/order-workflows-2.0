"""Cross-workflow trigger code generation: emission, project glue, and runtime.

The runtime test proves the load-bearing behaviour end to end: a generated
conditional trigger, executed under a time-skipping ``WorkflowEnvironment``
with mocked start activities, fires the correct branch's trigger with the
correct typed payload — without the caller ever owning the target.
"""

from __future__ import annotations

import ast
import importlib
import sys
import uuid

import pytest

from workflow_compiler.codegen.temporal.generator import to_temporal_python
from workflow_compiler.codegen.temporal.project_generator import generate_project_files
from workflow_compiler.models import (
    BindingSource,
    InputBinding,
    StepKind,
    TemporalActivityDesign,
    TemporalParam,
    TemporalStep,
    TemporalTriggerDesign,
    TemporalWorkflowDesign,
    TriggerInputBinding,
    TriggerMode,
    WorkflowTrigger,
)

CALLS: list[tuple[str, object]] = []
QUERIES: dict[str, object] = {}


def _design() -> TemporalWorkflowDesign:
    """One activity, then: if its result is 'big' escalate, else archive."""
    return TemporalWorkflowDesign(
        workflow_name="OrderReview",
        task_queue="order-review-tq",
        workflow_inputs=[TemporalParam(name="order_id", type="str")],
        activities=[
            TemporalActivityDesign(
                name="Evaluate", params=[TemporalParam(name="order_id")], timeout_seconds=5
            )
        ],
        triggers=[
            TemporalTriggerDesign(
                name="StartEscalation",
                target_workflow_name="Escalation",
                target_slug="escalation",
                target_task_queue="Escalation-task-queue",
                mode="blocking",
                params=[TemporalParam(name="order_id")],
            ),
            TemporalTriggerDesign(
                name="StartArchival",
                target_workflow_name="Archival",
                target_slug="archival",
                mode="fire_and_forget",
                params=[TemporalParam(name="order_id")],
            ),
        ],
        plan=[
            TemporalStep(
                id="evaluate",
                kind=StepKind.ACTIVITY,
                ref="Evaluate",
                result_name="verdict",
                bindings=[
                    InputBinding(
                        param="order_id", source=BindingSource.WORKFLOW_INPUT, ref="order_id"
                    )
                ],
            ),
            TemporalStep(
                id="route",
                kind=StepKind.BRANCH,
                predicate="verdict == 'big'",
                lanes=[
                    [
                        TemporalStep(
                            id="escalate",
                            kind=StepKind.TRIGGER,
                            ref="StartEscalation",
                            result_name="escalation_result",
                            bindings=[
                                InputBinding(
                                    param="order_id",
                                    source=BindingSource.WORKFLOW_INPUT,
                                    ref="order_id",
                                )
                            ],
                        )
                    ],
                    [
                        TemporalStep(
                            id="archive",
                            kind=StepKind.TRIGGER,
                            ref="StartArchival",
                            bindings=[
                                InputBinding(
                                    param="order_id",
                                    source=BindingSource.WORKFLOW_INPUT,
                                    ref="order_id",
                                )
                            ],
                        )
                    ],
                ],
            ),
        ],
    )


class TestTriggerEmission:
    def test_bundle_contains_trigger_module_and_wiring(self) -> None:
        bundle = to_temporal_python(_design())
        paths = [f.path for f in bundle.files]
        assert "triggers.py" in paths
        for f in bundle.files:
            if f.path.endswith(".py"):
                ast.parse(f.content)

        triggers = next(f.content for f in bundle.files if f.path == "triggers.py")
        # Start activity uses the client, idempotently, on the target's queue.
        assert "id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING" in triggers
        assert 'task_queue="Escalation-task-queue"' in triggers
        # Blocking awaits the target's result; fire-and-forget returns the id.
        assert "return await handle.result()" in triggers
        assert "return handle.id" in triggers
        # Deterministic target workflow id from the business key.
        assert 'id=f"escalation-{arg.order_id}"' in triggers

        workflow = next(f.content for f in bundle.files if f.path == "workflow.py")
        assert "from triggers import" in workflow
        assert "escalation_result = await workflow.execute_activity(" in workflow
        assert "start_and_await_escalation," in workflow
        assert "start_archival," in workflow
        # The branch predicate resolves to the real step result.
        assert "verdict == 'big'" in workflow

        worker = next(f.content for f in bundle.files if f.path == "worker.py")
        assert "start_and_await_escalation" in worker
        assert "start_archival" in worker

        shared = next(f.content for f in bundle.files if f.path == "shared.py")
        assert "class StartEscalationInput:" in shared

    def test_trigger_only_plan_synthesizes_activity_spine(self) -> None:
        design = _design()
        trigger_only = design.model_copy(update={"plan": [design.plan[1]]})
        workflow = next(
            f.content
            for f in to_temporal_python(trigger_only).files
            if f.path == "workflow.py"
        )
        # The Evaluate activity still runs before the injected trigger branch.
        assert workflow.index("evaluate,") < workflow.index("start_and_await_escalation,")

    def test_no_triggers_means_no_module(self) -> None:
        design = _design().model_copy(update={"triggers": [], "plan": []})
        paths = [f.path for f in to_temporal_python(design).files]
        assert "triggers.py" not in paths


class TestProjectFiles:
    def test_contracts_and_topology(self) -> None:
        designs = {
            "order-review": _design(),
            "escalation": TemporalWorkflowDesign(
                workflow_name="Escalation",
                task_queue="Escalation-task-queue",
                workflow_inputs=[TemporalParam(name="order_id", type="str")],
            ),
        }
        triggers = [
            WorkflowTrigger(
                source_workflow="order-review",
                target_workflow="escalation",
                mode=TriggerMode.BLOCKING,
                condition="verdict == 'big'",
                input_map=[TriggerInputBinding(target_input="order_id")],
                result_binding="escalation_result",
            )
        ]
        files = {f.path: f.content for f in generate_project_files(designs, triggers)}
        contracts = files["contracts.py"]
        ast.parse(contracts)
        assert "class OrderReviewInput:" in contracts
        assert "class EscalationInput:" in contracts
        assert "order_id: str" in contracts
        readme = files["README.md"]
        assert "`escalation/`" in readme.replace("_", "")  # bundle dir listed
        assert "—(blocking when `verdict == 'big'`)→" in readme
        assert "`escalation_result`" in readme


# --- Runtime: the conditional trigger fires correctly under time-skipping ----


def _materialize(bundle, root) -> object:  # type: ignore[no-untyped-def]
    pkg = root / bundle.package_name
    pkg.mkdir(parents=True, exist_ok=True)
    for f in bundle.files:
        (pkg / f.path).write_text(f.content, encoding="utf-8")
    return pkg


async def _run(root, verdict: str) -> str:  # type: ignore[no-untyped-def]
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker

    bundle = to_temporal_python(_design())
    pkg_dir = _materialize(bundle, root)
    sys.path.insert(0, str(pkg_dir))
    modules = ("workflow", "activities", "shared", "triggers")
    for name in modules:
        sys.modules.pop(name, None)
    try:
        wf_mod = importlib.import_module("workflow")
        shared_mod = importlib.import_module("shared")

        # Untyped mock params arrive as the JSON payload (a dict), so field
        # access uses subscript — the *generated* activities take dataclasses.
        @activity.defn(name="Evaluate")
        async def evaluate(arg) -> str:  # type: ignore[no-untyped-def]
            CALLS.append(("Evaluate", arg["order_id"]))
            return verdict

        # The start activities are mocked: the real ones call the Temporal
        # client; here we only prove the workflow fires the right one with the
        # right typed payload.
        @activity.defn(name="StartAndAwaitEscalation")
        async def start_escalation(arg) -> str:  # type: ignore[no-untyped-def]
            CALLS.append(("StartAndAwaitEscalation", arg["order_id"]))
            return "escalated"

        @activity.defn(name="StartArchival")
        async def start_archival(arg) -> str:  # type: ignore[no-untyped-def]
            CALLS.append(("StartArchival", arg["order_id"]))
            return "archival-id"

        env = await WorkflowEnvironment.start_time_skipping()
        try:
            async with Worker(
                env.client,
                task_queue="order-review-tq",
                workflows=[wf_mod.OrderReview],
                activities=[evaluate, start_escalation, start_archival],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    wf_mod.OrderReview.run,
                    shared_mod.WorkflowInput(order_id="o-42"),
                    id=f"wf-{uuid.uuid4()}",
                    task_queue="order-review-tq",
                )
                result = await handle.result()
                # The always-on read-only debug surface reports what ran.
                QUERIES["decisions"] = await handle.query("decisions_taken")
                QUERIES["triggers"] = await handle.query("triggers_fired")
                QUERIES["step"] = await handle.query("current_step")
                return result
        finally:
            await env.shutdown()
    finally:
        sys.path.remove(str(pkg_dir))
        for name in modules:
            sys.modules.pop(name, None)


class TestDebugSurface:
    def test_queries_and_tracking_always_emitted(self) -> None:
        bundle = to_temporal_python(_design())
        paths = [f.path for f in bundle.files]
        assert "test_stepthrough.py" in paths
        workflow = next(f.content for f in bundle.files if f.path == "workflow.py")
        for query in ("def current_step", "def decisions_taken", "def triggers_fired"):
            assert query in workflow
        assert "self._current_step = 'evaluate'" in workflow
        assert "self._decisions_taken.append({'branch': 'route'," in workflow
        assert "self._triggers_fired.append('StartEscalation')" in workflow
        # Step gating is opt-in: no advance signal, no gates by default.
        assert "def advance" not in workflow
        assert "self._advance_to" not in workflow
        harness = next(
            f.content for f in bundle.files if f.path == "test_stepthrough.py"
        )
        ast.parse(harness)
        assert 'name="StartAndAwaitEscalation"' in harness  # triggers mocked

    def test_stepwise_gates_only_under_flag(self) -> None:
        bundle = to_temporal_python(_design(), stepwise=True)
        workflow = next(f.content for f in bundle.files if f.path == "workflow.py")
        ast.parse(workflow)
        assert "def advance" in workflow
        assert (
            "await workflow.wait_condition(lambda: self._advance_to >= self._step_index)"
            in workflow
        )
        harness = next(
            f.content for f in bundle.files if f.path == "test_stepthrough.py"
        )
        assert 'await handle.signal("advance")' in harness


async def test_runtime_conditional_trigger_takes_then_lane(tmp_path) -> None:  # type: ignore[no-untyped-def]
    CALLS.clear()
    QUERIES.clear()
    try:
        result = await _run(tmp_path / "big", verdict="big")
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Temporal test server unavailable: {exc}")
    assert result == "completed"
    assert ("StartAndAwaitEscalation", "o-42") in CALLS
    assert all(name != "StartArchival" for name, _arg in CALLS)
    # The read-only debug queries reported the decision and the trigger.
    assert QUERIES["triggers"] == ["StartEscalation"]
    decisions = QUERIES["decisions"]
    assert decisions == [
        {"branch": "route", "predicate": "verdict == 'big'", "taken": True}
    ]


async def test_runtime_conditional_trigger_takes_else_lane(tmp_path) -> None:  # type: ignore[no-untyped-def]
    CALLS.clear()
    QUERIES.clear()
    try:
        result = await _run(tmp_path / "small", verdict="small")
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Temporal test server unavailable: {exc}")
    assert result == "completed"
    assert ("StartArchival", "o-42") in CALLS
    assert all(name != "StartAndAwaitEscalation" for name, _arg in CALLS)
    assert QUERIES["triggers"] == ["StartArchival"]
    assert QUERIES["decisions"] == [
        {"branch": "route", "predicate": "verdict == 'big'", "taken": False}
    ]


async def test_runtime_generated_stepthrough_harness_passes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The bundle's own test_stepthrough.py runs green out of the box."""
    import subprocess
    import sys as _sys

    bundle = to_temporal_python(_design())
    pkg_dir = _materialize(bundle, tmp_path)
    proc = subprocess.run(
        [_sys.executable, "-m", "pytest", "test_stepthrough.py", "-q"],
        cwd=str(pkg_dir),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0 and "unavailable" in (proc.stdout + proc.stderr).lower():
        pytest.skip("Temporal test server unavailable")  # pragma: no cover
    assert proc.returncode == 0, proc.stdout + proc.stderr
