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

Concurrency rule: **at most one active run per scope** (starting a second run
on a project that is already running raises :class:`JobConflictError`), but any
number of *different* scopes may run at once. A scope is the thing a job
belongs to — a project (``scope_kind="project"``) or a knowledge base
(``scope_kind="knowledge_base"``, kind ``kb_ingest``); ``project_id`` is kept as
an alias of ``scope_id`` so existing callers and the frontend poller are
unchanged. Two runs on the same project
would race on the same persisted file and make cancellation ambiguous; two runs
on different projects share no state.

Jobs live only in memory: a server restart drops in-flight runs. That is
acceptable — an interrupted LLM call cannot be resumed anyway, and because
nothing was persisted the project simply stays in its pre-run state. The
frontend treats a vanished job as "ended" and refetches the project.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

JobKind = Literal["validate", "approve", "predraft", "kb_ingest"]
JobStatus = Literal["running", "succeeded", "failed", "canceled"]
ScopeKind = Literal["project", "knowledge_base"]

#: Speculative work: started by the system rather than the user, and never worth
#: making the user wait for. It is exempt from the one-run-per-project rule and
#: is cancelled the instant real work arrives for the same project (see
#: :meth:`JobManager.start`).
_SPECULATIVE: frozenset[str] = frozenset({"predraft"})

#: How long a finished job is retained so the UI can read its terminal state
#: (status + any error) before it is pruned.
_RETENTION_SECONDS = 600.0


def _now() -> datetime:
    return datetime.now(UTC)


class JobConflictError(Exception):
    """A run is already in flight for this scope (one active run per scope)."""

    def __init__(self, scope_id: str, job_id: str, scope_kind: ScopeKind = "project") -> None:
        noun = "project" if scope_kind == "project" else "knowledge base"
        super().__init__(f"A run is already in progress for {noun} {scope_id!r}.")
        self.project_id = scope_id
        self.scope_id = scope_id
        self.scope_kind = scope_kind
        self.job_id = job_id


@dataclass
class JobProgress:
    """Mutable progress a long run reports while it is running.

    Shared by reference between the job and the coroutine doing the work: the
    worker calls :meth:`update` (safe from a thread — plain attribute writes),
    the job endpoint reads it. ``total == 0`` means "indeterminate".
    """

    message: str = ""
    done: int = 0
    total: int = 0

    def update(self, message: str, done: int = 0, total: int = 0) -> None:
        self.message = message
        self.done = done
        self.total = total


