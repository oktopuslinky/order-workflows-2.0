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
        cancel_refund,
        reverse_authorisation,
    )
    from shared import (
        WorkflowInput,
        AuthoriseReturnInput,
        ReceiveReturnedItemInput,
        IssueRefundInput,
        CancelRefundInput,
        ReverseAuthorisationInput,
    )



@workflow.defn
class ReturnProcessingWorkflow:
    """Manages the return processing workflow from authorisation to refund."""

    def __init__(self) -> None:
        self._status: str = "pending"
        # Read-only debug surface (safe in production: no I/O, no wall-clock).
        self._current_step: str = ""
        self._decisions_taken: list[dict[str, object]] = []
        self._triggers_fired: list[str] = []

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            self._current_step = 'A1'
            workflow.logger.info("Running step: AuthoriseReturn")
            authorisation_result = await workflow.execute_activity(
                authorise_return,
                AuthoriseReturnInput(order_id=arg.order_id, shipment_id=arg.shipment_id, reason_code=arg.reason_code),
                start_to_close_timeout=timedelta(seconds=10),
            )
            compensations.append((reverse_authorisation, ReverseAuthorisationInput(return_id=authorisation_result)))
            self._current_step = 'D1'
            should_authorisation_result_return_id_is_not_null = True  # TODO: set from a real condition: authorisation_result.return_id is not null
            if should_authorisation_result_return_id_is_not_null:
                self._decisions_taken.append({'branch': 'D1', 'predicate': 'authorisation_result.return_id is not null', 'taken': True})
                self._current_step = 'A2'
                workflow.logger.info("Running step: ReceiveReturnedItem")
                a2_result = await workflow.execute_activity(
                    receive_returned_item,
                    ReceiveReturnedItemInput(shipment_id=arg.shipment_id, return_id=authorisation_result),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=3),
                )
                self._current_step = 'A3'
                workflow.logger.info("Running step: IssueRefund")
                refund_result = await workflow.execute_activity(
                    issue_refund,
                    IssueRefundInput(order_id=arg.order_id, return_id=authorisation_result),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5),
                )
                compensations.append((cancel_refund, CancelRefundInput(refund_id=refund_result)))
            else:
                self._decisions_taken.append({'branch': 'D1', 'predicate': 'authorisation_result.return_id is not null', 'taken': False})
                self._current_step = 'E1'
                workflow.logger.info("Running step: ReverseAuthorisation")
                e1_result = await workflow.execute_activity(
                    reverse_authorisation,
                    ReverseAuthorisationInput(return_id=authorisation_result),
                    start_to_close_timeout=timedelta(seconds=60),
                )
            self._current_step = 'C1'
            workflow.logger.info("Running step: CancelRefund")
            c1_result = await workflow.execute_activity(
                cancel_refund,
                CancelRefundInput(refund_id=refund_result),
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
