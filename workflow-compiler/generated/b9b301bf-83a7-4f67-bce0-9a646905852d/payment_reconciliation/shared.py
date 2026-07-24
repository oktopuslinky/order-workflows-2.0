"""Shared dataclasses for the PaymentReconciliationWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the PaymentReconciliationWorkflow workflow."""

    payment_id: str = ""
    order_id: str = ""


@dataclass
class FetchSettlementRecordInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""


@dataclass
class FetchOrderTotalInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class CompareAmountsInput:
    """Input to the matching activity / child workflow."""

    settlement_amount: float = 0.0
    order_total: float = 0.0


@dataclass
class MarkReconciledInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""


@dataclass
class FileDiscrepancyReportInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""
    order_id: str = ""
    discrepancy_details: str = ""


@dataclass
class UnmarkReconciledInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""
