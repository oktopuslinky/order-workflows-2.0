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
        compensate_reserve_inventory,
    )
    from triggers import (
        start_order_fulfilment,
        start_order_return,
    )
    from shared import (
        WorkflowInput,
        ValidateCartInput,
        ReserveInventoryInput,
        AuthorisePaymentInput,
        CreateOrderInput,
        ReleaseInventoryReservationInput,
        CompensateReserveInventoryInput,
        StartOrderFulfilmentInput,
        StartOrderReturnInput,
    )

VALIDATE_CART_TIMEOUT = timedelta(seconds=5)  # Timeout for cart validation
AUTHORISE_PAYMENT_TIMEOUT = timedelta(seconds=30)  # Timeout for payment authorisation


@workflow.defn
class EcommerceOrderWorkflow:
    """Manages the ecommerce order workflow from cart validation to order fulfillment"""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []
        self._checkout_submitted_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'S1'
            workflow.logger.info("Running step: ValidateCart")
            eligibility_status = await workflow.execute_activity(
                validate_cart,
                ValidateCartInput(cart_id=arg.cart_id),
                start_to_close_timeout=timedelta(seconds=5),
            )
            self._current_step = 'D1'
            should_eligibility_status_eligible = eligibility_status == 'eligible'  # branch condition: eligibility_status == 'eligible'
            if should_eligibility_status_eligible:
                self._decisions_taken.append({'branch': 'D1', 'predicate': "eligibility_status == 'eligible'", 'taken': True})
                self._current_step = 'S2'
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation_id = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(cart_id=arg.cart_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((compensate_reserve_inventory, CompensateReserveInventoryInput(inventory_reservation_id=inventory_reservation_id)))
                self._current_step = 'S3'
                workflow.logger.info("Running step: AuthorisePayment")
                payment_authorisation_id = await workflow.execute_activity(
                    authorise_payment,
                    AuthorisePaymentInput(amount=arg.amount, currency=arg.currency),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['PaymentDeclined']),
                )
                self._current_step = 'D2'
                should_payment_authorisation_id = bool(payment_authorisation_id)  # branch condition: payment_authorisation_id
                if should_payment_authorisation_id:
                    self._decisions_taken.append({'branch': 'D2', 'predicate': 'payment_authorisation_id', 'taken': True})
                    self._current_step = 'S4'
                    workflow.logger.info("Running step: CreateOrder")
                    order_id = await workflow.execute_activity(
                        create_order,
                        CreateOrderInput(cart_id=arg.cart_id, payment_authorisation_id=payment_authorisation_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
                    self._current_step = 'S5'
                    workflow.logger.info("Running step: ReleaseInventoryReservation")
                    s5_result = await workflow.execute_activity(
                        release_inventory_reservation,
                        ReleaseInventoryReservationInput(inventory_reservation_id=inventory_reservation_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
                else:
                    self._decisions_taken.append({'branch': 'D2', 'predicate': 'payment_authorisation_id', 'taken': False})
                    self._current_step = 'S6'
                    workflow.logger.info("Raising: PaymentDeclined")
                    raise ApplicationError('Workflow rejected: PaymentDeclined', type='PaymentDeclined', non_retryable=True)
                    self._current_step = 'S7'
                    workflow.logger.info("Running step: ReleaseInventoryReservation")
                    s7_result = await workflow.execute_activity(
                        release_inventory_reservation,
                        ReleaseInventoryReservationInput(inventory_reservation_id=inventory_reservation_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
            else:
                self._decisions_taken.append({'branch': 'D1', 'predicate': "eligibility_status == 'eligible'", 'taken': False})
                self._current_step = 'S8'
                workflow.logger.info("Raising: CartNotEligible")
                raise ApplicationError('Workflow rejected: CartNotEligible', type='CartNotEligible', non_retryable=True)
            self._current_step = 'S9'
            workflow.logger.info("Waiting for signal: checkoutSubmitted")
            # Bounded wait: raises TimeoutError after ValidateCartTimeout, which
            # fires the saga compensations below instead of blocking forever.
            await workflow.wait_condition(lambda: self._checkout_submitted_received, timeout=VALIDATE_CART_TIMEOUT)
            self._current_step = 'branch_trigger_1'
            should_when_an_order_is_placed = True  # TODO: set from a real condition: when an order is placed
            if should_when_an_order_is_placed:
                self._decisions_taken.append({'branch': 'branch_trigger_1', 'predicate': 'when an order is placed', 'taken': True})
                self._current_step = 'trigger_1'
                workflow.logger.info("Triggering workflow: OrderFulfilment")
                trigger_1_result = await workflow.execute_activity(
                    start_order_fulfilment,
                    StartOrderFulfilmentInput(),
                    start_to_close_timeout=timedelta(seconds=60),
                )
                self._triggers_fired.append('StartOrderFulfilment')
            else:
                self._decisions_taken.append({'branch': 'branch_trigger_1', 'predicate': 'when an order is placed', 'taken': False})
            self._current_step = 'trigger_2'
            workflow.logger.info("Triggering workflow: OrderReturn")
            trigger_2_result = await workflow.execute_activity(
                start_order_return,
                StartOrderReturnInput(),
                start_to_close_timeout=timedelta(seconds=60),
            )
            self._triggers_fired.append('StartOrderReturn')
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

    @workflow.query
    def get_order_status(self) -> str:
        """Query the current order status"""
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