@dataclass
class Job:
    """One background run of a project stage or a knowledge-base ingest."""

    job_id: str
    scope_id: str
    kind: JobKind
    owner_id: str | None
    scope_kind: ScopeKind = "project"
    status: JobStatus = "running"
    error: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    progress: JobProgress | None = None
    # The running task — never serialized; ``None`` once terminal.
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def project_id(self) -> str:
        """Alias of ``scope_id`` (every job used to be a project job)."""
        return self.scope_id

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

    def active_for_project(
        self, project_id: str, *, speculative: bool | None = None
    ) -> Job | None:
        """The in-flight run for ``project_id``, if any.

        ``speculative`` filters by whether the run is system-started background
        work: ``False`` finds only user-initiated runs, ``True`` only speculative
        ones, ``None`` (the default) either.
        """
        return self.active_for_scope(project_id, speculative=speculative)

    def active_for_scope(
        self,
        scope_id: str,
        *,
        scope_kind: ScopeKind | None = None,
        speculative: bool | None = None,
    ) -> Job | None:
        """The in-flight run for ``scope_id`` (optionally of one ``scope_kind``)."""
        return next(
            (
                j
                for j in self._jobs.values()
                if j.scope_id == scope_id
                and (scope_kind is None or j.scope_kind == scope_kind)
                and j.active
                and (speculative is None or (j.kind in _SPECULATIVE) is speculative)
            ),
            None,
        )

    async def start(
        self,
        *,
        project_id: str | None = None,
        kind: JobKind,
        owner_id: str | None,
        run: Callable[[], Awaitable[object]],
        after: Callable[[], Awaitable[object]] | None = None,
        scope_id: str | None = None,
        scope_kind: ScopeKind = "project",
        progress: JobProgress | None = None,
    ) -> Job:
        """Register and launch a run. Raises :class:`JobConflictError` if the
        project already has one in flight.

        ``run`` is a zero-argument factory that returns the stage coroutine when
        called (so the coroutine is created inside the task, not before).

        Speculative kinds bend the rule in both directions, and deliberately:
        starting one while *anything* is in flight is refused (it is a nicety, not
        worth contending for the project), and starting real work first **cancels**
        any speculative run rather than being refused by it. Background
        pre-drafting must never be able to answer a user's click with a 409.
        """
        resolved_scope = scope_id if scope_id is not None else project_id
        if resolved_scope is None:
            raise ValueError("start() needs a project_id or a scope_id")
        async with self._lock:
            self._prune()
            if kind in _SPECULATIVE:
                existing = self.active_for_scope(resolved_scope, scope_kind=scope_kind)
                if existing is not None:
                    raise JobConflictError(resolved_scope, existing.job_id, scope_kind)
            else:
                speculative = self.active_for_scope(
                    resolved_scope, scope_kind=scope_kind, speculative=True
                )
                if speculative is not None:
                    # Nothing is persisted until a run finishes, so this discards
                    # work in progress and no state.
                    await self._cancel(speculative)
                existing = self.active_for_scope(
                    resolved_scope, scope_kind=scope_kind, speculative=False
                )
                if existing is not None:
                    raise JobConflictError(resolved_scope, existing.job_id, scope_kind)
            job = Job(
                job_id=uuid.uuid4().hex,
                scope_id=resolved_scope,
                kind=kind,
                owner_id=owner_id,
                scope_kind=scope_kind,
                progress=progress,
            )
            self._jobs[job.job_id] = job
            job.task = asyncio.create_task(self._run(job, run, after))
            return job

    @staticmethod
    async def _run(
        job: Job,
        run: Callable[[], Awaitable[object]],
        after: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        """Execute the stage and record the terminal status.

        Cancellation is swallowed on purpose: it is a normal terminal outcome for
        a background job, and nothing was persisted, so there is nothing to undo.

        ``after`` is a follow-on step run only when the stage succeeded, and only
        **once the job is no longer active** — which is the point of it. A chained
        step that starts its own job (background question drafting after a
        validate) would otherwise collide with the very job that is calling it.
        Its outcome is not the job's: a failure there is swallowed, because the
        stage the user asked for did succeed.
        """
        try:
            try:
                await run()
                job.status = "succeeded"
            except asyncio.CancelledError:
                job.status = "canceled"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc) or exc.__class__.__name__
            job.updated_at = _now()
            if after is not None and job.status == "succeeded":
                with contextlib.suppress(Exception):
                    await after()
        finally:
            # Cleared last, not when the status was set: the loop keeps only a
            # weak reference to a task, so dropping this one mid-``after`` would
            # let the follow-on step be garbage collected. ``cancel`` guards on
            # ``active`` first, so a terminal job with a task still attached is
            # never cancellable.
            job.task = None

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(
        self,
        *,
        owner_id: str | None,
        project_id: str | None = None,
        scope_id: str | None = None,
        scope_kind: ScopeKind | None = None,
    ) -> list[Job]:
        """Jobs visible to a caller, newest first.

        ``owner_id=None`` returns every job (used when projects are shared, to
        mirror project visibility); otherwise only that owner's jobs.
        ``project_id`` is an alias of ``scope_id``."""
        self._prune()
        wanted_scope = scope_id if scope_id is not None else project_id
        jobs = [
            j
            for j in self._jobs.values()
            if (owner_id is None or j.owner_id == owner_id)
            and (wanted_scope is None or j.scope_id == wanted_scope)
            and (scope_kind is None or j.scope_kind == scope_kind)
        ]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    async def cancel(self, job_id: str) -> Job | None:
        """Cancel a running job and wait for it to settle. No-op if terminal."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        await self._cancel(job)
        return job

    @staticmethod
    async def _cancel(job: Job) -> None:
        """Stop ``job`` and wait until it has recorded a terminal status."""
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
