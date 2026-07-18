"""Shared dataclasses for the OrderFulfillmentWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the OrderFulfillmentWorkflow workflow."""

    cart_id: str = ""
    customer_id: str = ""
    amount: float = 0.0
    currency: str = ""


@dataclass
class ValidateCartInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    cart_id: str = ""


@dataclass
class AuthorisePaymentInput:
    """Input to the matching activity / child workflow."""

    amount: float = 0.0
    currency: str = ""


@dataclass
class CreateOrderRecordInput:
    """Input to the matching activity / child workflow."""

    cart_id: str = ""
    customer_id: str = ""


@dataclass
class ReleaseInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""


@dataclass
class SendOrderConfirmationEmailInput:
    """Input to the matching activity / child workflow."""

    customer_id: str = ""
    order_id: str = ""


@dataclass
class CompensateReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""


@dataclass
class StartOrderFulfilmentInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
