"""The EcommerceOrderWorkflow Temporal workflow.

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
        release_inventory_reservation,
    )
    from triggers import (
        start_order_fulfilment,
    )
    from shared import (
        WorkflowInput,
        ValidateCartInput,
        ReserveInventoryInput,
        AuthorisePaymentInput,
        CreateOrderInput,
        ReleaseInventoryReservationInput,
        StartOrderFulfilmentInput,
    )



@workflow.defn
class EcommerceOrderWorkflow:
    """Manages the ecommerce order creation workflow from cart validation to order fulfillment."""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'S1'
            workflow.logger.info("Running step: ValidateCart")
            eligibility = await workflow.execute_activity(
                validate_cart,
                ValidateCartInput(cart_id=arg.cart_id),
                start_to_close_timeout=timedelta(seconds=5),
            )
            self._current_step = 'D1'
            should_eligibility_status_eligible = True  # TODO: set from a real condition: eligibility.status == 'eligible'
            if should_eligibility_status_eligible:
                self._decisions_taken.append({'branch': 'D1', 'predicate': "eligibility.status == 'eligible'", 'taken': True})
                self._current_step = 'S2'
                workflow.logger.info("Running step: ReserveInventory")
                reservation = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(cart_id=arg.cart_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((release_inventory_reservation, ReleaseInventoryReservationInput(reservation_id=reservation)))
                self._current_step = 'S3'
                workflow.logger.info("Running step: AuthorisePayment")
                payment = await workflow.execute_activity(
                    authorise_payment,
                    AuthorisePaymentInput(customer_id=arg.customer_id, amount=arg.amount, currency=arg.currency),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['PaymentDeclined']),
                )
                self._current_step = 'S4'
                workflow.logger.info("Running step: CreateOrder")
                s4_result = await workflow.execute_activity(
                    create_order,
                    CreateOrderInput(cart_id=arg.cart_id, payment_id=payment),
                    start_to_close_timeout=timedelta(seconds=60),
                )
            else:
                self._decisions_taken.append({'branch': 'D1', 'predicate': "eligibility.status == 'eligible'", 'taken': False})
            self._current_step = 'C1'
            should_payment_status_declined = True  # TODO: set from a real condition: payment.status == 'declined'
            if should_payment_status_declined:
                self._decisions_taken.append({'branch': 'C1', 'predicate': "payment.status == 'declined'", 'taken': True})
                self._current_step = 'C2'
                workflow.logger.info("Running step: ReleaseInventoryReservation")
                c2_result = await workflow.execute_activity(
                    release_inventory_reservation,
                    ReleaseInventoryReservationInput(reservation_id=reservation),
                    start_to_close_timeout=timedelta(seconds=60),
                )
            else:
                self._decisions_taken.append({'branch': 'C1', 'predicate': "payment.status == 'declined'", 'taken': False})
            self._current_step = 'branch_trigger_1'
            should_an_order_is_placed = True  # TODO: set from a real condition: an order is placed
            if should_an_order_is_placed:
                self._decisions_taken.append({'branch': 'branch_trigger_1', 'predicate': 'an order is placed', 'taken': True})
                self._current_step = 'trigger_1'
                workflow.logger.info("Triggering workflow: OrderFulfilment")
                trigger_1_result = await workflow.execute_activity(
                    start_order_fulfilment,
                    StartOrderFulfilmentInput(),
                    start_to_close_timeout=timedelta(seconds=60),
                )
                self._triggers_fired.append('StartOrderFulfilment')
            else:
                self._decisions_taken.append({'branch': 'branch_trigger_1', 'predicate': 'an order is placed', 'taken': False})
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

    @workflow.query
    def get_order_status(self) -> str:
        """Query to get the current order status."""
        return self._status

    @workflow.query
    def current_step(self) -> str:
        """The plan step currently executing (read-only debug surface)."""
        return self._current_step

    @workflow.query
    def decisions_taken(self) -> list[dict[str, object]]:
        """Every branch decision so far: branch id, predicate, and path taken."""
        return self._decisions_taken

    @workflow.query
    def triggers_fired(self) -> list[str]:
        """Cross-workflow triggers fired so far."""
        return self._triggers_fired
