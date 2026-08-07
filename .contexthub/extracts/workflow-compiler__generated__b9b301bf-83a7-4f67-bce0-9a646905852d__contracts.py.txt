"""Shared cross-workflow contracts for this project.

One typed input dataclass per workflow. Each workflow's own bundle
defines the identical shape in its shared.py (bundles stay standalone);
this file is the single project-wide reference for trigger payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FulfilmentWorkflowInput:
    """Input to the standalone 'order-fulfilment' workflow."""

    order_id: str = ""
    authorization_id: str = ""


@dataclass
class OrderFulfillmentWorkflowInput:
    """Input to the standalone 'order-placement' workflow."""

    cart_id: str = ""
    customer_id: str = ""
    amount: float = 0.0
    currency: str = ""


@dataclass
class PaymentReconciliationWorkflowInput:
    """Input to the standalone 'payment-reconciliation' workflow."""

    payment_id: str = ""
    order_id: str = ""