"""Worker process for the OrderSettlementWorkflow workflow.

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
    from workflow import OrderSettlementWorkflow
    from activities import (
        validate_order,
        reserve_inventory,
        charge_payment,
        notify_customer,
        record_settlement_event,
        wait_for_shipping_confirmation,
        finalise_settlement,
        release_inventory,
        refund_payment,
    )

TASK_QUEUE = "order-settlement-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderSettlementWorkflow],
        activities=[validate_order, reserve_inventory, charge_payment, notify_customer, record_settlement_event, wait_for_shipping_confirmation, finalise_settlement, release_inventory, refund_payment],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
