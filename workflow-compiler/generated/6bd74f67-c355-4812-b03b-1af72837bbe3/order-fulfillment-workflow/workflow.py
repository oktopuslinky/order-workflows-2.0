"""The OrderFulfillmentWorkflow Temporal workflow.

Workflow code must be deterministic: do all I/O inside activities, and use
``workflow.*`` helpers (``execute_activity``, ``execute_child_workflow``,
``sleep``, signals, queries) rather than calling the outside world directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from activities import (
        validate_order_and_payment,
        cancel_order,
        reserve_inventory,
        send_order_confirmation,
        notify_warehouse,
        pick_and_pack_items,
        create_shipment,
        release_inventory,
        obtain_manager_approval,
        email_customer_tracking_link,
        notify_customer_of_delay,
        compensate_reserve_inventory,
        notify_customer_of_slabreach,
    )
    from shared import (
        WorkflowInput,
        ValidateOrderAndPaymentInput,
        CancelOrderInput,
        ReserveInventoryInput,
        SendOrderConfirmationInput,
        NotifyWarehouseInput,
        PickAndPackItemsInput,
        CreateShipmentInput,
        ReleaseInventoryInput,
        ObtainManagerApprovalInput,
        EmailCustomerTrackingLinkInput,
        NotifyCustomerOfDelayInput,
        CompensateReserveInventoryInput,
        NotifyCustomerOfSLABreachInput,
    )

SHIPMENT_SLATIMER = timedelta(seconds=86400)  # 24-hour timer for shipment SLA.


@workflow.defn
class OrderFulfillmentWorkflow:
    """Manages the order fulfillment process from validation to shipment."""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []
        self._order_submitted_signal_received: bool = False
        self._slabreach_alert_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'S1'
            workflow.logger.info("Running step: ValidateOrderAndPayment")
            validation_result = await workflow.execute_activity(
                validate_order_and_payment,
                ValidateOrderAndPaymentInput(order=arg.customer_order),
                start_to_close_timeout=timedelta(seconds=30),
            )
            self._current_step = 'D1'
            should_validation_result_is_valid = True  # TODO: set from a real condition: validation_result.is_valid
            if should_validation_result_is_valid:
                self._decisions_taken.append({'branch': 'D1', 'predicate': 'validation_result.is_valid', 'taken': True})
                self._current_step = 'S2'
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(order_items=arg.customer_order_items),
                    start_to_close_timeout=timedelta(seconds=45),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2, maximum_attempts=3, maximum_interval=timedelta(seconds=60)),
                )
                compensations.append((compensate_reserve_inventory, CompensateReserveInventoryInput(inventory_reservation_id=inventory_reservation)))
                self._current_step = 'S3'
                workflow.logger.info("Running 2 steps in parallel")
                s3a_result, s3b_result = await asyncio.gather(
                    workflow.execute_activity(
                        send_order_confirmation,
                        SendOrderConfirmationInput(customer_email=arg.customer_email),
                        start_to_close_timeout=timedelta(seconds=10),
                    ),
                    workflow.execute_activity(
                        notify_warehouse,
                        NotifyWarehouseInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=20),
                    ),
                )
                self._current_step = 'S4'
                workflow.logger.info("Running step: PickAndPackItems")
                packing_slip = await workflow.execute_activity(
                    pick_and_pack_items,
                    PickAndPackItemsInput(order_id=arg.order_id),
                    start_to_close_timeout=timedelta(seconds=120),
                )
                self._current_step = 'S5'
                workflow.logger.info("Running step: CreateShipment")
                shipment_id = await workflow.execute_activity(
                    create_shipment,
                    CreateShipmentInput(packing_slip_id=packing_slip),
                    start_to_close_timeout=timedelta(seconds=90),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=10), backoff_coefficient=2, maximum_attempts=3, maximum_interval=timedelta(seconds=120), non_retryable_error_types=['CarrierAPIError']),
                )
                compensations.append((notify_customer_of_slabreach, NotifyCustomerOfSLABreachInput(customer_email=arg.customer_email)))
                self._current_step = 'D2'
                should_shipment_id = bool(shipment_id)  # branch condition: shipment_id
                if should_shipment_id:
                    self._decisions_taken.append({'branch': 'D2', 'predicate': 'shipment_id', 'taken': True})
                    self._current_step = 'S6'
                    workflow.logger.info("Running step: EmailCustomerTrackingLink")
                    s6_result = await workflow.execute_activity(
                        email_customer_tracking_link,
                        EmailCustomerTrackingLinkInput(customer_email=arg.customer_email, tracking_link=shipment_id),
                        start_to_close_timeout=timedelta(seconds=10),
                    )
                else:
                    self._decisions_taken.append({'branch': 'D2', 'predicate': 'shipment_id', 'taken': False})
                    self._current_step = 'S7'
                    workflow.logger.info("Running step: NotifyCustomerOfDelay")
                    s7_result = await workflow.execute_activity(
                        notify_customer_of_delay,
                        NotifyCustomerOfDelayInput(customer_email=arg.customer_email),
                        start_to_close_timeout=timedelta(seconds=10),
                    )
                    self._current_step = 'S8'
                    workflow.logger.info("Raising: ShipmentCreationFailed")
                    raise ApplicationError('Workflow rejected: ShipmentCreationFailed', type='ShipmentCreationFailed', non_retryable=True)
            else:
                self._decisions_taken.append({'branch': 'D1', 'predicate': 'validation_result.is_valid', 'taken': False})
                self._current_step = 'S9'
                workflow.logger.info("Running step: CancelOrder")
                s9_result = await workflow.execute_activity(
                    cancel_order,
                    CancelOrderInput(order_id=arg.order_id),
                    start_to_close_timeout=timedelta(seconds=15),
                )
                self._current_step = 'S10'
                workflow.logger.info("Raising: PaymentDeclined")
                raise ApplicationError('Workflow rejected: PaymentDeclined', type='PaymentDeclined', non_retryable=True)
            self._current_step = 'S11'
            # Wait until: true
            workflow.logger.info("Waiting for signal: SLABreachAlert")
            # Bounded wait: raises TimeoutError after ShipmentSLATimer, which
            # fires the saga compensations below instead of blocking forever.
            await workflow.wait_condition(lambda: self._slabreach_alert_received, timeout=SHIPMENT_SLATIMER)
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
    @workflow.signal(name="OrderSubmittedSignal")
    def order_submitted_signal(self, order_id: str = "") -> None:
        """Handle the 'OrderSubmittedSignal' signal."""
        self._order_submitted_signal_received = True
    @workflow.signal(name="SLABreachAlert")
    def slabreach_alert(self, order_id: str = "", delay_reason: str = "") -> None:
        """Handle the 'SLABreachAlert' signal."""
        self._slabreach_alert_received = True
    @workflow.query(name="GetOrderStatus")
    def get_order_status(self) -> str:
        """Query the current status of an order."""
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