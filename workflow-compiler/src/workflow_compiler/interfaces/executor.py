"""Abstract execution interface for running a generated workflow bundle.

The compiler emits a runnable Temporal bundle but must never *depend* on the
Temporal SDK — the same split every other vendor boundary in this codebase keeps
(`interfaces/`, no vendor SDK in agent or compiler code). So running a bundle is
expressed here in terms the compiler already understands (a bundle directory, a
task queue, a workflow type, a dict of inputs) and implemented behind it.

Two implementations exist:

* ``execution.temporal.TemporalExecutor`` — the real one, and the only module in
  the package that imports ``temporalio``;
* ``execution.fake.FakeExecutor`` — in-memory, no server and no subprocess, so
  the API layer is testable without infrastructure.

Everything here is a plain dataclass or ABC. Nothing imports a vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

#: Terminal and non-terminal states a run can be observed in.
#:
#: ``compensated`` is deliberately distinct from ``failed``: a saga that rolled
#: back cleanly did what it was designed to do, and §8 of the handoff requires a
#: user to be able to tell the two apart at a glance.
RunState = Literal[
    "running",
    "completed",
    "failed",
    "compensated",
    "terminated",
    "timed_out",
    "canceled",
]

#: States from which no further transition is possible.
TERMINAL_RUN_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "compensated", "terminated", "timed_out", "canceled"}
)


class ExecutorError(Exception):
    """Base class for execution failures."""


class ExecutorUnavailableError(ExecutorError):
    """No execution backend is usable — SDK missing, or server unreachable.

    Raised only by code paths that *act*. Availability is otherwise reported
    through :meth:`WorkflowExecutor.health` so the UI can disable its control up
    front rather than failing on click (handoff §5.4).
    """


class RunNotFoundError(ExecutorError):
    """No run with the given identifiers is known to the backend."""


@dataclass(frozen=True)
class ExecutorHealth:
    """Whether runs can be started right now, and why not when they cannot."""

    reachable: bool
    address: str
    detail: str | None = None


@dataclass(frozen=True)
class WorkflowInputField:
    """One field of a bundle's ``WorkflowInput``, for building an input form.

    ``sample`` is the placeholder literal the generator renders into
    ``starter.py`` (handoff §7) — reused here so the form's defaults and the
    bundle's own defaults cannot drift apart.
    """

    name: str
    type: str
    sample: str


@dataclass(frozen=True)
class SignalDescriptor:
    """A signal the workflow declares, named as the **spec** names it.

    The name is load-bearing. A bundle generated before 2026-08-12 registered the
    snake_cased Python method instead, so signalling the documented name did
    nothing at all — no error, no dispatch (handoff §6.2). Callers must send
    ``name`` verbatim, and one argument per entry in ``params``.
    """

    name: str
    params: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunnableWorkflow:
    """Everything needed to offer, and validate, a Run of one generated slug."""

    slug: str
    workflow_id: str
    workflow_type: str
    task_queue: str
    bundle_dir: str | None
    inputs: list[WorkflowInputField] = field(default_factory=list)
    signals: list[SignalDescriptor] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        """``True`` when a bundle exists on disk to execute."""
        return self.bundle_dir is not None


@dataclass(frozen=True)
class RunEvent:
    """One entry in a run's step trail."""

    at: datetime | None
    kind: str
    detail: str


@dataclass(frozen=True)
class RunStatus:
    """Observed state of a single execution."""

    workflow_id: str
    run_id: str
    state: RunState
    result: str | None = None
    error: str | None = None
    events: list[RunEvent] = field(default_factory=list)
    current_step: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_RUN_STATES


class WorkflowExecutor(ABC):
    """Start, observe, signal and stop executions of a generated bundle."""

    @abstractmethod
    async def health(self) -> ExecutorHealth:
        """Report whether the backend is reachable. Must never raise."""
        raise NotImplementedError

    @abstractmethod
    async def start(
        self,
        *,
        bundle_dir: str,
        workflow_type: str,
        task_queue: str,
        workflow_id: str,
        payload: dict[str, object],
    ) -> RunStatus:
        """Ensure a worker serves ``task_queue``, then start one execution.

        ``bundle_dir`` is the directory the worker runs in, so the caller's
        hand-edited ``activities.py`` is what executes.
        """
        raise NotImplementedError

    @abstractmethod
    async def describe(
        self, *, workflow_id: str, run_id: str, status_query: str | None = None
    ) -> RunStatus:
        """Current state of a run, including its step trail.

        ``status_query`` names a query on the workflow that reports its own
        disposition. It exists because a saga that compensated cleanly still
        ends *failed* as far as the server is concerned — the generated
        ``workflow.py`` sets ``self._status = "compensated"`` and then re-raises.
        Without asking the workflow, a clean rollback and a genuine crash are
        indistinguishable, and §8 requires telling them apart.
        """
        raise NotImplementedError

    @abstractmethod
    async def signal(
        self, *, workflow_id: str, run_id: str, name: str, args: list[object]
    ) -> None:
        """Deliver a signal by its **spec** name, one argument per parameter."""
        raise NotImplementedError

    @abstractmethod
    async def terminate(self, *, workflow_id: str, run_id: str, reason: str) -> None:
        """Stop a running execution."""
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Release any processes or connections. Idempotent; no-op by default."""
        return None
