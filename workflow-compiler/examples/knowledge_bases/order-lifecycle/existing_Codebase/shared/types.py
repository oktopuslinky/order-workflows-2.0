"""
Shared data contracts for the Order Lifecycle Workflow.

These dataclasses are used as Temporal workflow/activity inputs and outputs.
Keeping them in a dedicated module (rather than defining them inline) means
both the workflow and activities can import from the same source of truth,
and it keeps workflow code free of business-object construction logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    PROVISIONING = "PROVISIONING"
    PROVISIONED = "PROVISIONED"
    DISPATCHING = "DISPATCHING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class LineItem:
    sku: str
    quantity: int
    unit_price: float


@dataclass
class ShippingAddress:
    line1: str
    city: str
    state: str
    postal_code: str
    country: str


@dataclass
class OrderRequest:
    """Inbound payload used to start the workflow (see US-001)."""

    order_id: str
    customer_id: str
    line_items: list[LineItem]
    shipping_address: ShippingAddress
    payment_token: str


@dataclass
class ValidationResult:
    passed: bool
    reason_code: Optional[str] = None  # e.g. INVENTORY_UNAVAILABLE, PAYMENT_DECLINED, FRAUD_HOLD


@dataclass
class ProvisioningResult:
    reservation_id: str
    warehouse_id: str


@dataclass
class DispatchResult:
    tracking_number: str
    carrier: str
    label_url: str
    idempotency_key: str


@dataclass
class CompletionResult:
    invoice_id: str
    delivered_at: datetime


@dataclass
class OrderState:
    """The queryable projection returned by OrderWorkflow.get_status() (BR-09)."""

    order_id: str
    status: OrderStatus
    failure_reason: Optional[str] = None
    received_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None
    provisioned_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tracking_number: Optional[str] = None
    invoice_id: Optional[str] = None
    history: list[str] = field(default_factory=list)
