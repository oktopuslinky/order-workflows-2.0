"""An in-memory :class:`WorkflowExecutor` — no server, no subprocess.

Lets the API layer be tested without infrastructure, the way ``MockProvider``
does for the LLM boundary. It is a test double, not a simulator: it records what
it was asked to do and reports whatever state the test told it to report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from workflow_compiler.interfaces.executor import (
    ExecutorHealth,
    ExecutorUnavailableError,
    RunEvent,
    RunNotFoundError,
    RunState,
    RunStatus,
    WorkflowExecutor,
)


@dataclass
class StartedRun:
    """One execution the fake was asked to start."""

    bundle_dir: str
    workflow_type: str
    task_queue: str
    workflow_id: str
    payload: dict[str, object]


@dataclass
class SentSignal:
    workflow_id: str
    name: str
    args: list[object]


@dataclass
class FakeExecutor(WorkflowExecutor):
    """Records calls; returns whatever ``state`` is set to."""

    reachable: bool = True
    address: str = "fake:0"
    detail: str | None = None
    #: State reported by :meth:`describe` for every run.
    state: RunState = "running"
    result: str | None = None
    error: str | None = None

    started: list[StartedRun] = field(default_factory=list)
    signals: list[SentSignal] = field(default_factory=list)
    terminated: list[str] = field(default_factory=list)
    shutdowns: int = 0

    async def health(self) -> ExecutorHealth:
        return ExecutorHealth(
            reachable=self.reachable, address=self.address, detail=self.detail
        )

    async def start(
        self,
        *,
        bundle_dir: str,
        workflow_type: str,
        task_queue: str,
        workflow_id: str,
        payload: dict[str, object],
    ) -> RunStatus:
        if not self.reachable:
            raise ExecutorUnavailableError(self.detail or "fake executor is unreachable")
        self.started.append(
            StartedRun(
                bundle_dir=bundle_dir,
                workflow_type=workflow_type,
                task_queue=task_queue,
                workflow_id=workflow_id,
                payload=payload,
            )
        )
        return RunStatus(
            workflow_id=workflow_id,
            run_id=f"fake-run-{len(self.started)}",
            state="running",
        )

    async def describe(
        self, *, workflow_id: str, run_id: str, status_query: str | None = None
    ) -> RunStatus:
        if not any(run.workflow_id == workflow_id for run in self.started):
            raise RunNotFoundError(workflow_id)
        return RunStatus(
            workflow_id=workflow_id,
            run_id=run_id,
            state=self.state,
            result=self.result,
            error=self.error,
            events=[
                RunEvent(at=datetime.now(UTC), kind="started", detail="ValidateOrder")
            ],
            current_step="ValidateOrder",
        )

    async def signal(
        self, *, workflow_id: str, run_id: str, name: str, args: list[object]
    ) -> None:
        if not any(run.workflow_id == workflow_id for run in self.started):
            raise RunNotFoundError(workflow_id)
        self.signals.append(SentSignal(workflow_id=workflow_id, name=name, args=list(args)))

    async def terminate(self, *, workflow_id: str, run_id: str, reason: str) -> None:
        if not any(run.workflow_id == workflow_id for run in self.started):
            raise RunNotFoundError(workflow_id)
        self.terminated.append(workflow_id)

    async def shutdown(self) -> None:
        self.shutdowns += 1
