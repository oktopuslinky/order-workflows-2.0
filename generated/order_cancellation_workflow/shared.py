"""Shared dataclasses for the OrderCancellationWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the OrderCancellationWorkflow workflow."""

    order_type: str = ""
    flow_type: str = ""
    cancel_scope: str = ""
    cancel_reason: str = ""
    requested_by: str = ""
    effective_date: str = ""
    target_item_ids: list = field(default_factory=list)
    authorization: str = ""
    x_correlation_id: str = ""
    idempotency_key: str = ""


@dataclass
class CancelRequestIntakeInput:
    """Input to the matching activity / child workflow."""

    order_type: str = ""
    cancel_scope: str = ""
    cancel_reason: str = ""
    requested_by: str = ""
    effective_date: str = ""
    target_item_ids: list = field(default_factory=list)
    authorization: str = ""


@dataclass
class EligibilityCheckInput:
    """Input to the matching activity / child workflow."""

    cancel_request_id: str = ""
    order_type: str = ""


@dataclass
class DeprovisioningInput:
    """Input to the matching activity / child workflow."""

    eligibility_status: str = ""
    cancel_request_id: str = ""


@dataclass
class InventoryReleaseInput:
    """Input to the matching activity / child workflow."""

    deprovision_status: str = ""
    cancel_request_id: str = ""


@dataclass
class PartialCancelCompensationInput:
    """Input to the matching activity / child workflow."""

    deprovision_status: str = ""
    cancel_request_id: str = ""
