"""The ReturnProcessingWorkflow Temporal workflow.

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
        authorise_return,
        receive_returned_item,
        issue_refund,
        cancel_return_process,
    )
    from shared import (
        WorkflowInput,
        AuthoriseReturnInput,
        ReceiveReturnedItemInput,
        IssueRefundInput,
        CancelReturnProcessInput,
    )



@workflow.defn
class ReturnProcessingWorkflow:
    """Manages the return processing workflow from authorisation to refund."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._return_requested_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            workflow.logger.info("Waiting for signal: return.requested")
            # TODO: pass timeout= to wait_condition so a signal that never arrives can't block the workflow forever.
            await workflow.wait_condition(lambda: self._return_requested_received)
            workflow.logger.info("Running step: AuthoriseReturn")
            authorisation_result = await workflow.execute_activity(
                authorise_return,
                AuthoriseReturnInput(order_id=arg.order_id, shipment_id=arg.shipment_id, reason_code=arg.reason_code),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=1, maximum_attempts=2, non_retryable_error_types=['ReturnNotEligible']),
            )
            compensations.append((cancel_return_process, CancelReturnProcessInput(return_id=authorisation_result)))
            should_authorisation_result_return_id_is_not_null = True  # TODO: set from a real condition: authorisation_result.return_id is not null
            if should_authorisation_result_return_id_is_not_null:
                workflow.logger.info("Running step: ReceiveReturnedItem")
                receipt_confirmation = await workflow.execute_activity(
                    receive_returned_item,
                    ReceiveReturnedItemInput(shipment_id=arg.shipment_id, return_id=authorisation_result),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                workflow.logger.info("Running step: IssueRefund")
                refund_result = await workflow.execute_activity(
                    issue_refund,
                    IssueRefundInput(order_id=arg.order_id, return_id=authorisation_result),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5, non_retryable_error_types=['RefundFailed']),
                )
            else:
                # Wait until: true
                await workflow.wait_condition(lambda: True)  # TODO: real condition
            workflow.logger.info("Running step: CancelReturnProcess")
            c1_result = await workflow.execute_activity(
                cancel_return_process,
                CancelReturnProcessInput(return_id=authorisation_result),
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
    def return_requested(self) -> None:
        """Handle the 'return.requested' signal."""
        self._return_requested_received = True

    @workflow.query
    def get_return_status(self) -> str:
        """Query the current return status."""
        return self._status
