"""Tests for background validate/approve runs (JobManager + job endpoints).

Two layers:

* :class:`JobManager` unit tests drive cancellation deterministically with a
  coroutine that blocks on an event, proving a canceled run stops before its
  later work (the final ``save``) can run — the basis of "keep what was already
  there".
* API tests exercise the real endpoints against the mock provider: start a run,
  poll it to completion, and confirm the project advanced.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from workflow_compiler import ProjectCompiler, WorkflowCompiler
from workflow_compiler.api.app import app
from workflow_compiler.api.auth import get_user_store
from workflow_compiler.api.dependencies import get_compiler, get_project_compiler
from workflow_compiler.api.jobs import JobConflictError, JobManager
from workflow_compiler.compiler import ReviewConfig
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


# --------------------------------------------------------------------------- #
# JobManager unit tests (no HTTP): cancellation + rollback semantics
# --------------------------------------------------------------------------- #


def test_cancel_stops_before_later_work_and_frees_the_project() -> None:
    """A canceled run is marked ``canceled`` and never runs the code after the
    await it was suspended on — the same await point at which a real run would
    otherwise reach its final ``save``."""

    async def scenario() -> None:
        mgr = JobManager()
        started = asyncio.Event()
        release = asyncio.Event()
        reached_end = False

        async def work() -> None:
            nonlocal reached_end
            started.set()
            await release.wait()  # cancellation lands here, like an LLM await
            reached_end = True  # stands in for "persist the result"

        job = await mgr.start(
            project_id="p1", kind="validate", owner_id="u1", run=lambda: work()
        )
        await started.wait()

        # A second run on the same project is refused while one is in flight.
        with pytest.raises(JobConflictError):
            await mgr.start(
                project_id="p1", kind="validate", owner_id="u1", run=lambda: work()
            )

        settled = await mgr.cancel(job.job_id)
        assert settled is not None
        assert settled.status == "canceled"
        assert reached_end is False  # nothing past the await ran → nothing persisted

        # The project is free again once the run settles.
        job2 = await mgr.start(
            project_id="p1", kind="approve", owner_id="u1", run=lambda: work()
        )
        assert job2.active
        await mgr.cancel(job2.job_id)

    asyncio.run(scenario())


def test_successful_run_is_recorded() -> None:
    async def scenario() -> None:
        mgr = JobManager()
        ran = asyncio.Event()

        async def work() -> None:
            ran.set()

        job = await mgr.start(
            project_id="p2", kind="validate", owner_id="u1", run=lambda: work()
        )
        task = job.task
        assert task is not None
        await task
        assert job.status == "succeeded"
        assert ran.is_set()

    asyncio.run(scenario())


def test_failed_run_captures_the_error() -> None:
    async def scenario() -> None:
        mgr = JobManager()

        async def work() -> None:
            raise ValueError("boom")

        job = await mgr.start(
            project_id="p3", kind="approve", owner_id="u1", run=lambda: work()
        )
        task = job.task
        assert task is not None
        await task
        assert job.status == "failed"
        assert job.error == "boom"

    asyncio.run(scenario())


def test_list_filters_by_owner_and_project() -> None:
    async def scenario() -> None:
        mgr = JobManager()

        async def noop() -> None:
            return None

        a = await mgr.start(project_id="pa", kind="validate", owner_id="u1", run=lambda: noop())
        b = await mgr.start(project_id="pb", kind="validate", owner_id="u2", run=lambda: noop())
        for job in (a, b):
            task = job.task
            if task is not None:
                await task

        assert {j.job_id for j in mgr.list(owner_id=None)} == {a.job_id, b.job_id}
        assert {j.job_id for j in mgr.list(owner_id="u1")} == {a.job_id}
        assert {j.job_id for j in mgr.list(owner_id=None, project_id="pb")} == {b.job_id}

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# API tests: the real endpoints against the mock provider
# --------------------------------------------------------------------------- #


@pytest.fixture
def client() -> TestClient:
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
    app.dependency_overrides[get_project_compiler] = lambda: compiler
    app.dependency_overrides[get_compiler] = lambda: inner
    users = InMemoryUserStore()
    app.dependency_overrides[get_user_store] = lambda: users
    with TestClient(app) as test_client:
        test_client.post(
            "/auth/register",
            json={
                "email": "tester@example.com",
                "password": "password123",
                "display_name": "Tester",
            },
        )
        yield test_client
    app.dependency_overrides.clear()


def _poll(client: TestClient, job_id: str, timeout: float = 15.0) -> dict:
    """Poll a job to a terminal state (the background task runs on the portal
    loop while ``time.sleep`` yields this thread)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def _compile(client: TestClient) -> str:
    compiled = client.post("/projects/compile", json={"document_text": _DOCUMENT})
    assert compiled.status_code == 200, compiled.text
    return compiled.json()["project"]["project_id"]


