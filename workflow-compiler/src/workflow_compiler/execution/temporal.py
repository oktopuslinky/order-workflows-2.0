"""The real :class:`WorkflowExecutor`, backed by a Temporal server.

**This is the only module in the package that imports ``temporalio``**, and even
here the import is deferred to first use. ``temporalio`` is an optional extra
(``pip install workflow-compiler[run]``): the API must import cleanly without it,
because §5.4 requires an absent Temporal to show up as a disabled control rather
than a traceback when someone clicks Run.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from workflow_compiler.execution.workers import WorkerPool
from workflow_compiler.interfaces.executor import (
    ExecutorHealth,
    ExecutorUnavailableError,
    RunEvent,
    RunNotFoundError,
    RunState,
    RunStatus,
    WorkflowExecutor,
)
from workflow_compiler.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from temporalio.client import Client

logger = get_logger()

#: Temporal's terminal statuses mapped onto ours. ``CONTINUED_AS_NEW`` is
#: deliberately absent — it is not terminal from a user's point of view.
_STATUS_TO_STATE: dict[str, RunState] = {
    "RUNNING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "CANCELED": "canceled",
    "CANCELLED": "canceled",
    "TERMINATED": "terminated",
    "TIMED_OUT": "timed_out",
    "CONTINUED_AS_NEW": "running",
}

#: History event types worth showing in a step trail. The raw history is mostly
#: bookkeeping (workflow task scheduled/started/completed for every turn of the
#: loop); these are the entries that correspond to something the user's process
#: actually did.
_INTERESTING = {
    "ACTIVITY_TASK_SCHEDULED": "activity_scheduled",
    "ACTIVITY_TASK_COMPLETED": "activity_completed",
    "ACTIVITY_TASK_FAILED": "activity_failed",
    "TIMER_STARTED": "timer_started",
    "TIMER_FIRED": "timer_fired",
    "WORKFLOW_EXECUTION_SIGNALED": "signal_received",
    "WORKFLOW_EXECUTION_STARTED": "started",
    "WORKFLOW_EXECUTION_COMPLETED": "completed",
    "WORKFLOW_EXECUTION_FAILED": "failed",
    "WORKFLOW_EXECUTION_TERMINATED": "terminated",
    "WORKFLOW_EXECUTION_TIMED_OUT": "timed_out",
}


def temporal_sdk_available() -> bool:
    """Whether ``temporalio`` can be imported at all."""
    try:
        import temporalio.client  # noqa: F401
    except ImportError:
        return False
    return True


class TemporalExecutor(WorkflowExecutor):
    """Runs generated bundles against a Temporal server via subprocess workers."""

    def __init__(self, *, address: str, namespace: str = "default") -> None:
        self._address = address
        self._namespace = namespace
        self._client: Client | None = None
        self._workers = WorkerPool(address=address)

    # -- connection --------------------------------------------------------

    async def _connect(self) -> Client:
        """Connect once and cache. Raises :class:`ExecutorUnavailableError`."""
        if self._client is not None:
            return self._client
        try:
            from temporalio.client import Client
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ExecutorUnavailableError(
                "the Temporal SDK is not installed — "
                "install it with `pip install workflow-compiler[run]`"
            ) from exc
        try:
            self._client = await Client.connect(self._address, namespace=self._namespace)
        except Exception as exc:
            raise ExecutorUnavailableError(
                f"cannot reach a Temporal server at {self._address!r}: {exc}"
            ) from exc
        return self._client

    async def health(self) -> ExecutorHealth:
        """Never raises — this is what the UI gates its Run control on."""
        if not temporal_sdk_available():
            return ExecutorHealth(
                reachable=False,
                address=self._address,
                detail=(
                    "the Temporal SDK is not installed "
                    "(pip install workflow-compiler[run])"
                ),
            )
        try:
            await self._connect()
        except ExecutorUnavailableError as exc:
            return ExecutorHealth(reachable=False, address=self._address, detail=str(exc))
        return ExecutorHealth(reachable=True, address=self._address)

    # -- lifecycle ---------------------------------------------------------

    async def start(
        self,
        *,
        bundle_dir: str,
        workflow_type: str,
        task_queue: str,
        workflow_id: str,
        payload: dict[str, object],
    ) -> RunStatus:
        client = await self._connect()
        # Worker first: starting the execution before anything polls the queue
        # is legal but means a crashed worker looks like a workflow that simply
        # never progresses.
        await self._workers.ensure(bundle_dir=bundle_dir, task_queue=task_queue)

        handle = await client.start_workflow(
            workflow_type,
            payload,
            id=workflow_id,
            task_queue=task_queue,
        )
        logger.info(
            "started execution id={} run={} type={!r}",
            handle.id,
            handle.result_run_id,
            workflow_type,
        )
        return RunStatus(
            workflow_id=handle.id,
            run_id=handle.result_run_id or "",
            state="running",
        )

    async def describe(
        self, *, workflow_id: str, run_id: str, status_query: str | None = None
    ) -> RunStatus:
        client = await self._connect()
        handle = client.get_workflow_handle(workflow_id, run_id=run_id or None)

        try:
            description = await handle.describe()
        except Exception as exc:
            if "not found" in str(exc).lower():
                raise RunNotFoundError(f"no execution {workflow_id!r}") from exc
            raise

        state = _STATUS_TO_STATE.get(_status_name(description.status), "running")
        events = await self._events(handle)

        result: str | None = None
        error: str | None = None
        if state == "completed":
            try:
                result = _short(await handle.result())
            except Exception as exc:  # pragma: no cover - result decode is best effort
                error = str(exc)
        elif state == "failed":
            error = _failure_message(events) or "the workflow failed"
            if await self._compensated(handle, status_query):
                state = "compensated"

        return RunStatus(
            workflow_id=workflow_id,
            run_id=run_id,
            state=state,
            result=result,
            error=error,
            events=events,
            current_step=_current_step(events),
        )

    @staticmethod
    async def _compensated(handle: Any, status_query: str | None) -> bool:
        """Ask the workflow whether it rolled back rather than simply failing.

        Temporal reports a compensating saga as FAILED, because the generated
        ``workflow.py`` re-raises after running its compensations. The workflow
        knows better, so ask it. Querying a closed execution is supported.

        Best-effort by design: a design that declares no status query just reads
        as ``failed``, which is honest — the alternative would be guessing.
        """
        if not status_query:
            return False
        try:
            answer = await handle.query(status_query)
        except Exception:
            return False
        return "compensat" in str(answer).lower()

    @staticmethod
    async def _events(handle: Any) -> list[RunEvent]:
        """Project the raw history into a readable step trail."""
        out: list[RunEvent] = []
        try:
            history = await handle.fetch_history()
        except Exception:  # pragma: no cover - history is a nicety, not the status
            return out

        # An ActivityTaskCompleted event carries no activity name — only the id
        # of the Scheduled event that started it. Without this map the trail
        # reads "activity completed" five times in a row, which tells the user
        # nothing about where their process actually got to.
        scheduled_names: dict[int, str] = {}

        for event in history.events:
            name = _event_type_name(event)
            if name == "ACTIVITY_TASK_SCHEDULED":
                scheduled_names[int(event.event_id)] = _event_detail(event, "activity")
            kind = _INTERESTING.get(name)
            if kind is None:
                continue
            detail = _event_detail(event, kind)
            if kind in {"activity_completed", "activity_failed"}:
                detail = scheduled_names.get(_scheduled_event_id(event), detail)
            out.append(RunEvent(at=_event_time(event), kind=kind, detail=detail))
        return out

    async def signal(
        self, *, workflow_id: str, run_id: str, name: str, args: list[object]
    ) -> None:
        client = await self._connect()
        handle = client.get_workflow_handle(workflow_id, run_id=run_id or None)
        # One argument per declared parameter. A single object passed where the
        # handler expects several raises TypeError *inside* the handler, which
        # fails the workflow task and puts it in a retry loop (handoff §2.1).
        await handle.signal(name, args=list(args))

    async def terminate(self, *, workflow_id: str, run_id: str, reason: str) -> None:
        client = await self._connect()
        handle = client.get_workflow_handle(workflow_id, run_id=run_id or None)
        await handle.terminate(reason=reason)

    async def shutdown(self) -> None:
        await self._workers.shutdown()
        self._client = None


# --- history helpers --------------------------------------------------------
#
# Kept as free functions taking `Any`: they walk protobuf history events, whose
# types only exist when the optional SDK is installed.


def _status_name(status: object) -> str:
    name = getattr(status, "name", None)
    return str(name if name is not None else status).upper()


def _event_type_name(event: Any) -> str:
    event_type = getattr(event, "event_type", None)
    name = getattr(event_type, "name", None)
    if isinstance(name, str):
        return name.removeprefix("EVENT_TYPE_").upper()
    # Fall back to the *_event_attributes field that is set on this event.
    for field, _ in event.ListFields():
        field_name = str(field.name)
        if field_name.endswith("_event_attributes"):
            return field_name.removesuffix("_event_attributes").upper()
    return ""


def _event_time(event: Any) -> datetime | None:
    stamp = getattr(event, "event_time", None)
    if stamp is None:
        return None
    try:
        moment = stamp.ToDatetime()
    except Exception:  # pragma: no cover - defensive
        return None
    return moment if isinstance(moment, datetime) else None


def _event_detail(event: Any, kind: str) -> str:
    """A short human label — the activity or signal name where there is one."""
    for attribute, path in (
        ("activity_task_scheduled_event_attributes", ("activity_type", "name")),
        ("workflow_execution_signaled_event_attributes", ("signal_name",)),
        ("timer_started_event_attributes", ("timer_id",)),
        ("timer_fired_event_attributes", ("timer_id",)),
    ):
        attrs = getattr(event, attribute, None)
        if attrs is None or not event.HasField(attribute):
            continue
        value: Any = attrs
        for part in path:
            value = getattr(value, part, "")
        if value:
            return str(value)
    return kind.replace("_", " ")


def _scheduled_event_id(event: Any) -> int:
    for attribute in (
        "activity_task_completed_event_attributes",
        "activity_task_failed_event_attributes",
    ):
        if event.HasField(attribute):
            return int(getattr(event, attribute).scheduled_event_id)
    return -1


def _current_step(events: list[RunEvent]) -> str | None:
    """Where the process actually is.

    The last *event* is often bookkeeping — a workflow parked on its SLA timer
    ends on ``timer_started``, whose detail is a bare timer id. The last thing
    the user recognizes is the most recent activity, so prefer that and fall
    back to the raw tail only when no activity has run yet.
    """
    for event in reversed(events):
        if event.kind.startswith("activity_"):
            return event.detail
    return events[-1].detail if events else None


def _failure_message(events: list[RunEvent]) -> str | None:
    for event in reversed(events):
        if event.kind in {"activity_failed", "failed"}:
            return event.detail
    return None


def _short(value: object, limit: int = 500) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"
