"""Locating and materializing the on-disk bundle a run executes.

The rule these tests pin down is the one the whole Run feature hangs on: runs
execute the files **on disk**, because §3 of ``RUN_WORKFLOWS_HANDOFF.md`` expects
the activity stubs to be replaced by hand. So materializing must never overwrite
— otherwise the second run of a workflow silently discards the user's real
implementation and executes placeholders again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_compiler.execution import (
    bundle_dir,
    describe_runnable,
    is_materialized,
    materialize_bundle,
)
from workflow_compiler.execution.bundles import (
    LEGACY_WORKER_ADDRESS,
    worker_honors_address,
)
from workflow_compiler.execution.workers import WorkerPool
from workflow_compiler.interfaces.executor import ExecutorUnavailableError
from workflow_compiler.models import (
    GeneratedFile,
    TemporalCodeBundle,
    TemporalParam,
    TemporalQueryDesign,
    TemporalSignalDesign,
    TemporalWorkflowDesign,
    WorkflowState,
)


def _design() -> TemporalWorkflowDesign:
    return TemporalWorkflowDesign(
        workflow_name="OrderFulfillmentWorkflow",
        workflow_inputs=[
            TemporalParam(name="order_id", type="str"),
            TemporalParam(name="line_items", type="list"),
        ],
        signals=[
            TemporalSignalDesign(name="SLABreachAlert", payload=["order_id", "delay_reason"])
        ],
        queries=[TemporalQueryDesign(name="OrderStatus", returns="str")],
    )


def _state() -> WorkflowState:
    return WorkflowState(
        workflow_id="wf-1",
        document_text="irrelevant",
        temporal_design=_design(),
    )


def test_bundle_dir_is_project_then_slug(tmp_path: Path) -> None:
    assert bundle_dir(tmp_path, "proj-1", "order-fulfillment") == (
        tmp_path / "proj-1" / "order-fulfillment"
    )


def test_materialize_writes_a_runnable_bundle(tmp_path: Path) -> None:
    result = materialize_bundle(_state(), tmp_path / "b")

    assert is_materialized(result.directory)
    assert result.created
    for required in ("worker.py", "workflow.py", "activities.py", "shared.py"):
        assert required in result.written


def test_materialize_never_overwrites_a_hand_edited_file(tmp_path: Path) -> None:
    """The whole reason runs execute from disk: the user's code must survive."""
    directory = tmp_path / "b"
    materialize_bundle(_state(), directory)
    implemented = "# my real implementation\n"
    (directory / "activities.py").write_text(implemented, encoding="utf-8")

    second = materialize_bundle(_state(), directory)

    assert (directory / "activities.py").read_text(encoding="utf-8") == implemented
    assert "activities.py" in second.kept
    assert "activities.py" not in second.written


def test_materialize_rerenders_rather_than_replaying_stored_code(tmp_path: Path) -> None:
    """Stored ``temporal_code`` is whatever codegen produced at approve time.

    Handoff §6 records that every bundle generated before 2026-08-12 carries
    real defects, so writing the stored copy to disk resurrects fixed bugs in
    code the user is about to run. Caught for real: the stored worker.py
    predated TEMPORAL_ADDRESS support, so the worker silently connected to a
    different server and the execution's first workflow task was never polled.
    """
    state = _state()
    state.temporal_code = TemporalCodeBundle(
        package_name="order_fulfillment_workflow",
        files=[GeneratedFile(path="worker.py", content="# stale, from an old codegen\n")],
    )

    materialize_bundle(state, tmp_path / "b")

    worker = (tmp_path / "b" / "worker.py").read_text(encoding="utf-8")
    assert "stale" not in worker
    assert 'os.environ.get("TEMPORAL_ADDRESS"' in worker


async def test_a_bundle_that_ignores_temporal_address_is_refused(tmp_path: Path) -> None:
    """The worst failure mode this feature has: a stale worker.py connects to a
    hardcoded localhost:7233, serves a *different* server, and the run sits in
    `running` forever because nothing polls its queue. Materialization
    re-renders, so this only reaches a directory that was already on disk — an
    old `approve-spec --out-dir`, or an unzipped download.
    """
    directory = tmp_path / "old-bundle"
    directory.mkdir()
    for name in ("workflow.py", "activities.py", "shared.py"):
        (directory / name).write_text("# placeholder\n", encoding="utf-8")
    (directory / "worker.py").write_text(
        'client = await Client.connect("localhost:7233")\n', encoding="utf-8"
    )
    assert not worker_honors_address(directory)

    pool = WorkerPool(address="localhost:7234")
    with pytest.raises(ExecutorUnavailableError) as caught:
        await pool.ensure(bundle_dir=str(directory), task_queue="q")

    message = str(caught.value)
    assert "TEMPORAL_ADDRESS" in message
    assert "localhost:7234" in message
    # The message has to say what to actually do about it.
    assert "Delete the directory" in message


async def test_a_stale_bundle_is_allowed_when_the_address_matches_anyway(
    tmp_path: Path,
) -> None:
    """Only the genuinely broken combination is blocked. A bundle hardcoding the
    address the app is configured with connects to the right place regardless,
    so refusing it would be gratuitous."""
    directory = tmp_path / "old-bundle"
    materialize_bundle(_state(), directory)
    (directory / "worker.py").write_text(
        'client = await Client.connect("localhost:7233")\n', encoding="utf-8"
    )

    pool = WorkerPool(address=LEGACY_WORKER_ADDRESS)
    # Spawning is what would fail; the address guard must not be what stops it.
    try:
        await pool.ensure(bundle_dir=str(directory), task_queue="q")
    except ExecutorUnavailableError as exc:
        assert "TEMPORAL_ADDRESS" not in str(exc)
    finally:
        await pool.shutdown()


def test_describe_runnable_exposes_form_fields_with_sample_defaults(tmp_path: Path) -> None:
    runnable = describe_runnable(
        slug="order-fulfillment", state=_state(), root=tmp_path, project_id="proj-1"
    )

    samples = {f.name: f.sample for f in runnable.inputs}
    assert samples == {"order_id": '"ORD-1"', "line_items": "[]"}
    assert runnable.workflow_type == "OrderFulfillmentWorkflow"
    assert runnable.task_queue == "order_fulfillment_workflow-task-queue"


def test_describe_runnable_names_signals_as_the_spec_does(tmp_path: Path) -> None:
    """Not the snake_cased method — signalling that name does nothing (§6.2)."""
    runnable = describe_runnable(
        slug="order-fulfillment", state=_state(), root=tmp_path, project_id="proj-1"
    )

    assert [(s.name, s.params) for s in runnable.signals] == [
        ("SLABreachAlert", ["order_id", "delay_reason"])
    ]


def test_a_workflow_that_never_reached_codegen_is_not_runnable(tmp_path: Path) -> None:
    """A disabled control, not a click-time failure (§5.4)."""
    state = WorkflowState(workflow_id="wf-2", document_text="irrelevant")

    runnable = describe_runnable(
        slug="never-compiled", state=state, root=tmp_path, project_id="proj-1"
    )

    assert not runnable.runnable
    assert runnable.bundle_dir is None
