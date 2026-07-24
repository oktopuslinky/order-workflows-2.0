"""The OrderFulfilmentWorkflow Temporal workflow.

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
        pick_items,
        pack_shipment,
        dispatch_shipment,
        capture_payment,
        wait_for_carrier_pickup_confirmation,
        unpack_shipment,
    )
    from shared import (
        WorkflowInput,
        PickItemsInput,
        PackShipmentInput,
        DispatchShipmentInput,
        CapturePaymentInput,
        WaitForCarrierPickupConfirmationInput,
        UnpackShipmentInput,
    )

DISPATCH_TIMEOUT = timedelta(seconds=60)  # Timeout for shipment dispatch.
PICKUP_CONFIRMATION_TIMEOUT = timedelta(seconds=43200)  # Timeout for carrier pickup confirmation.


@workflow.defn
class OrderFulfilmentWorkflow:
    """Manages the order fulfilment process from item picking to payment capture."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._carrier_picked_up_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            workflow.logger.info("Running step: PickItems")
            picked_items = await workflow.execute_activity(
                pick_items,
                PickItemsInput(order_id=arg.order_id),
                start_to_close_timeout=timedelta(seconds=60),
            )
            workflow.logger.info("Running step: PackShipment")
            shipment_id = await workflow.execute_activity(
                pack_shipment,
                PackShipmentInput(picked_items=picked_items),
                start_to_close_timeout=timedelta(seconds=60),
            )
            compensations.append((unpack_shipment, UnpackShipmentInput(shipment_id=shipment_id)))
            workflow.logger.info("Running step: DispatchShipment")
            dispatch_status = await workflow.execute_activity(
                dispatch_shipment,
                DispatchShipmentInput(shipment_id=shipment_id),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3, non_retryable_error_types=['CarrierRejected']),
            )
            should_dispatch_status_success = dispatch_status == 'success'  # branch condition: dispatch_status == 'success'
            if should_dispatch_status_success:
                workflow.logger.info("Running step: CapturePayment")
                payment_id = await workflow.execute_activity(
                    capture_payment,
                    CapturePaymentInput(order_id=arg.order_id, authorization_id=arg.authorization_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5),
                )
                workflow.logger.info("Running step: WaitForCarrierPickupConfirmation")
                confirmation_status = await workflow.execute_activity(
                    wait_for_carrier_pickup_confirmation,
                    WaitForCarrierPickupConfirmationInput(shipment_id=shipment_id),
                    start_to_close_timeout=timedelta(seconds=43200),
                )
            else:
                # Wait until: dispatch_status == 'failed'
                workflow.logger.info("Waiting for signal: carrier.picked_up")
                # Bounded wait: raises TimeoutError after PickupConfirmationTimeout, which
                # fires the saga compensations below instead of blocking forever.
                await workflow.wait_condition(lambda: self._carrier_picked_up_received, timeout=PICKUP_CONFIRMATION_TIMEOUT)
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
    def carrier_picked_up(self) -> None:
        """Handle the 'carrier.picked_up' signal."""
        self._carrier_picked_up_received = True

    @workflow.query
    def get_fulfilment_status(self) -> str:
        """Returns the current fulfilment status of the order."""
        return self._status
