"""HTTP contract for running generated bundles (RUN_WORKFLOWS_HANDOFF §5).

Driven against :class:`FakeExecutor`, so there is no Temporal server and no
subprocess. What is checked here is the contract the UI depends on — that
absent Temporal is *reported* rather than thrown at click time, that a run
executes the bundle on disk, that signals go out under their spec names, and
that a compensated saga is distinguishable from a failure.

The executor's own behaviour against a real server is not unit-testable and is
verified by actually running a bundle; see §5 of the design notes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import (
    get_compiler,
    get_executor,
    get_project_compiler,
)
from workflow_compiler.compiler import ReviewConfig
from workflow_compiler.config import get_settings
from workflow_compiler.execution import FakeExecutor
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.storage import InMemoryStateStore
from workflow_compiler.storage.project_store import InMemoryProjectStore
from workflow_compiler.storage.user_store import InMemoryUserStore

_NO_REVIEW = ReviewConfig(enabled=False)

_DOCUMENT = (
    "When an order is submitted, validate the order, reserve inventory, and "
    "ship the order. If the order is invalid, raise OrderInvalid. Release "
    "inventory compensates Reserve inventory. Inputs: order_id, customer_id."
)


class _Harness:
    def __init__(self, client: TestClient, executor: FakeExecutor, root: Path) -> None:
        self.client = client
        self.executor = executor
        self.root = root


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Harness]:
    provider = MockProvider(script_defaults=True)
    inner = WorkflowCompiler(
        llm_provider=provider, state_store=InMemoryStateStore(), review=_NO_REVIEW
    )
    compiler = ProjectCompiler(
        llm_provider=provider,
        workflow_compiler=inner,
        project_store=InMemoryProjectStore(),
        segmentation_review=False,
    )
    executor = FakeExecutor()
    # Bundles are written under a temp root, never the repo's ./generated.
    monkeypatch.setattr(get_settings(), "generated_root", str(tmp_path))

    app.dependency_overrides[get_project_compiler] = lambda: compiler
    app.dependency_overrides[get_compiler] = lambda: inner
    app.dependency_overrides[get_executor] = lambda: executor
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={
                "email": "runner@example.com",
                "password": "password123",
                "display_name": "Runner",
            },
        )
        yield _Harness(client, executor, tmp_path)
    app.dependency_overrides.clear()


def _approved_project(harness: _Harness) -> str:
    """Compile and approve, so the project has generated workflows to run."""
    compiled = harness.client.post("/projects/compile", json={"document_text": _DOCUMENT})
    assert compiled.status_code == 200
    project_id = str(compiled.json()["project"]["project_id"])

    approved = harness.client.post(
        f"/projects/{project_id}/approve", json={"accept_incomplete": True}
    )
    assert approved.status_code == 200, approved.text
    return project_id


def _slug(harness: _Harness, project_id: str) -> str:
    body = harness.client.get(f"/projects/{project_id}/runnable").json()
    runnable = [w for w in body["workflows"] if w["runnable"]]
    assert runnable, body
    return str(runnable[0]["slug"])


# --- availability -----------------------------------------------------------


def test_health_reports_temporal_reachability(harness: _Harness) -> None:
    body = harness.client.get("/health").json()

    assert body["temporal"]["reachable"] is True
    assert body["temporal"]["address"] == "fake:0"


def test_unreachable_temporal_is_reported_not_raised(harness: _Harness) -> None:
    """§5.4: a disabled control with a reason, never a click-time error."""
    harness.executor.reachable = False
    harness.executor.detail = "no Temporal server configured"
    project_id = _approved_project(harness)

    body = harness.client.get(f"/projects/{project_id}/runnable").json()

    assert body["temporal"]["reachable"] is False
    assert body["temporal"]["detail"] == "no Temporal server configured"
    # The workflows are still listed — it is Temporal that is missing, not them.
    assert body["workflows"]


def test_runnable_lists_input_fields_and_signals(harness: _Harness) -> None:
    project_id = _approved_project(harness)

    body = harness.client.get(f"/projects/{project_id}/runnable").json()
    workflow = next(w for w in body["workflows"] if w["runnable"])

    assert workflow["workflow_type"]
    assert workflow["task_queue"]
    # Every field carries the sample the generator puts in starter.py, so the
    # form's defaults and the bundle's own defaults cannot drift.
    assert all(field["sample"] for field in workflow["inputs"])


# --- starting ---------------------------------------------------------------


def test_start_run_executes_the_bundle_on_disk(harness: _Harness) -> None:
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)

    response = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug, "input": {}}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "running"
    assert body["bundle_written"], "the bundle should have been materialized"

    started = harness.executor.started[-1]
    assert Path(started.bundle_dir) == harness.root / project_id / slug
    assert (Path(started.bundle_dir) / "worker.py").is_file()


def test_a_second_run_keeps_hand_edited_activities(harness: _Harness) -> None:
    """The bundle is materialized once; the user's implementation then wins."""
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    harness.client.post(f"/projects/{project_id}/runs", json={"slug": slug})

    implemented = "# my real implementation\n"
    (harness.root / project_id / slug / "activities.py").write_text(
        implemented, encoding="utf-8"
    )
    second = harness.client.post(f"/projects/{project_id}/runs", json={"slug": slug})

    assert second.status_code == 200
    assert "activities.py" in second.json()["bundle_kept"]
    assert (harness.root / project_id / slug / "activities.py").read_text(
        encoding="utf-8"
    ) == implemented


