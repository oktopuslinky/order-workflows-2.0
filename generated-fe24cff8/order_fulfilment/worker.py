"""Worker process for the OrderFulfilmentWorkflow workflow.

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
    from workflow import OrderFulfilmentWorkflow
    from activities import (
        pick_items,
        pack_shipment,
        dispatch_shipment,
        capture_payment,
        wait_for_carrier_pickup,
        unpack_shipment,
    )
    from triggers import (
        start_order_return,
    )

TASK_QUEUE = "order-fulfilment-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderFulfilmentWorkflow],
        activities=[pick_items, pack_shipment, dispatch_shipment, capture_payment, wait_for_carrier_pickup, unpack_shipment, start_order_return],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
