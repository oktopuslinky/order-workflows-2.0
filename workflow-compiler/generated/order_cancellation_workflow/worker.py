"""Worker process for the OrderCancellationWorkflow workflow.

Start a local Temporal dev server in one terminal::

    temporal server start-dev

Then, from inside this package directory, run the worker::

    python worker.py

Keep it running, then start a workflow with ``python starter.py``.
"""

from __future__ import annotations

import asyncio

from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from workflow import OrderCancellationWorkflow
    from activities import (
        cancel_request_intake,
        eligibility_check,
        deprovisioning,
        inventory_release,
        partial_cancel_compensation,
    )

TASK_QUEUE = "order-cancellation-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderCancellationWorkflow],
        activities=[cancel_request_intake, eligibility_check, deprovisioning, inventory_release, partial_cancel_compensation],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
