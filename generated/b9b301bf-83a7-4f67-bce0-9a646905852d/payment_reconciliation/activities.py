"""Activities for the PaymentReconciliationWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    FetchSettlementRecordInput,
    FetchOrderTotalInput,
    CompareAmountsInput,
    MarkReconciledInput,
    FileDiscrepancyReportInput,
    UnmarkReconciledInput,
)


@activity.defn(name="FetchSettlementRecord")
async def fetch_settlement_record(arg: FetchSettlementRecordInput) -> str:
    """Retrieve settlement record from Payment Gateway"""
    activity.logger.info("Running fetch_settlement_record", extra={"input": arg})
    # TODO: implement fetch_settlement_record. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="FetchOrderTotal")
async def fetch_order_total(arg: FetchOrderTotalInput) -> str:
    """Retrieve order total from Order Service"""
    activity.logger.info("Running fetch_order_total", extra={"input": arg})
    # TODO: implement fetch_order_total. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CompareAmounts")
async def compare_amounts(arg: CompareAmountsInput) -> str:
    """Compare settlement and order amounts"""
    activity.logger.info("Running compare_amounts", extra={"input": arg})
    # TODO: implement compare_amounts. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="MarkReconciled")
async def mark_reconciled(arg: MarkReconciledInput) -> str:
    """Mark payment as reconciled in the system"""
    activity.logger.info("Running mark_reconciled", extra={"input": arg})
    # TODO: implement mark_reconciled. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="FileDiscrepancyReport")
async def file_discrepancy_report(arg: FileDiscrepancyReportInput) -> str:
    """File report and notify on discrepancy"""
    activity.logger.info("Running file_discrepancy_report", extra={"input": arg})
    # TODO: implement file_discrepancy_report. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="UnmarkReconciled")
async def unmark_reconciled(arg: UnmarkReconciledInput) -> str:
    """Undo mark reconciled in case of failure"""
    activity.logger.info("Running unmark_reconciled", extra={"input": arg})
    # TODO: implement unmark_reconciled. Returns a placeholder so the bundle runs as-is.
    return "stub-result"
