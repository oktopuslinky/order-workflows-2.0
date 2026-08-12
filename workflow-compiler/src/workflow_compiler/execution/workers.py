"""Supervise ``python worker.py`` subprocesses for generated bundles.

Option A of handoff §5.3, chosen because it is how the bundle is already designed
to run (§2) and it keeps generated code out of the API process.

One worker per ``(bundle directory, task queue)``, started lazily on the first
run and **reused** across later runs of the same workflow. Per-run workers would
be simpler to reap but wrong: a workflow that parks on a 24-hour SLA timer (§2)
needs its worker alive long after the request that started it returned.

The failure this module exists to prevent: if the worker dies at import time —
``temporalio`` missing, a syntax error in a hand-edited ``activities.py`` — then
nothing consumes the task queue and the execution simply sits in ``Running``
forever with no error anywhere. So the pool captures the child's output and,
when it exits early, reports *that* instead of letting the run hang.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from workflow_compiler.interfaces.executor import ExecutorUnavailableError
from workflow_compiler.logging import get_logger

logger = get_logger()

#: How long to wait for a freshly spawned worker to start polling.
_READY_TIMEOUT = 30.0
#: How often to re-check readiness while waiting.
_POLL_INTERVAL = 0.25
#: Grace period used when no readiness probe is supplied — long enough for an
#: import-time crash (missing temporalio, a broken hand-edited activities.py)
#: to have happened already.
_READY_GRACE = 2.0
#: How much of a dead worker's output to quote back in the error.
_ERROR_TAIL = 2000


@dataclass
class _Worker:
    """One supervised ``worker.py`` process."""

    key: tuple[str, str]
    process: asyncio.subprocess.Process
    output: bytearray = field(default_factory=bytearray)
    reader: asyncio.Task[None] | None = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    def tail(self) -> str:
        text = self.output.decode("utf-8", errors="replace").strip()
        return text[-_ERROR_TAIL:]


class WorkerPool:
    """Lazily starts and reuses bundle workers; shuts them all down on exit."""

    def __init__(
        self,
        *,
        address: str,
        is_ready: Callable[[str], Awaitable[bool]] | None = None,
        ready_timeout: float = _READY_TIMEOUT,
    ) -> None:
        """``is_ready`` reports whether a task queue has a live poller.

        It is injected rather than implemented here so this module stays free of
        the Temporal SDK; the executor supplies it.
        """
        self._address = address
        self._is_ready = is_ready
        self._ready_timeout = ready_timeout
        self._workers: dict[tuple[str, str], _Worker] = {}
        self._lock = asyncio.Lock()

    async def ensure(self, *, bundle_dir: str, task_queue: str) -> None:
        """Guarantee a live worker serving ``task_queue`` from ``bundle_dir``."""
        key = (str(Path(bundle_dir).resolve()), task_queue)
        async with self._lock:
            existing = self._workers.get(key)
            if existing is not None and existing.alive:
                return
            if existing is not None:
                # Died since the last run — surface why rather than silently
                # restarting into the same failure.
                logger.warning(
                    "bundle worker had exited (rc={}) — restarting: {}",
                    existing.process.returncode,
                    existing.tail()[-200:],
                )
                await self._discard(key)
            worker = await self._spawn(key)
            self._workers[key] = worker
        await self._await_ready(worker, task_queue)

    async def _spawn(self, key: tuple[str, str]) -> _Worker:
        directory, task_queue = key
        script = Path(directory) / "worker.py"
        if not script.is_file():
            raise ExecutorUnavailableError(
                f"no worker.py in {directory!r} — the bundle is not on disk"
            )

        env = dict(os.environ)
        env["TEMPORAL_ADDRESS"] = self._address
        # Generated bundles import `workflow`/`shared`/`activities` as top-level
        # modules from their own directory, and print progress with non-cp1252
        # glyphs on Windows.
        env["PYTHONUTF8"] = "1"
        env.setdefault("PYTHONUNBUFFERED", "1")

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "worker.py",
            cwd=directory,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
        )
        worker = _Worker(key=key, process=process)
        worker.reader = asyncio.create_task(self._drain(worker))
        logger.info(
            "started bundle worker pid={} queue={!r} dir={}",
            process.pid,
            task_queue,
            directory,
        )
        return worker

    @staticmethod
    async def _drain(worker: _Worker) -> None:
        """Accumulate the child's output so a crash can explain itself.

        Without this the pipe fills, the child blocks on write, and the worker
        wedges without ever exiting — a hang that looks exactly like a workflow
        waiting on a signal.
        """
        stream = worker.process.stdout
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            worker.output.extend(chunk)
            if len(worker.output) > 64_000:
                del worker.output[:-32_000]

    async def _await_ready(self, worker: _Worker, task_queue: str) -> None:
        """Block until the worker polls the queue, or explain why it never will."""
        deadline = asyncio.get_running_loop().time() + self._ready_timeout
        while True:
            if not worker.alive:
                raise ExecutorUnavailableError(
                    f"the bundle worker exited immediately (code "
                    f"{worker.process.returncode}). Output:\n{worker.tail()}"
                )
            if self._is_ready is None:
                # No readiness probe: give the child long enough to fail at
                # import (which is where it fails, and it fails fast), then trust
                # it. Temporal queues the task until a worker polls, so starting
                # slightly early is harmless; starting after a silent crash is
                # not, and that is what the grace period catches.
                await asyncio.sleep(_READY_GRACE)
                if not worker.alive:
                    continue
                return
            if await self._is_ready(task_queue):
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise ExecutorUnavailableError(
                    f"the bundle worker did not start polling {task_queue!r} "
                    f"within {self._ready_timeout:.0f}s. Output:\n{worker.tail()}"
                )
            await asyncio.sleep(_POLL_INTERVAL)

    async def _discard(self, key: tuple[str, str]) -> None:
        worker = self._workers.pop(key, None)
        if worker is None:
            return
        if worker.alive:
            worker.process.terminate()
            try:
                await asyncio.wait_for(worker.process.wait(), timeout=10)
            except TimeoutError:
                worker.process.kill()
        if worker.reader is not None:
            worker.reader.cancel()

    async def shutdown(self) -> None:
        """Stop every worker. Idempotent."""
        async with self._lock:
            for key in list(self._workers):
                await self._discard(key)
