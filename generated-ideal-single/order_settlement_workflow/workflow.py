"""The OrderSettlementWorkflow Temporal workflow.

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
        validate_order,
        reserve_inventory,
        charge_payment,
        notify_customer,
        record_settlement_event,
        wait_for_shipping_confirmation,
        finalise_settlement,
        release_inventory,
        refund_payment,
    )
    from shared import (
        WorkflowInput,
        ValidateOrderInput,
        ReserveInventoryInput,
        ChargePaymentInput,
        NotifyCustomerInput,
        RecordSettlementEventInput,
        WaitForShippingConfirmationInput,
        FinaliseSettlementInput,
        ReleaseInventoryInput,
        RefundPaymentInput,
    )

SHIPPING_CONFIRMATION_TIMEOUT = timedelta(seconds=86400)  # Timeout for waiting on shipping confirmation.


@workflow.defn
class OrderSettlementWorkflow:
    """Manages the settlement of orders, including inventory reservation, payment charging, and shipping confirmation."""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []
        self._shipping_confirmed_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'S1'
            workflow.logger.info("Running step: ValidateOrder")
            is_settleable = await workflow.execute_activity(
                validate_order,
                ValidateOrderInput(),
                start_to_close_timeout=timedelta(seconds=5),
            )
            self._current_step = 'S2'
            should_is_settleable = True  # TODO: set from a real condition: is_settleable
            if should_is_settleable:
                self._decisions_taken.append({'branch': 'S2', 'predicate': 'is_settleable', 'taken': True})
                self._current_step = 'S3'
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation_id = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(order_id=arg.order_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((release_inventory, ReleaseInventoryInput(inventory_reservation_id=inventory_reservation_id)))
                self._current_step = 'S4'
                workflow.logger.info("Running step: ChargePayment")
                payment_id = await workflow.execute_activity(
                    charge_payment,
                    ChargePaymentInput(order_id=arg.order_id, amount=arg.amount, currency=arg.currency),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['PaymentDeclined']),
                )
                compensations.append((refund_payment, RefundPaymentInput(payment_id=payment_id)))
                self._current_step = 'S5'
                should_payment_id = True  # TODO: set from a real condition: payment_id
                if should_payment_id:
                    self._decisions_taken.append({'branch': 'S5', 'predicate': 'payment_id', 'taken': True})
                    self._current_step = 'S6'
                    workflow.logger.info("Running step: NotifyCustomer")
                    s6_result = await workflow.execute_activity(
                        notify_customer,
                        NotifyCustomerInput(customer_id=arg.customer_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=5),
                    )
                    self._current_step = 'S7'
                    workflow.logger.info("Running step: RecordSettlementEvent")
                    s7_result = await workflow.execute_activity(
                        record_settlement_event,
                        RecordSettlementEventInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
                    self._current_step = 'S8'
                    workflow.logger.info("Waiting for signal: ShippingConfirmed")
                    # Bounded wait: raises TimeoutError after ShippingConfirmationTimeout, which
                    # fires the saga compensations below instead of blocking forever.
                    await workflow.wait_condition(lambda: self._shipping_confirmed_received, timeout=SHIPPING_CONFIRMATION_TIMEOUT)
                    self._current_step = 'S9'
                    workflow.logger.info("Running step: FinaliseSettlement")
                    settlement_id = await workflow.execute_activity(
                        finalise_settlement,
                        FinaliseSettlementInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
                else:
                    self._decisions_taken.append({'branch': 'S5', 'predicate': 'payment_id', 'taken': False})
            else:
                self._decisions_taken.append({'branch': 'S2', 'predicate': 'is_settleable', 'taken': False})
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
    def shipping_confirmed(self, shipping_id: str) -> None:
        """Handle the 'ShippingConfirmed' signal."""
        self._shipping_confirmed_received = True

    @workflow.query
    def get_settlement_status(self) -> str:
        """Query the current settlement status of an order."""
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
