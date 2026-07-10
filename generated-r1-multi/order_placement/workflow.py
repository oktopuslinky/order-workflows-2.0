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
from temporalio.exceptions import ApplicationError

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

VALIDATE_CART_TIMEOUT = timedelta(seconds=5)  # Timeout for cart validation.
PAYMENT_AUTHORISATION_TIMEOUT = timedelta(seconds=30)  # Timeout for payment authorisation.


@workflow.defn
class EcommerceOrderWorkflow:
    """Manages the ecommerce order process from cart validation to order creation."""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []
        self._checkout_submitted_received: bool = False
        self._placement_status_update_received: bool = False

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
            should_eligibility_eligible = eligibility == 'eligible'  # branch condition: eligibility == 'eligible'
            if should_eligibility_eligible:
                self._decisions_taken.append({'branch': 'D1', 'predicate': "eligibility == 'eligible'", 'taken': True})
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
                    AuthorisePaymentInput(amount=arg.amount, currency=arg.currency),
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
                self._decisions_taken.append({'branch': 'D1', 'predicate': "eligibility == 'eligible'", 'taken': False})
                self._current_step = 'E1'
                workflow.logger.info("Raising: CartNotEligible")
                raise ApplicationError('Workflow rejected: CartNotEligible', type='CartNotEligible', non_retryable=True)
            self._current_step = 'S5'
            workflow.logger.info("Waiting for signal: checkoutSubmitted")
            # Bounded wait: raises TimeoutError after ValidateCartTimeout, which
            # fires the saga compensations below instead of blocking forever.
            await workflow.wait_condition(lambda: self._checkout_submitted_received, timeout=VALIDATE_CART_TIMEOUT)
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

    @workflow.signal
    def checkout_submitted(self, cart_id: str) -> None:
        """Handle the 'checkoutSubmitted' signal."""
        self._checkout_submitted_received = True

    @workflow.signal
    def placement_status_update(self, status: str) -> None:
        """Handle the 'placementStatusUpdate' signal."""
        self._placement_status_update_received = True

    @workflow.query
    def get_order_status(self) -> str:
        """Query the current order status."""
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
