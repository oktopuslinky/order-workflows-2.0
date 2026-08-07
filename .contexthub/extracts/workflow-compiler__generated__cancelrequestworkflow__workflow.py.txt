"""The Cancelrequestworkflow Temporal workflow.

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
        cancelrequestintake,
        eligibilitycheck,
        deprovisioning,
        inventoryrelease,
        compensateremaininglegs,
    )
    from shared import (
        WorkflowInput,
        CancelrequestintakeInput,
        EligibilitycheckInput,
        DeprovisioningInput,
        InventoryreleaseInput,
        CompensateremaininglegsInput,
    )

DEPROVISION_TIMEOUT = timedelta(seconds=3600)  # Timeout for deprovisioning completion


@workflow.defn
class Cancelrequestworkflow:
    """Manages the cancellation of orders based on eligibility and inventory."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._cancel_requested_received: bool = False
        self._deprovision_requested_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            cancel_request_output = await workflow.execute_activity(
                cancel_request_intake,
                CancelRequestIntakeInput(order_id=arg.order_id, order_type=arg.order_type),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            eligibility_result = await workflow.execute_activity(
                eligibility_check,
                EligibilityCheckInput(request_id=cancel_request_output),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            if True:  # TODO: replace with real condition: eligibility_result.is_eligible
                deprovision_result = await workflow.execute_activity(
                    deprovisioning,
                    DeprovisioningInput(request_id=eligibility_result),
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1.5, maximum_attempts=2, non_retryable_error_types=['DeprovisionFailure']),
                )
                compensations.append((compensateremaininglegs, CompensateremaininglegsInput()))
                inventory_result = await workflow.execute_activity(
                    inventory_release,
                    InventoryReleaseInput(deprovision_status=deprovision_result),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
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
    def cancel_requested(self) -> None:
        """Handle the 'CancelRequested' signal."""
        self._cancel_requested_received = True

    @workflow.signal
    def deprovision_requested(self) -> None:
        """Handle the 'DeprovisionRequested' signal."""
        self._deprovision_requested_received = True

    @workflow.query
    def get_cancellation_status(self) -> str:
        """Query for current cancellation status"""
        return self._status
