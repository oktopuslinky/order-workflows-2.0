"""Local step-through harness for the OrderFulfilmentWorkflow workflow.

Runs this bundle under a time-skipping Temporal test environment with the
generated stub activities (they return placeholders, no I/O) and **mocked
trigger activities** (the real ones call the Temporal client), then inspects
the read-only debug queries — proving which steps ran, which branch each
decision took, and which cross-workflow triggers fired.

Run from inside this bundle directory::

    pytest test_stepthrough.py -s

Requires: temporalio, pytest, pytest-asyncio (asyncio_mode=auto or the marker).
"""

from __future__ import annotations

import uuid

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from activities import (
    pick_items,
    pack_shipment,
    dispatch_shipment,
    wait_for_carrier_pickup,
    capture_payment,
    unpack_shipment,
)
from shared import WorkflowInput
from workflow import OrderFulfilmentWorkflow
TRIGGERS_CALLED: list[str] = []


@activity.defn(name="StartOrderReturn")
async def mock_start_order_return(arg) -> str:
    """Mocked cross-workflow start — records the call instead of starting."""
    TRIGGERS_CALLED.append("StartOrderReturn")
    return ""


@pytest.mark.asyncio
async def test_stepthrough() -> None:
    """Run the workflow end to end and inspect the debug queries."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="fulfilment-queue",
            workflows=[OrderFulfilmentWorkflow],
            activities=[pick_items, pack_shipment, dispatch_shipment, wait_for_carrier_pickup, capture_payment, unpack_shipment, mock_start_order_return, ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                OrderFulfilmentWorkflow.run,
                WorkflowInput(),
                id=f"stepthrough-{uuid.uuid4()}",
                task_queue="fulfilment-queue",
            )
            # Release the 'carrier_picked_up' wait gate with a stub payload —
            # signalling before the workflow reaches its wait is safe (the
            # received flag stays set).
            await handle.signal("carrier_picked_up", args=["stub-pickup_confirmation", ])
            result = await handle.result()
            assert result == "completed"
            print("last step:", await handle.query("current_step"))
            print("decisions:", await handle.query("decisions_taken"))
            print("triggers fired:", await handle.query("triggers_fired"))
    finally:
        await env.shutdown()