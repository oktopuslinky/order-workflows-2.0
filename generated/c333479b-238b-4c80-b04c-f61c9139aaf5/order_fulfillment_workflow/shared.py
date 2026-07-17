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

    order_id: str = ""
    customer_info: str = ""
    order_value: float = 0.0
    items: str = ""


@dataclass
class ValidateOrderAndPaymentInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    customer_info: str = ""


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    items: str = ""


@dataclass
class SendOrderConfirmationInput:
    """Input to the matching activity / child workflow."""

    customer_info: str = ""
    order_id: str = ""


@dataclass
class NotifyWarehouseInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class PickAndPackItemsInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class CreateShipmentViaCarrierAPIInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    customer_info: str = ""


@dataclass
class ShipOrderInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""


@dataclass
class ReleaseReservedInventoryInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class ObtainManagerApprovalInput:
    """Input to the matching activity / child workflow."""

    order_value: float = 0.0
    order_id: str = ""


@dataclass
class NotifyFinanceTeamInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    order_value: float = 0.0


@dataclass
class CompensateReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
