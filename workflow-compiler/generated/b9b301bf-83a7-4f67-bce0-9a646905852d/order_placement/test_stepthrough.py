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
    validate_cart,
    reserve_inventory,
    authorise_payment,
    create_order_record,
    release_inventory,
    send_order_confirmation_email,
    compensate_reserve_inventory,
)
from shared import WorkflowInput
from workflow import OrderFulfillmentWorkflow
TRIGGERS_CALLED: list[str] = []


@activity.defn(name="StartOrderFulfilment")
async def mock_start_order_fulfilment(arg) -> str:
    """Mocked cross-workflow start — records the call instead of starting."""
    TRIGGERS_CALLED.append("StartOrderFulfilment")
    return ""


@pytest.mark.asyncio
async def test_stepthrough() -> None:
    """Run the workflow end to end and inspect the debug queries."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="order-fulfillment-queue",
            workflows=[OrderFulfillmentWorkflow],
            activities=[validate_cart, reserve_inventory, authorise_payment, create_order_record, release_inventory, send_order_confirmation_email, compensate_reserve_inventory, mock_start_order_fulfilment, ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                OrderFulfillmentWorkflow.run,
                WorkflowInput(),
                id=f"stepthrough-{uuid.uuid4()}",
                task_queue="order-fulfillment-queue",
            )
            # Release the 'checkoutSubmitted' wait gate with a stub payload —
            # signalling before the workflow reaches its wait is safe (the
            # received flag stays set).
            await handle.signal("checkout_submitted", args=["stub-cart_id", ])
            # Release the 'placementStatusUpdate' wait gate with a stub payload —
            # signalling before the workflow reaches its wait is safe (the
            # received flag stays set).
            await handle.signal("placement_status_update", args=["stub-placement_status", ])
            result = await handle.result()
            assert result == "completed"
            print("last step:", await handle.query("current_step"))
            print("decisions:", await handle.query("decisions_taken"))
            print("triggers fired:", await handle.query("triggers_fired"))
    finally:
        await env.shutdown()
