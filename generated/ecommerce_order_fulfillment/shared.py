"""Shared dataclasses for the EcommerceOrderFulfillment workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the EcommerceOrderFulfillment workflow."""

    cart_id: str = ""
    customer_id: str = ""
    amount: float = 0.0
    currency: str = ""
    order_id: str = ""
    shipment_id: str = ""
    reason_code: str = ""


@dataclass
class ValidateCartInput:
    """Input to the matching activity / child workflow."""

    cart_id: str = ""


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class AuthorisePaymentInput:
    """Input to the matching activity / child workflow."""

    amount: float = 0.0
    currency: str = ""


@dataclass
class CreateOrderInput:
    """Input to the matching activity / child workflow."""

    customer_id: str = ""
    cart_id: str = ""


@dataclass
class PickItemsInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class PackShipmentInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class DispatchShipmentInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""


@dataclass
class CapturePaymentInput:
    """Input to the matching activity / child workflow."""

    payment_authorisation_id: str = ""


@dataclass
class AuthoriseReturnInput:
    """Input to the matching activity / child workflow."""

    reason_code: str = ""
    order_id: str = ""


@dataclass
class ReceiveReturnedItemInput:
    """Input to the matching activity / child workflow."""

    return_id: str = ""


@dataclass
class IssueRefundInput:
    """Input to the matching activity / child workflow."""

    payment_capture_id: str = ""


@dataclass
class ReleaseInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""


@dataclass
class UnpackShipmentInput:
    """Input to the matching activity / child workflow."""

    shipment_pack_status: str = ""
