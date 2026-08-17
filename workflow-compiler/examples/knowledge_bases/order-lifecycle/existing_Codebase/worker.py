"""
Temporal worker process for the order-workflow task queue.

Run with:
    python -m src.worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from src.activities.order_activities import (
    capture_order,
    compensate_dispatch,
    compensate_provisioning,
    complete_order,
    dispatch_order,
    provision_order,
    record_terminal_state,
    validate_order,
)
from src.workflows.order_workflow import OrderWorkflow

TASK_QUEUE = "order-workflow-task-queue"


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    client = await Client.connect("localhost:7233", namespace="default")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=[
            capture_order,
            validate_order,
            provision_order,
            compensate_provisioning,
            dispatch_order,
            compensate_dispatch,
            complete_order,
            record_terminal_state,
        ],
    )

    logging.info("Starting worker on task queue '%s'", TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
