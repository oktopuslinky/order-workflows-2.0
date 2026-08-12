"""In-memory registry of executions started from the app.

Mirrors :mod:`workflow_compiler.api.jobs`, deliberately. Runs live only in
memory and a server restart drops the index — which is acceptable for the same
reason it is for jobs, and for a better one besides: **Temporal is the durable
record**. The execution keeps running whether or not this process remembers it,
and its full history survives, so nothing is actually lost. What the registry
adds is the mapping the server cannot reconstruct on its own: which project and
slug a workflow id belongs to, and which query reports its disposition.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: Terminal runs older than this are pruned from the index.
_RETENTION_SECONDS = 24 * 60 * 60.0


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Run:
    """One execution started through the API."""

    run_id: str
    project_id: str
    slug: str
    owner_id: str | None
    #: Temporal workflow id — what `temporal workflow describe -w` takes.
    workflow_id: str
    #: Temporal run id, identifying this attempt of that workflow id.
    execution_run_id: str
    task_queue: str
    workflow_type: str
    bundle_dir: str
    #: Query that reports the workflow's own disposition, used to tell a
    #: compensated saga from a genuine failure. ``None`` when it declares none.
    status_query: str | None = None
    created_at: datetime = field(default_factory=_now)
    #: Last observed state, refreshed on each describe. Cached so the list
    #: endpoint does not have to hit Temporal once per run.
    last_state: str = "running"
    last_seen_at: datetime = field(default_factory=_now)


class RunRegistry:
    """Registry of runs, one instance per app."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def _prune(self) -> None:
        cutoff = _now().timestamp() - _RETENTION_SECONDS
        for run_id, run in list(self._runs.items()):
            if run.last_state != "running" and run.last_seen_at.timestamp() < cutoff:
                self._runs.pop(run_id, None)

    def add(self, **kwargs: object) -> Run:
        run = Run(run_id=uuid.uuid4().hex, **kwargs)  # type: ignore[arg-type]
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def note_state(self, run_id: str, state: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return
        run.last_state = state
        run.last_seen_at = _now()

    def list(self, *, owner_id: str | None, project_id: str | None = None) -> list[Run]:
        """Runs visible to a caller, newest first.

        ``owner_id=None`` returns every run, mirroring how project visibility
        works when ``projects_shared`` is on.
        """
        self._prune()
        runs = [
            run
            for run in self._runs.values()
            if (owner_id is None or run.owner_id == owner_id)
            and (project_id is None or run.project_id == project_id)
        ]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)
