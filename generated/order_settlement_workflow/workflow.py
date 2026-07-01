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
    """Manages the settlement of orders from validation to finalisation."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._shipping_confirmed_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            workflow.logger.info("Running step: ValidateOrder")
            is_settleable = await workflow.execute_activity(
                validate_order,
                ValidateOrderInput(),
                start_to_close_timeout=timedelta(seconds=5),
            )
            should_is_settleable_true = True  # TODO: set from a real condition: is_settleable == True
            if should_is_settleable_true:
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation_id = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(order_id=arg.order_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((release_inventory, ReleaseInventoryInput(inventory_reservation_id=inventory_reservation_id)))
                workflow.logger.info("Running step: ChargePayment")
                payment_id = await workflow.execute_activity(
                    charge_payment,
                    ChargePaymentInput(order_id=arg.order_id, amount=arg.amount, currency=arg.currency),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['PaymentDeclined']),
                )
                compensations.append((refund_payment, RefundPaymentInput(payment_id=payment_id)))
                should_payment_id_is_not_none = True  # TODO: set from a real condition: payment_id is not None
                if should_payment_id_is_not_none:
                    workflow.logger.info("Running step: NotifyCustomer")
                    s6_result = await workflow.execute_activity(
                        notify_customer,
                        NotifyCustomerInput(customer_id=arg.customer_id, order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=5),
                    )
                    workflow.logger.info("Running step: RecordSettlementEvent")
                    s7_result = await workflow.execute_activity(
                        record_settlement_event,
                        RecordSettlementEventInput(order_id=arg.order_id, payment_id=payment_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
                    workflow.logger.info("Running step: WaitForShippingConfirmation")
                    shipping_confirmed = await workflow.execute_activity(
                        wait_for_shipping_confirmation,
                        WaitForShippingConfirmationInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=86400),
                    )
                    workflow.logger.info("Running step: FinaliseSettlement")
                    settlement_id = await workflow.execute_activity(
                        finalise_settlement,
                        FinaliseSettlementInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=60),
                    )
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
    def shipping_confirmed(self, order_id: str) -> None:
        """Handle the 'shipping.confirmed' signal."""
        self._shipping_confirmed_received = True

    @workflow.query
    def get_settlement_status(self) -> str:
        """Query the current settlement status of an order."""
        return self._status
