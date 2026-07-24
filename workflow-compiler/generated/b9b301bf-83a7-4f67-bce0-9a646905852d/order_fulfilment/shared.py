"""Shared dataclasses for the FulfilmentWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the FulfilmentWorkflow workflow."""

    order_id: str = ""
    authorization_id: str = ""


@dataclass
class PickOrderItemsInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class PackShipmentInput:
    """Input to the matching activity / child workflow."""

    pick_list_id: str = ""


@dataclass
class DispatchShipmentInput:
    """Input to the matching activity / child workflow."""

    package_id: str = ""


@dataclass
class CapturePaymentInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    authorization_id: str = ""


@dataclass
class RecordFulfilmentLedgerEntryInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""
    payment_id: str = ""


@dataclass
class UnpackShipmentInput:
    """Input to the matching activity / child workflow."""

    package_id: str = ""


@dataclass
class RefundCapturedPaymentInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""


@dataclass
class StartPaymentReconciliationInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""
