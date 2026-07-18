"""The EcommerceOrderFulfillment Temporal workflow.

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
        pick_items,
        pack_shipment,
        dispatch_shipment,
        capture_payment,
        authorise_return,
        receive_returned_item,
        issue_refund,
        release_inventory,
        unpack_shipment,
    )
    from shared import (
        WorkflowInput,
        ValidateCartInput,
        ReserveInventoryInput,
        AuthorisePaymentInput,
        CreateOrderInput,
        PickItemsInput,
        PackShipmentInput,
        DispatchShipmentInput,
        CapturePaymentInput,
        AuthoriseReturnInput,
        ReceiveReturnedItemInput,
        IssueRefundInput,
        ReleaseInventoryInput,
        UnpackShipmentInput,
    )

CART_VALIDATION_TIMEOUT = timedelta(seconds=5)  # Timeout for cart validation.
PAYMENT_AUTHORISATION_TIMEOUT = timedelta(seconds=30)  # Timeout for payment authorisation.
DISPATCH_TIMEOUT = timedelta(seconds=3600)  # Timeout for shipment dispatch.
RETURN_AUTHORISATION_TIMEOUT = timedelta(seconds=10)  # Timeout for return authorisation.
REFUND_TIMEOUT = timedelta(seconds=30)  # Timeout for refund processing.


@workflow.defn
class EcommerceOrderFulfillment:
    """Manages the full lifecycle of an e-commerce order from cart validation through shipment and potential returns."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._checkout_submitted_received: bool = False
        self._order_fulfil_received: bool = False
        self._return_requested_received: bool = False
        self._carrier_picked_up_received: bool = False

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
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            should_eligibility_eligible = True  # TODO: set from a real condition: eligibility == 'eligible'
            if should_eligibility_eligible:
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(order_id=arg.order_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((release_inventory, ReleaseInventoryInput(inventory_reservation_id=inventory_reservation)))
                workflow.logger.info("Running step: AuthorisePayment")
                payment_authorisation = await workflow.execute_activity(
                    authorise_payment,
                    AuthorisePaymentInput(amount=arg.amount, currency=arg.currency),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['PaymentDeclined']),
                )
                should_payment_authorisation_successful = True  # TODO: set from a real condition: payment_authorisation == 'successful'
                if should_payment_authorisation_successful:
                    workflow.logger.info("Running step: CreateOrder")
                    order_created = await workflow.execute_activity(
                        create_order,
                        CreateOrderInput(customer_id=arg.customer_id, cart_id=arg.cart_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    workflow.logger.info("Running step: PickItems")
                    picking_done = await workflow.execute_activity(
                        pick_items,
                        PickItemsInput(order_id=order_created),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    workflow.logger.info("Running step: PackShipment")
                    shipment_packed = await workflow.execute_activity(
                        pack_shipment,
                        PackShipmentInput(order_id=order_created),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    compensations.append((unpack_shipment, UnpackShipmentInput(shipment_pack_status=shipment_packed)))
                    workflow.logger.info("Running step: DispatchShipment")
                    shipment_dispatched = await workflow.execute_activity(
                        dispatch_shipment,
                        DispatchShipmentInput(shipment_id=arg.shipment_id),
                        start_to_close_timeout=timedelta(seconds=3600),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3, non_retryable_error_types=['CarrierRejected', 'PickupTimeout']),
                    )
                    # Wait until: shipment_dispatched == 'picked_up'
                    workflow.logger.info("Waiting for signal: carrier.picked_up")
                    # TODO: pass timeout= to wait_condition so a signal that never arrives can't block the workflow forever.
                    await workflow.wait_condition(lambda: self._carrier_picked_up_received)
                    workflow.logger.info("Running step: CapturePayment")
                    payment_captured = await workflow.execute_activity(
                        capture_payment,
                        CapturePaymentInput(payment_authorisation_id=payment_authorisation),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5),
                    )
                else:
                    # Wait until: true
                    workflow.logger.info("Waiting for signal: return.requested")
                    # TODO: pass timeout= to wait_condition so a signal that never arrives can't block the workflow forever.
                    await workflow.wait_condition(lambda: self._return_requested_received)
                    workflow.logger.info("Running step: AuthoriseReturn")
                    return_eligible = await workflow.execute_activity(
                        authorise_return,
                        AuthoriseReturnInput(reason_code=arg.reason_code, order_id=order_created),
                        start_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    should_return_eligible_eligible = True  # TODO: set from a real condition: return_eligible == 'eligible'
                    if should_return_eligible_eligible:
                        workflow.logger.info("Running step: ReceiveReturnedItem")
                        item_received = await workflow.execute_activity(
                            receive_returned_item,
                            ReceiveReturnedItemInput(return_id=return_eligible),
                            start_to_close_timeout=timedelta(seconds=60),
                            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                        )
                        workflow.logger.info("Running step: IssueRefund")
                        refund_issued = await workflow.execute_activity(
                            issue_refund,
                            IssueRefundInput(payment_capture_id=payment_captured),
                            start_to_close_timeout=timedelta(seconds=30),
                            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5, non_retryable_error_types=['RefundFailed']),
                        )
            else:
                # Wait until: true
                workflow.logger.info("Waiting for signal: checkout.submitted")
                # TODO: pass timeout= to wait_condition so a signal that never arrives can't block the workflow forever.
                await workflow.wait_condition(lambda: self._checkout_submitted_received)
        except Exception:
            for _comp_fn, _comp_arg in reversed(compensations):
                await workflow.execute_activity(
                    _comp_fn,
                    _comp_arg,
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
            self._status = "compensated"
            raise
        self._status = "completed"
        return self._status

    @workflow.signal
    def checkout_submitted(self, cart_id: str, customer_id: str) -> None:
        """Handle the 'checkout.submitted' signal."""
        self._checkout_submitted_received = True

    @workflow.signal
    def order_fulfil(self, order_id: str) -> None:
        """Handle the 'order.fulfil' signal."""
        self._order_fulfil_received = True

    @workflow.signal
    def return_requested(self, order_id: str, reason_code: str) -> None:
        """Handle the 'return.requested' signal."""
        self._return_requested_received = True

    @workflow.signal
    def carrier_picked_up(self, shipment_id: str) -> None:
        """Handle the 'carrier.picked_up' signal."""
        self._carrier_picked_up_received = True

    @workflow.query
    def get_order_status(self) -> str:
        """Returns the current order status."""
        return self._status

    @workflow.query
    def get_shipment_status(self) -> str:
        """Returns the current shipment status."""
        return self._status
