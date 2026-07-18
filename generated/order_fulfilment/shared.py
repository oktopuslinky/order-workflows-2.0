"""Shared dataclasses for the OrderFulfilmentWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the OrderFulfilmentWorkflow workflow."""

    order_id: str = ""
    authorization_id: str = ""


@dataclass
class PickItemsInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""


@dataclass
class PackShipmentInput:
    """Input to the matching activity / child workflow."""

    picked_items: str = ""


@dataclass
class DispatchShipmentInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""


@dataclass
class CapturePaymentInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    authorization_id: str = ""


@dataclass
class WaitForCarrierPickupConfirmationInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""


@dataclass
class UnpackShipmentInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""
