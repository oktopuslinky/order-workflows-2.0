"""In-process background jobs for the long-running project stages.

``validate`` and ``approve`` each take a fresh copy of the project, mutate it in
memory, and persist **only at the very end** (see
:meth:`ProjectCompiler.validate_specs` / :meth:`ProjectCompiler.approve_spec`).
That single property is what makes background execution with true cancellation
cheap and safe:

* **Background:** the stage runs as an :class:`asyncio.Task`, so the HTTP request
  that starts it returns immediately. The task keeps running even after the
  client navigates away or closes the tab — the frontend rediscovers it via
  ``GET /jobs`` on the next page load.
* **Cancel + rollback:** cancelling calls :meth:`asyncio.Task.cancel`, which
  raises :class:`asyncio.CancelledError` at the next ``await`` (an LLM call). The
  final ``save`` never runs, so the project on disk is byte-for-byte what it was
  before the run started — "keep what was already there" for free, no rollback
  bookkeeping. (An interrupted ``approve`` may leave orphan per-workflow states
  in the state store, but the *project* record never references them, so at the
  project level nothing changed.)

Concurrency rule: **at most one active run per project** (starting a second run
on a project that is already running raises :class:`JobConflictError`), but any
number of *different* projects may run at once. Two runs on the same project
would race on the same persisted file and make cancellation ambiguous; two runs
on different projects share no state.

Jobs live only in memory: a server restart drops in-flight runs. That is
acceptable — an interrupted LLM call cannot be resumed anyway, and because
nothing was persisted the project simply stays in its pre-run state. The
frontend treats a vanished job as "ended" and refetches the project.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

JobKind = Literal["validate", "approve"]
JobStatus = Literal["running", "succeeded", "failed", "canceled"]

#: How long a finished job is retained so the UI can read its terminal state
#: (status + any error) before it is pruned.
_RETENTION_SECONDS = 600.0


def _now() -> datetime:
    return datetime.now(UTC)


class JobConflictError(Exception):
    """A run is already in flight for this project (one active run per project)."""

    def __init__(self, project_id: str, job_id: str) -> None:
        super().__init__(f"A run is already in progress for project {project_id!r}.")
        self.project_id = project_id
        self.job_id = job_id


@dataclass
class Job:
    """One background run of a project stage."""

    job_id: str
    project_id: str
    kind: JobKind
    owner_id: str | None
    status: JobStatus = "running"
    error: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    # The running task — never serialized; ``None`` once terminal.
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def active(self) -> bool:
        return self.status == "running"


class JobManager:
    """Registry of background jobs, one instance per app.

    Purely an executor: it runs whatever coroutine the endpoint hands it, so the
    dependency-injected (possibly mock) compiler is what actually does the work.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    def _prune(self) -> None:
        """Drop terminal jobs older than the retention window."""
        cutoff = _now().timestamp() - _RETENTION_SECONDS
        for jid in [
            jid
            for jid, job in self._jobs.items()
            if not job.active and job.updated_at.timestamp() < cutoff
        ]:
            self._jobs.pop(jid, None)

    def active_for_project(self, project_id: str) -> Job | None:
        """The in-flight run for ``project_id``, if any."""
        return next(
            (j for j in self._jobs.values() if j.project_id == project_id and j.active),
            None,
        )

    async def start(
        self,
        *,
        project_id: str,
        kind: JobKind,
        owner_id: str | None,
        run: Callable[[], Awaitable[object]],
    ) -> Job:
        """Register and launch a run. Raises :class:`JobConflictError` if the
        project already has one in flight.

        ``run`` is a zero-argument factory that returns the stage coroutine when
        called (so the coroutine is created inside the task, not before)."""
        async with self._lock:
            self._prune()
            existing = self.active_for_project(project_id)
            if existing is not None:
                raise JobConflictError(project_id, existing.job_id)
            job = Job(
                job_id=uuid.uuid4().hex,
                project_id=project_id,
                kind=kind,
                owner_id=owner_id,
            )
            self._jobs[job.job_id] = job
            job.task = asyncio.create_task(self._run(job, run))
            return job

    @staticmethod
    async def _run(job: Job, run: Callable[[], Awaitable[object]]) -> None:
        """Execute the stage and record the terminal status.

        Cancellation is swallowed on purpose: it is a normal terminal outcome for
        a background job, and nothing was persisted, so there is nothing to undo.
        """
        try:
            await run()
            job.status = "succeeded"
        except asyncio.CancelledError:
            job.status = "canceled"
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc) or exc.__class__.__name__
        finally:
            job.task = None
            job.updated_at = _now()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(
        self, *, owner_id: str | None, project_id: str | None = None
    ) -> list[Job]:
        """Jobs visible to a caller, newest first.

        ``owner_id=None`` returns every job (used when projects are shared, to
        mirror project visibility); otherwise only that owner's jobs."""
        self._prune()
        jobs = [
            j
            for j in self._jobs.values()
            if (owner_id is None or j.owner_id == owner_id)
            and (project_id is None or j.project_id == project_id)
        ]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    async def cancel(self, job_id: str) -> Job | None:
        """Cancel a running job and wait for it to settle. No-op if terminal."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        task = job.task
        if job.active and task is not None:
            task.cancel()
            # Let the task observe the cancellation and record "canceled".
            # _run swallows CancelledError, so awaiting it will not re-raise, but
            # guard both outcomes defensively.
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        return job
