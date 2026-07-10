"""The OrderPlacementWorkflow Temporal workflow.

Workflow code must be deterministic: do all I/O inside activities, and use
``workflow.*`` helpers (``execute_activity``, ``execute_child_workflow``,
``sleep``, signals, queries) rather than calling the outside world directly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        validate_cart,
        reserve_inventory,
        authorise_payment,
        create_order,
        release_inventory,
    )
    from shared import (
        WorkflowInput,
        ValidateCartInput,
        ReserveInventoryInput,
        AuthorisePaymentInput,
        CreateOrderInput,
        ReleaseInventoryInput,
    )



@workflow.defn
class OrderPlacementWorkflow:
    """Manages the placement of orders, including validation, inventory reservation, payment authorisation, and order creation."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._order_id_emitted_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            workflow.logger.info("Running step: ValidateCart")
            eligibility = await workflow.execute_activity(
                validate_cart,
                ValidateCartInput(cart_id=arg.cart_id),
                start_to_close_timeout=timedelta(seconds=5),
            )
            should_eligibility_eligibility_status_eligible = True  # TODO: set from a real condition: eligibility.eligibility_status == 'ELIGIBLE'
            if should_eligibility_eligibility_status_eligible:
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(cart_id=arg.cart_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((release_inventory, ReleaseInventoryInput(inventory_reservation_id=inventory_reservation)))
                workflow.logger.info("Running step: AuthorisePayment")
                payment_authorisation = await workflow.execute_activity(
                    authorise_payment,
                    AuthorisePaymentInput(amount=arg.amount, currency=arg.currency, customer_id=arg.customer_id),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['PaymentDeclined']),
                )
                workflow.logger.info("Running step: CreateOrder")
                order = await workflow.execute_activity(
                    create_order,
                    CreateOrderInput(cart_id=arg.cart_id, payment_authorisation_id=payment_authorisation),
                    start_to_close_timeout=timedelta(seconds=60),
                )
                # Wait until: order.order_id is not null
                workflow.logger.info("Waiting for signal: order_id_emitted")
                # TODO: pass timeout= to wait_condition so a signal that never arrives can't block the workflow forever.
                await workflow.wait_condition(lambda: self._order_id_emitted_received)
        except Exception:
            for _comp_fn, _comp_arg in reversed(compensations):
                await workflow.execute_activity(
                    _comp_fn,
                    _comp_arg,
                    start_to_close_timeout=timedelta(seconds=60),
                )
            self._status = "compensated"
            raise
        self._status = "completed"
        return self._status

    @workflow.signal
    def order_id_emitted(self, order_id: str) -> None:
        """Handle the 'order_id_emitted' signal."""
        self._order_id_emitted_received = True

    @workflow.query
    def get_order_status(self) -> str:
        """Query the current status of the order placement."""
        return self._status
