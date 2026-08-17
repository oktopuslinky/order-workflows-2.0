"""
CLI to start a new OrderWorkflow execution.

Example:
    python -m src.starter --customer-id CUST-1001 --sku SKU-4471 --qty 2
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from src.shared.types import LineItem, OrderRequest, ShippingAddress
from src.worker import TASK_QUEUE
from src.workflows.order_workflow import OrderWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer-id", required=True)
    parser.add_argument("--sku", required=True)
    parser.add_argument("--qty", type=int, default=1)
    parser.add_argument("--payment-token", default="tok_test_ok")
    parser.add_argument("--order-id", default=None, help="Defaults to a generated UUID")
    args = parser.parse_args()

    order_id = args.order_id or f"ORD-{uuid.uuid4().hex[:10].upper()}"

    order = OrderRequest(
        order_id=order_id,
        customer_id=args.customer_id,
        line_items=[LineItem(sku=args.sku, quantity=args.qty, unit_price=19.99)],
        shipping_address=ShippingAddress(
            line1="123 Market St",
            city="Dallas",
            state="TX",
            postal_code="75201",
            country="US",
        ),
        payment_token=args.payment_token,
    )

    client = await Client.connect("localhost:7233", namespace="default")

    handle = await client.start_workflow(
        OrderWorkflow.run,
        order,
        id=order_id,  # order_id as Workflow ID -> idempotent start (US-001)
        task_queue=TASK_QUEUE,
    )

    print(f"Started OrderWorkflow: order_id={order_id} workflow_id={handle.id} run_id={handle.result_run_id}")


if __name__ == "__main__":
    asyncio.run(main())
