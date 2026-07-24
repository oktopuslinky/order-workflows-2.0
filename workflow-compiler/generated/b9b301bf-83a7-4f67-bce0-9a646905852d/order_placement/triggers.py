"""Cross-workflow trigger activities for the OrderFulfillmentWorkflow workflow.

Temporal workflow code may not start another workflow directly (that would be
non-deterministic), so each trigger below is an **activity** that talks to the
Temporal client. The target workflows stay fully standalone: they are started
by workflow-type name on their own task queues, and
``id_conflict_policy=USE_EXISTING`` makes activity retries idempotent — a retry
attaches to the already-started run instead of double-starting it.

The client address comes from ``TEMPORAL_ADDRESS`` (default ``localhost:7233``).
"""

from __future__ import annotations

import os

from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from shared import (
    StartOrderFulfilmentInput,
)

_client: Client | None = None


async def _get_client() -> Client:
    """Connect (once per worker process) to the Temporal server."""
    global _client
    if _client is None:
        _client = await Client.connect(
            os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        )
    return _client


@activity.defn(name="StartOrderFulfilment")
async def start_order_fulfilment(arg: StartOrderFulfilmentInput) -> str:
    """Start the standalone 'OrderFulfilment' workflow."""
    client = await _get_client()
    handle = await client.start_workflow(
        "OrderFulfilment",
        arg,
        id=f"order-fulfilment-{arg.order_id}",
        task_queue="OrderFulfilment-task-queue",
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    activity.logger.info("Started workflow %s", handle.id)
    return handle.id
