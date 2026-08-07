"""The FulfilmentWorkflow Temporal workflow.

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
        pick_order_items,
        pack_shipment,
        dispatch_shipment,
        capture_payment,
        record_fulfilment_ledger_entry,
        unpack_shipment,
        refund_captured_payment,
    )
    from triggers import (
        start_payment_reconciliation,
    )
    from shared import (
        WorkflowInput,
        PickOrderItemsInput,
        PackShipmentInput,
        DispatchShipmentInput,
        CapturePaymentInput,
        RecordFulfilmentLedgerEntryInput,
        UnpackShipmentInput,
        RefundCapturedPaymentInput,
        StartPaymentReconciliationInput,
    )

CARRIER_PICKUP_TIMEOUT = timedelta(seconds=86400)  # Timeout for carrier pickup confirmation


@workflow.defn
class FulfilmentWorkflow:
    """Manages the fulfilment process from order to shipment and payment capture"""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []
        self._carrier_picked_up_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'S1'
            workflow.logger.info("Running step: PickOrderItems")
            pick_list_id = await workflow.execute_activity(
                pick_order_items,
                PickOrderItemsInput(order_id=arg.order_id),
                start_to_close_timeout=timedelta(seconds=60),
            )
            self._current_step = 'S2'
            workflow.logger.info("Waiting for signal: carrier_picked_up")
            # Bounded wait: raises TimeoutError after carrier_pickup_timeout, which
            # fires the saga compensations below instead of blocking forever.
            await workflow.wait_condition(lambda: self._carrier_picked_up_received, timeout=CARRIER_PICKUP_TIMEOUT)
            self._current_step = 'S3'
            workflow.logger.info("Running step: PackShipment")
            package_id = await workflow.execute_activity(
                pack_shipment,
                PackShipmentInput(pick_list_id=pick_list_id),
                start_to_close_timeout=timedelta(seconds=60),
            )
            compensations.append((unpack_shipment, UnpackShipmentInput(package_id=package_id)))
            self._current_step = 'S4'
            workflow.logger.info("Running step: DispatchShipment")
            shipment_id = await workflow.execute_activity(
                dispatch_shipment,
                DispatchShipmentInput(package_id=package_id),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3, non_retryable_error_types=['CarrierRejected']),
            )
            self._current_step = 'S5'
            should_shipment_id_null = True  # TODO: set from a real condition: shipment_id != null
            if should_shipment_id_null:
                self._decisions_taken.append({'branch': 'S5', 'predicate': 'shipment_id != null', 'taken': True})
                self._current_step = 'S6'
                workflow.logger.info("Running step: CapturePayment")
                payment_id = await workflow.execute_activity(
                    capture_payment,
                    CapturePaymentInput(order_id=arg.order_id, authorization_id=arg.authorization_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5, non_retryable_error_types=['PaymentDeclined']),
                )
                compensations.append((refund_captured_payment, RefundCapturedPaymentInput(payment_id=payment_id)))
                self._current_step = 'S7'
                workflow.logger.info("Running step: RecordFulfilmentLedgerEntry")
                fulfilment_status = await workflow.execute_activity(
                    record_fulfilment_ledger_entry,
                    RecordFulfilmentLedgerEntryInput(shipment_id=shipment_id, payment_id=payment_id),
                    start_to_close_timeout=timedelta(seconds=60),
                )
            else:
                self._decisions_taken.append({'branch': 'S5', 'predicate': 'shipment_id != null', 'taken': False})
                self._current_step = 'S8'
                workflow.logger.info("Raising: CarrierRejected")
                raise ApplicationError('Workflow rejected: CarrierRejected', type='CarrierRejected', non_retryable=True)
            self._current_step = 'S9'
            workflow.logger.info("Sleeping on timer: carrier_pickup_timeout")
            await workflow.sleep(CARRIER_PICKUP_TIMEOUT)
            self._current_step = 'trigger_1'
            workflow.logger.info("Triggering workflow: PaymentReconciliation")
            trigger_1_result = await workflow.execute_activity(
                start_payment_reconciliation,
                StartPaymentReconciliationInput(),
                start_to_close_timeout=timedelta(seconds=60),
            )
            self._triggers_fired.append('StartPaymentReconciliation')
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
    def carrier_picked_up(self, shipment_id: str) -> None:
        """Handle the 'carrier_picked_up' signal."""
        self._carrier_picked_up_received = True

    @workflow.query
    def get_fulfilment_status(self) -> str:
        """Returns the current fulfilment status of an order"""
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
