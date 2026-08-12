"""Local step-through harness for the OrderFulfillmentWorkflow workflow.

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
from shared import WorkflowInput
from workflow import OrderFulfillmentWorkflow
TRIGGERS_CALLED: list[str] = []


@pytest.mark.asyncio
async def test_stepthrough() -> None:
    """Run the workflow end to end and inspect the debug queries."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="order-fulfillment-queue",
            workflows=[OrderFulfillmentWorkflow],
            activities=[validate_order_and_payment, cancel_order, reserve_inventory, send_order_confirmation, notify_warehouse, pick_and_pack_items, create_shipment, release_inventory, obtain_manager_approval, email_customer_tracking_link, notify_customer_of_delay, compensate_reserve_inventory, notify_customer_of_slabreach, ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                OrderFulfillmentWorkflow.run,
                WorkflowInput(),
                id=f"stepthrough-{uuid.uuid4()}",
                task_queue="order-fulfillment-queue",
            )
            # Release the 'OrderSubmittedSignal' wait gate with a stub payload —
            # signalling before the workflow reaches its wait is safe (the
            # received flag stays set).
            await handle.signal("order_submitted_signal", args=["stub-order_id", ])
            # Release the 'SLABreachAlert' wait gate with a stub payload —
            # signalling before the workflow reaches its wait is safe (the
            # received flag stays set).
            await handle.signal("slabreach_alert", args=["stub-order_id", "stub-delay_reason", ])
            result = await handle.result()
            assert result == "completed"
            print("last step:", await handle.query("current_step"))
            print("decisions:", await handle.query("decisions_taken"))
            print("triggers fired:", await handle.query("triggers_fired"))
    finally:
        await env.shutdown()