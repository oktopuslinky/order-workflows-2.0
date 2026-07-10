"""Shared dataclasses for the OrderSettlementWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the OrderSettlementWorkflow workflow."""

    order_id: str = ""
    customer_id: str = ""
    amount: float = 0.0
    currency: str = ""


@dataclass
class ValidateOrderInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class ChargePaymentInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    amount: float = 0.0
    currency: str = ""


@dataclass
class NotifyCustomerInput:
    """Input to the matching activity / child workflow."""

    customer_id: str = ""


@dataclass
class RecordSettlementEventInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class WaitForShippingConfirmationInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class FinaliseSettlementInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class ReleaseInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""


@dataclass
class RefundPaymentInput:
    """Input to the matching activity / child workflow."""

    payment_id: str = ""
