"""Worker process for the OrderFulfillmentWorkflow workflow.

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
    from workflow import OrderFulfillmentWorkflow
    from activities import (
        validate_order_and_payment,
        cancel_order,
        reserve_inventory,
        send_order_confirmation,
        notify_warehouse,
        pick_and_pack_items,
        create_shipment,
        release_inventory,
        obtain_manager_approval,
        email_customer_tracking_link,
        notify_customer_of_delay,
        compensate_reserve_inventory,
        notify_customer_of_slabreach,
    )

TASK_QUEUE = "order-fulfillment-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderFulfillmentWorkflow],
        activities=[validate_order_and_payment, cancel_order, reserve_inventory, send_order_confirmation, notify_warehouse, pick_and_pack_items, create_shipment, release_inventory, obtain_manager_approval, email_customer_tracking_link, notify_customer_of_delay, compensate_reserve_inventory, notify_customer_of_slabreach],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())