def test_background_validate_then_approve(client: TestClient) -> None:
    project_id = _compile(client)

    started = client.post(
        f"/projects/{project_id}/jobs", json={"kind": "validate", "spec_markdown": {}}
    )
    assert started.status_code == 202, started.text
    start_body = started.json()
    assert start_body["kind"] == "validate"
    assert start_body["status"] in {"running", "succeeded"}

    done = _poll(client, start_body["job_id"])
    assert done["status"] == "succeeded"
    # The finished project is embedded, already advanced past the gate.
    assert done["project"]["project"]["stage"] == "spec_validated"

    approved = client.post(
        f"/projects/{project_id}/jobs",
        json={"kind": "approve", "accept_incomplete": True},
    )
    assert approved.status_code == 202, approved.text
    final = _poll(client, approved.json()["job_id"])
    assert final["status"] == "succeeded"
    project = final["project"]["project"]
    assert project["stage"] == "completed"
    assert project["workflow_ids"]


def test_jobs_list_reports_the_run(client: TestClient) -> None:
    project_id = _compile(client)
    started = client.post(
        f"/projects/{project_id}/jobs", json={"kind": "validate", "spec_markdown": {}}
    )
    job_id = started.json()["job_id"]
    _poll(client, job_id)

    listed = client.get("/jobs")
    assert listed.status_code == 200
    ids = {j["job_id"] for j in listed.json()}
    assert job_id in ids

    scoped = client.get("/jobs", params={"project_id": project_id})
    # The filter is by project, not "only the jobs this test started": a cloud
    # provider (the default) chains a speculative `predraft` run off a successful
    # validate, so the list legitimately holds it too.
    scoped_jobs = scoped.json()
    assert job_id in {j["job_id"] for j in scoped_jobs}
    assert {j["project_id"] for j in scoped_jobs} == {project_id}
    assert {j["kind"] for j in scoped_jobs} <= {"validate", "predraft"}


def test_cancel_finished_job_is_a_no_op(client: TestClient) -> None:
    project_id = _compile(client)
    started = client.post(
        f"/projects/{project_id}/jobs", json={"kind": "validate", "spec_markdown": {}}
    )
    job_id = started.json()["job_id"]
    _poll(client, job_id)

    canceled = client.post(f"/jobs/{job_id}/cancel")
    assert canceled.status_code == 200
    # Already succeeded — cancel does not rewrite a finished run.
    assert canceled.json()["status"] == "succeeded"


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/jobs/nope").status_code == 404
    assert client.post("/jobs/nope/cancel").status_code == 404


# --------------------------------------------------------------------------- #
# Speculative runs: background question drafting must never obstruct the user
# --------------------------------------------------------------------------- #


