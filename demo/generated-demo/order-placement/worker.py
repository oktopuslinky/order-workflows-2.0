"""Worker process for the EcommerceOrderWorkflow workflow.

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
    from workflow import EcommerceOrderWorkflow
    from activities import (
        validate_cart,
        reserve_inventory,
        authorise_payment,
        create_order,
        release_inventory_reservation,
        compensate_reserve_inventory,
    )
    from triggers import (
        start_order_fulfilment,
        start_order_return,
    )

TASK_QUEUE = "ecommerce-queue"


async def main() -> None:
    """Connect to Temporal and run the worker until cancelled."""
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[EcommerceOrderWorkflow],
        activities=[validate_cart, reserve_inventory, authorise_payment, create_order, release_inventory_reservation, compensate_reserve_inventory, start_order_fulfilment, start_order_return],
    )
    print(f"Worker started on task queue {TASK_QUEUE!r}. Press Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())