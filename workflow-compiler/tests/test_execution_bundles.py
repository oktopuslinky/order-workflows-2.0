"""Locating and materializing the on-disk bundle a run executes.

The rule these tests pin down is the one the whole Run feature hangs on: runs
execute the files **on disk**, because §3 of ``RUN_WORKFLOWS_HANDOFF.md`` expects
the activity stubs to be replaced by hand. So materializing must never overwrite
— otherwise the second run of a workflow silently discards the user's real
implementation and executes placeholders again.
"""

from __future__ import annotations

from pathlib import Path

from workflow_compiler.execution import (
    bundle_dir,
    describe_runnable,
    is_materialized,
    materialize_bundle,
)
from workflow_compiler.models import (
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
