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

    customer_order: dict = field(default_factory=dict)
    order_id: str = ""
    customer_order_items: list = field(default_factory=list)
    customer_email: str = ""


@dataclass
class ValidateOrderAndPaymentInput:
    """Input to the matching activity / child workflow."""

    order: dict = field(default_factory=dict)


@dataclass
class CancelOrderInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    order_items: list = field(default_factory=list)


@dataclass
class SendOrderConfirmationInput:
    """Input to the matching activity / child workflow."""

    customer_email: str = ""
    order_summary: str = ""


@dataclass
class NotifyWarehouseInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class PickAndPackItemsInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class CreateShipmentInput:
    """Input to the matching activity / child workflow."""

    packing_slip_id: str = ""


@dataclass
class ReleaseInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""


@dataclass
class ObtainManagerApprovalInput:
    """Input to the matching activity / child workflow."""

    order_value: float = 0.0


@dataclass
class EmailCustomerTrackingLinkInput:
    """Input to the matching activity / child workflow."""

    customer_email: str = ""
    tracking_link: str = ""


@dataclass
class NotifyCustomerOfDelayInput:
    """Input to the matching activity / child workflow."""

    customer_email: str = ""
    delay_reason: str = ""


@dataclass
class CompensateReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""


@dataclass
class NotifyCustomerOfSLABreachInput:
    """Input to the matching activity / child workflow."""

    customer_email: str = ""
    delay_reason: str = ""