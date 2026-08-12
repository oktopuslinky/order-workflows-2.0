"""Shared cross-workflow contracts for this project.

One typed input dataclass per workflow. Each workflow's own bundle
defines the identical shape in its shared.py (bundles stay standalone);
this file is the single project-wide reference for trigger payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderFulfillmentWorkflowInput:
    """Input to the standalone 'order-fulfillment-workflow' workflow."""

    customer_order: dict = field(default_factory=dict)
    order_id: str = ""