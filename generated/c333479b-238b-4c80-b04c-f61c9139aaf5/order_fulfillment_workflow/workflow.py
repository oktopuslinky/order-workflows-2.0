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
        reserve_inventory,
        send_order_confirmation,
        notify_warehouse,
        pick_and_pack_items,
        create_shipment_via_carrier_api,
        ship_order,
        release_reserved_inventory,
        obtain_manager_approval,
        notify_finance_team,
        compensate_reserve_inventory,
    )
    from shared import (
        WorkflowInput,
        ValidateOrderAndPaymentInput,
        ReserveInventoryInput,
        SendOrderConfirmationInput,
        NotifyWarehouseInput,
        PickAndPackItemsInput,
        CreateShipmentViaCarrierAPIInput,
        ShipOrderInput,
        ReleaseReservedInventoryInput,
        ObtainManagerApprovalInput,
        NotifyFinanceTeamInput,
        CompensateReserveInventoryInput,
    )

SHIPMENT_SLATIMER = timedelta(seconds=86400)  # Ensures shipment within 24 hours of payment confirmation.


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

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'S1'
            workflow.logger.info("Running step: ValidateOrderAndPayment")
            payment_validation_result = await workflow.execute_activity(
                validate_order_and_payment,
                ValidateOrderAndPaymentInput(order_id=arg.order_id, customer_info=arg.customer_info),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            self._current_step = 'S2'
            should_payment_validation_result_is_payment_valid = True  # TODO: set from a real condition: paymentValidationResult.is_payment_valid
            if should_payment_validation_result_is_payment_valid:
                self._decisions_taken.append({'branch': 'S2', 'predicate': 'paymentValidationResult.is_payment_valid', 'taken': True})
                self._current_step = 'S3'
                workflow.logger.info("Running step: ReserveInventory")
                inventory_reservation_result = await workflow.execute_activity(
                    reserve_inventory,
                    ReserveInventoryInput(order_id=arg.order_id, items=arg.items),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=10), backoff_coefficient=2, maximum_attempts=3, non_retryable_error_types=['InventoryUnavailableError']),
                )
                compensations.append((compensate_reserve_inventory, CompensateReserveInventoryInput(order_id=inventory_reservation_result)))
                self._current_step = 'S4'
                workflow.logger.info("Running 2 steps in parallel")
                s5_result, s6_result = await asyncio.gather(
                    workflow.execute_activity(
                        send_order_confirmation,
                        SendOrderConfirmationInput(customer_info=arg.customer_info, order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    ),
                    workflow.execute_activity(
                        notify_warehouse,
                        NotifyWarehouseInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    ),
                )
                self._current_step = 'S7'
                workflow.logger.info("Running step: PickAndPackItems")
                picking_status = await workflow.execute_activity(
                    pick_and_pack_items,
                    PickAndPackItemsInput(order_id=arg.order_id),
                    start_to_close_timeout=timedelta(seconds=1800),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                self._current_step = 'S8'
                workflow.logger.info("Running step: CreateShipmentViaCarrierAPI")
                shipment_status = await workflow.execute_activity(
                    create_shipment_via_carrier_api,
                    CreateShipmentViaCarrierAPIInput(order_id=arg.order_id, customer_info=arg.customer_info),
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=30), backoff_coefficient=2, maximum_attempts=5, non_retryable_error_types=['CarrierAPIError']),
                )
                self._current_step = 'S9'
                should_shipment_status_shipment_status_failed = True  # TODO: set from a real condition: shipmentStatus.shipment_status == 'FAILED'
                if should_shipment_status_shipment_status_failed:
                    self._decisions_taken.append({'branch': 'S9', 'predicate': "shipmentStatus.shipment_status == 'FAILED'", 'taken': True})
                    self._current_step = 'S10'
                    workflow.logger.info("Running step: ReleaseReservedInventory")
                    s10_result = await workflow.execute_activity(
                        release_reserved_inventory,
                        ReleaseReservedInventoryInput(order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                else:
                    self._decisions_taken.append({'branch': 'S9', 'predicate': "shipmentStatus.shipment_status == 'FAILED'", 'taken': False})
                    self._current_step = 'S12'
                    workflow.logger.info("Running step: ShipOrder")
                    s12_result = await workflow.execute_activity(
                        ship_order,
                        ShipOrderInput(shipment_id=shipment_status),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                self._current_step = 'S13'
                should_order_value_1000 = True  # TODO: set from a real condition: order_value > 1000
                if should_order_value_1000:
                    self._decisions_taken.append({'branch': 'S13', 'predicate': 'order_value > 1000', 'taken': True})
                    self._current_step = 'S14'
                    workflow.logger.info("Running step: ObtainManagerApproval")
                    approval_status = await workflow.execute_activity(
                        obtain_manager_approval,
                        ObtainManagerApprovalInput(order_value=arg.order_value, order_id=arg.order_id),
                        start_to_close_timeout=timedelta(seconds=3600),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    self._current_step = 'S15'
                    workflow.logger.info("Running step: NotifyFinanceTeam")
                    s15_result = await workflow.execute_activity(
                        notify_finance_team,
                        NotifyFinanceTeamInput(order_id=arg.order_id, order_value=arg.order_value),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                else:
                    self._decisions_taken.append({'branch': 'S13', 'predicate': 'order_value > 1000', 'taken': False})
            else:
                self._decisions_taken.append({'branch': 'S2', 'predicate': 'paymentValidationResult.is_payment_valid', 'taken': False})
                self._current_step = 'S16'
                workflow.logger.info("Raising: PaymentDeclined")
                raise ApplicationError('Workflow rejected: PaymentDeclined', type='PaymentDeclined', non_retryable=True)
            self._current_step = 'S17'
            workflow.logger.info("Waiting for signal: OrderSubmittedSignal")
            # Bounded wait: raises TimeoutError after ShipmentSLATimer, which
            # fires the saga compensations below instead of blocking forever.
            await workflow.wait_condition(lambda: self._order_submitted_signal_received, timeout=SHIPMENT_SLATIMER)
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
    def order_submitted_signal(self, order_id: str) -> None:
        """Handle the 'OrderSubmittedSignal' signal."""
        self._order_submitted_signal_received = True

    @workflow.query
    def get_order_status(self) -> str:
        """Returns the current order fulfillment status."""
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
