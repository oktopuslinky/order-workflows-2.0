"""Shared dataclasses for the ReturnProcessingWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the ReturnProcessingWorkflow workflow."""

    order_id: str = ""
    shipment_id: str = ""
    reason_code: str = ""


@dataclass
class AuthoriseReturnInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    shipment_id: str = ""
    reason_code: str = ""


@dataclass
class ReceiveReturnedItemInput:
    """Input to the matching activity / child workflow."""

    shipment_id: str = ""
    return_id: str = ""


@dataclass
class IssueRefundInput:
    """Input to the matching activity / child workflow."""

    order_id: str = ""
    return_id: str = ""


@dataclass
class CancelRefundInput:
    """Input to the matching activity / child workflow."""

    refund_id: str = ""
