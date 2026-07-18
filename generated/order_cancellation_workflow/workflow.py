"""The OrderCancellationWorkflow Temporal workflow.

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
        cancel_request_intake,
        eligibility_check,
        deprovisioning,
        inventory_release,
        partial_cancel_compensation,
    )
    from shared import (
        WorkflowInput,
        CancelRequestIntakeInput,
        EligibilityCheckInput,
        DeprovisioningInput,
        InventoryReleaseInput,
        PartialCancelCompensationInput,
    )



@workflow.defn
class OrderCancellationWorkflow:
    """Manages the cancellation of orders based on input parameters."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._cancel_requested_received: bool = False
        self._cancel_eligible_received: bool = False
        self._cancel_ineligible_received: bool = False
        self._in_flight_stopped_received: bool = False
        self._deprovision_requested_received: bool = False
        self._deprovision_completed_received: bool = False
        self._inventory_released_received: bool = False
        self._cancel_completed_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            workflow.logger.info("Running step: CancelRequestIntake")
            cancel_request_result = await workflow.execute_activity(
                cancel_request_intake,
                CancelRequestIntakeInput(order_type=arg.order_type, cancel_scope=arg.cancel_scope, cancel_reason=arg.cancel_reason, requested_by=arg.requested_by, effective_date=arg.effective_date, target_item_ids=arg.target_item_ids, authorization=arg.authorization),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3, non_retryable_error_types=['OMS-CO-429', 'OMS-CO-500', 'OMS-CO-504']),
            )
            workflow.logger.info("Running step: EligibilityCheck")
            eligibility_result = await workflow.execute_activity(
                eligibility_check,
                EligibilityCheckInput(cancel_request_id=cancel_request_result, order_type=arg.order_type),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            should_eligibility_result_eligibility_status_eligible = True  # TODO: set from a real condition: EligibilityResult.eligibilityStatus == 'ELIGIBLE'
            if should_eligibility_result_eligibility_status_eligible:
                workflow.logger.info("Running step: Deprovisioning")
                deprovisioning_result = await workflow.execute_activity(
                    deprovisioning,
                    DeprovisioningInput(eligibility_status=eligibility_result, cancel_request_id=cancel_request_result),
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1.5, maximum_attempts=2, non_retryable_error_types=['DeprovisionFailure']),
                )
                compensations.append((partial_cancel_compensation, PartialCancelCompensationInput(cancel_request_id=arg.cancel_request_id)))
                workflow.logger.info("Running step: InventoryRelease")
                inventory_release_result = await workflow.execute_activity(
                    inventory_release,
                    InventoryReleaseInput(deprovision_status=deprovisioning_result, cancel_request_id=cancel_request_result),
                    start_to_close_timeout=timedelta(seconds=90),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
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
    def cancel_requested(self) -> None:
        """Handle the 'CancelRequested' signal."""
        self._cancel_requested_received = True

    @workflow.signal
    def cancel_eligible(self) -> None:
        """Handle the 'CancelEligible' signal."""
        self._cancel_eligible_received = True

    @workflow.signal
    def cancel_ineligible(self) -> None:
        """Handle the 'CancelIneligible' signal."""
        self._cancel_ineligible_received = True

    @workflow.signal
    def in_flight_stopped(self) -> None:
        """Handle the 'InFlightStopped' signal."""
        self._in_flight_stopped_received = True

    @workflow.signal
    def deprovision_requested(self) -> None:
        """Handle the 'DeprovisionRequested' signal."""
        self._deprovision_requested_received = True

    @workflow.signal
    def deprovision_completed(self) -> None:
        """Handle the 'DeprovisionCompleted' signal."""
        self._deprovision_completed_received = True

    @workflow.signal
    def inventory_released(self) -> None:
        """Handle the 'InventoryReleased' signal."""
        self._inventory_released_received = True

    @workflow.signal
    def cancel_completed(self) -> None:
        """Handle the 'CancelCompleted' signal."""
        self._cancel_completed_received = True

    @workflow.query
    def get_cancellation_status(self) -> str:
        """Returns current cancellation status."""
        return self._status

    @workflow.query
    def get_deprovisioning_status(self) -> str:
        """Returns deprovisioning status."""
        return self._status
