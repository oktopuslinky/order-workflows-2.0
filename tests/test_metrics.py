"""Tests for the time-saved metric: pure computation + pipeline timing capture."""

from __future__ import annotations

import pytest

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.metrics import compute_time_saved
from workflow_compiler.models import CompilationProject
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore

_BASELINES = {
    "discovery": 6.0,
    "spec": 8.0,
    "validate": 3.0,
    "compile": 38.0,
    "edit": 4.0,
}

_DOCUMENT = (
    "When an order is submitted, validate the order, reserve inventory, and "
    "ship the order. Inputs: order_id, customer_id."
)

_EDIT_DOC = (
    "# Edit Request\n\n"
    "## Workflow: demo-order-workflow\n\n"
    "### Add\n\n"
    "- A business rule: refunds require manager approval.\n\n"
    "## Reason\n\nMetric test.\n"
)


def _compiler() -> ProjectCompiler:
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider,
        state_store=InMemoryStateStore(),
        review=ReviewConfig(enabled=False),
    )
    return ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
    )


def test_compute_time_saved_none_when_unmeasured() -> None:
    project = CompilationProject(document_text="doc")
    assert compute_time_saved(project, _BASELINES) is None


def test_compute_time_saved_exact_numbers() -> None:
    project = CompilationProject(document_text="doc")
    project.stage_timings = {
        "workflow-segmentation": 36.0,
        "extract:orders": 72.0,
        "validate:orders": 18.0,
        "compile:orders": 180.0,
        "edit:orders": 7.2,
    }
    report = compute_time_saved(project, _BASELINES)
    assert report is not None
    assert len(report.rows) == 5
    by_step = {row.step: row for row in report.rows}
    assert by_step["workflow-segmentation"].category == "discovery"
    assert by_step["extract:orders"].category == "spec"
    assert by_step["validate:orders"].category == "validate"
    assert by_step["compile:orders"].category == "compile"
    assert by_step["edit:orders"].category == "edit"
    assert by_step["compile:orders"].saved_hours == pytest.approx(38.0 - 180.0 / 3600)
    assert report.total_baseline_hours == pytest.approx(59.0)
    assert report.total_actual_seconds == pytest.approx(313.2)
    assert report.total_saved_hours == pytest.approx(59.0 - 313.2 / 3600)


async def test_compile_and_edit_record_stage_timings() -> None:
    compiler = _compiler()
    project = await compiler.compile_document(_DOCUMENT)

    stored = await compiler.load_project(project.project_id)
    assert "workflow-segmentation" in stored.stage_timings
    assert any(key.startswith("extract:") for key in stored.stage_timings)
    assert all(seconds >= 0.0 for seconds in stored.stage_timings.values())

    edited = await compiler.edit_specs(project.project_id, _EDIT_DOC)
    assert any(key.startswith("edit:") for key in edited.stage_timings)

    report = compute_time_saved(edited, _BASELINES)
    assert report is not None and report.total_saved_hours > 0


async def test_confirm_records_preview_timings() -> None:
    compiler = _compiler()
    project = await compiler.compile_document(_DOCUMENT)

    preview = await compiler.preview_edit(project.project_id, _EDIT_DOC)
    assert preview.resolved.timings  # the preview measured the LLM interpretation
    confirmed = await compiler.edit_specs(
        project.project_id, _EDIT_DOC, resolved=preview.resolved
    )
    for step, seconds in preview.resolved.timings.items():
        # The confirm persists the preview's measured seconds, not the ~0s replay.
        assert confirmed.stage_timings[step] == pytest.approx(seconds)
