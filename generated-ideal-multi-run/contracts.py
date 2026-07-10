"""Shared cross-workflow contracts for this project.

One typed input dataclass per workflow. Each workflow's own bundle
defines the identical shape in its shared.py (bundles stay standalone);
this file is the single project-wide reference for trigger payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderFulfilmentWorkflowInput:
    """Input to the standalone 'order-fulfilment' workflow."""

    order_id: str = ""
    authorization_id: str = ""


@dataclass
class EcommerceOrderWorkflowInput:
    """Input to the standalone 'order-placement' workflow."""

    cart_id: int = 0
    customer_id: int = 0
    amount: float = 0.0
    currency: str = ""


@dataclass
class ReturnProcessingWorkflowInput:
    """Input to the standalone 'order-return' workflow."""

    order_id: str = ""
    shipment_id: str = ""
    reason_code: str = ""