def test_unknown_input_field_is_rejected_not_dropped(harness: _Harness) -> None:
    """Silently ignoring it would make the run look like it honored the input."""
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)

    response = harness.client.post(
        f"/projects/{project_id}/runs",
        json={"slug": slug, "input": {"not_a_field": "x"}},
    )

    assert response.status_code == 422
    assert "not_a_field" in response.json()["detail"]


def test_unknown_slug_is_404(harness: _Harness) -> None:
    project_id = _approved_project(harness)

    response = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": "no-such-workflow"}
    )

    assert response.status_code == 404


def test_starting_without_temporal_is_503_not_500(harness: _Harness) -> None:
    """A deployment precondition, not a bug in the request."""
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    harness.executor.reachable = False
    harness.executor.detail = "cannot reach a Temporal server"

    response = harness.client.post(f"/projects/{project_id}/runs", json={"slug": slug})

    assert response.status_code == 503
    assert "Temporal" in response.json()["detail"]


# --- observing, signalling, stopping ----------------------------------------


def test_get_run_reports_state_and_step_trail(harness: _Harness) -> None:
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    run_id = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug}
    ).json()["run_id"]
    harness.executor.state = "completed"
    harness.executor.result = "completed"

    body = harness.client.get(f"/runs/{run_id}").json()

    assert body["state"] == "completed"
    assert body["result"] == "completed"
    assert body["events"]


def test_a_compensated_saga_is_distinct_from_a_failure(harness: _Harness) -> None:
    """§8: a rolled-back run must be visibly different from a crashed one."""
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    run_id = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug}
    ).json()["run_id"]
    harness.executor.state = "compensated"

    assert harness.client.get(f"/runs/{run_id}").json()["state"] == "compensated"


def test_signal_goes_out_under_its_spec_name_with_one_arg_per_param(
    harness: _Harness,
) -> None:
    """Both halves of §6.2 / §2.1 in one assertion."""
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    run_id = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug}
    ).json()["run_id"]

    response = harness.client.post(
        f"/runs/{run_id}/signal",
        json={"name": "SLABreachAlert", "args": ["ORD-1", "carrier delay"]},
    )

    assert response.status_code == 200, response.text
    sent = harness.executor.signals[-1]
    assert sent.name == "SLABreachAlert"
    assert sent.args == ["ORD-1", "carrier delay"]


def test_terminate_stops_the_run(harness: _Harness) -> None:
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    run_id = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug}
    ).json()["run_id"]

    body = harness.client.delete(f"/runs/{run_id}").json()

    assert body["state"] == "terminated"
    assert harness.executor.terminated


def test_runs_are_listed_newest_first(harness: _Harness) -> None:
    project_id = _approved_project(harness)
    slug = _slug(harness, project_id)
    first = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug}
    ).json()["run_id"]
    second = harness.client.post(
        f"/projects/{project_id}/runs", json={"slug": slug}
    ).json()["run_id"]

    listed = harness.client.get(f"/projects/{project_id}/runs").json()

    assert [row["run_id"] for row in listed][:2] == [second, first]


def test_unknown_run_is_404(harness: _Harness) -> None:
    _approved_project(harness)

    assert harness.client.get("/runs/nope").status_code == 404
