"""Worker process for the FulfilmentWorkflow workflow.

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
    from workflow import FulfilmentWorkflow
    from activities import (
        pick_order_items,
        pack_shipment,
        dispatch_shipment,
        capture_payment,
        record_fulfilment_ledger_entry,
        unpack_shipment,
        refund_captured_payment,
    )
    from triggers import (
        start_payment_reconciliation,
    )

TASK_QUEUE = "fulfilment-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[FulfilmentWorkflow],
        activities=[pick_order_items, pack_shipment, dispatch_shipment, capture_payment, record_fulfilment_ledger_entry, unpack_shipment, refund_captured_payment, start_payment_reconciliation],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