def test_a_speculative_run_yields_to_real_work_rather_than_blocking_it() -> None:
    """Pre-drafting is a nicety. It must never answer a user's click with a 409.

    Starting real work on a project cancels an in-flight speculative run instead
    of being refused by it, and because nothing is persisted until a run
    finishes, that discards work in progress and no state.
    """

    async def scenario() -> None:
        mgr = JobManager()
        started = asyncio.Event()
        release = asyncio.Event()
        reached_end = False

        async def drafting() -> None:
            nonlocal reached_end
            started.set()
            await release.wait()  # cancellation lands here, like an LLM await
            reached_end = True  # stands in for "persist the agenda"

        speculative = await mgr.start(
            project_id="p1", kind="predraft", owner_id="u1", run=lambda: drafting()
        )
        await started.wait()

        # Real work is admitted, not refused.
        real = await mgr.start(
            project_id="p1", kind="validate", owner_id="u1", run=lambda: asyncio.sleep(0)
        )

        assert speculative.status == "canceled"
        assert not reached_end, "the cancelled draft must not have persisted anything"
        assert real.active or real.status == "succeeded"
        release.set()

    asyncio.run(scenario())


def test_a_speculative_run_is_refused_while_anything_is_in_flight() -> None:
    """It is not worth contending for the project — a later call will retry."""

    async def scenario() -> None:
        mgr = JobManager()
        started = asyncio.Event()
        release = asyncio.Event()

        async def work() -> None:
            started.set()
            await release.wait()

        await mgr.start(
            project_id="p1", kind="validate", owner_id="u1", run=lambda: work()
        )
        await started.wait()

        with pytest.raises(JobConflictError):
            await mgr.start(
                project_id="p1", kind="predraft", owner_id="u1", run=lambda: work()
            )

        release.set()

    asyncio.run(scenario())


def test_two_speculative_runs_do_not_stack_on_one_project() -> None:
    async def scenario() -> None:
        mgr = JobManager()
        started = asyncio.Event()
        release = asyncio.Event()

        async def work() -> None:
            started.set()
            await release.wait()

        await mgr.start(
            project_id="p1", kind="predraft", owner_id="u1", run=lambda: work()
        )
        await started.wait()

        with pytest.raises(JobConflictError):
            await mgr.start(
                project_id="p1", kind="predraft", owner_id="u1", run=lambda: work()
            )

        release.set()

    asyncio.run(scenario())


def test_the_after_hook_runs_once_the_job_is_no_longer_active() -> None:
    """Chaining a follow-on job is the whole point: it must not collide with the
    job that is calling it, and its failure must not fail that job."""

    async def scenario() -> None:
        mgr = JobManager()
        chained: list[str] = []

        async def follow_on() -> None:
            # A speculative start here would be refused if the calling job were
            # still active — this is exactly the validate → predraft chain.
            job = await mgr.start(
                project_id="p1",
                kind="predraft",
                owner_id="u1",
                run=lambda: asyncio.sleep(0),
            )
            chained.append(job.kind)

        job = await mgr.start(
            project_id="p1",
            kind="validate",
            owner_id="u1",
            run=lambda: asyncio.sleep(0),
            after=follow_on,
        )
        assert job.task is not None
        await job.task

        assert job.status == "succeeded"
        assert chained == ["predraft"]

    asyncio.run(scenario())


def test_the_after_hook_is_skipped_when_the_job_failed() -> None:
    async def scenario() -> None:
        mgr = JobManager()
        ran: list[str] = []

        async def boom() -> None:
            raise RuntimeError("stage blew up")

        async def follow_on() -> None:
            ran.append("after")

        job = await mgr.start(
            project_id="p1",
            kind="validate",
            owner_id="u1",
            run=lambda: boom(),
            after=follow_on,
        )
        assert job.task is not None
        await job.task

        assert job.status == "failed"
        assert ran == []

    asyncio.run(scenario())


def test_a_failing_after_hook_does_not_fail_the_job() -> None:
    """The stage the user asked for did succeed; a warm-up failure is not theirs."""

    async def scenario() -> None:
        mgr = JobManager()

        async def boom() -> None:
            raise RuntimeError("drafting blew up")

        job = await mgr.start(
            project_id="p1",
            kind="validate",
            owner_id="u1",
            run=lambda: asyncio.sleep(0),
            after=boom,
        )
        assert job.task is not None
        await job.task

        assert job.status == "succeeded"
        assert job.error is None

    asyncio.run(scenario())
