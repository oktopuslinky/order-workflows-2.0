"""The PaymentReconciliationWorkflow Temporal workflow.

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
        fetch_settlement_record,
        fetch_order_total,
        compare_amounts,
        mark_reconciled,
        file_discrepancy_report,
        unmark_reconciled,
    )
    from shared import (
        WorkflowInput,
        FetchSettlementRecordInput,
        FetchOrderTotalInput,
        CompareAmountsInput,
        MarkReconciledInput,
        FileDiscrepancyReportInput,
        UnmarkReconciledInput,
    )



@workflow.defn
class PaymentReconciliationWorkflow:
    """Reconciles payment and order totals, reporting discrepancies."""

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
            workflow.logger.info("Running step: FetchSettlementRecord")
            settlement = await workflow.execute_activity(
                fetch_settlement_record,
                FetchSettlementRecordInput(payment_id=arg.payment_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2, maximum_attempts=3),
            )
            self._current_step = 'A2'
            workflow.logger.info("Running step: FetchOrderTotal")
            order_total_result = await workflow.execute_activity(
                fetch_order_total,
                FetchOrderTotalInput(order_id=arg.order_id),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2, maximum_attempts=3),
            )
            self._current_step = 'A3'
            workflow.logger.info("Running step: CompareAmounts")
            comparison_result = await workflow.execute_activity(
                compare_amounts,
                CompareAmountsInput(settlement_amount=settlement, order_total=order_total_result),
                start_to_close_timeout=timedelta(seconds=60),
            )
            self._current_step = 'D1'
            should_comparison_result_is_match = True  # TODO: set from a real condition: comparison_result.is_match
            if should_comparison_result_is_match:
                self._decisions_taken.append({'branch': 'D1', 'predicate': 'comparison_result.is_match', 'taken': True})
                self._current_step = 'A4'
                workflow.logger.info("Running step: MarkReconciled")
                a4_result = await workflow.execute_activity(
                    mark_reconciled,
                    MarkReconciledInput(payment_id=arg.payment_id),
                    start_to_close_timeout=timedelta(seconds=15),
                )
                compensations.append((unmark_reconciled, UnmarkReconciledInput(payment_id=arg.payment_id)))
            else:
                self._decisions_taken.append({'branch': 'D1', 'predicate': 'comparison_result.is_match', 'taken': False})
                self._current_step = 'A5'
                workflow.logger.info("Running step: FileDiscrepancyReport")
                discrepancy_report = await workflow.execute_activity(
                    file_discrepancy_report,
                    FileDiscrepancyReportInput(payment_id=arg.payment_id, order_id=arg.order_id),
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
    def get_reconciliation_status(self) -> str:
        """Query current reconciliation status"""
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
