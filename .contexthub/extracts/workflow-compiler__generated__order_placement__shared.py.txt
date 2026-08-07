"""Shared dataclasses for the OrderProcessingWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the OrderProcessingWorkflow workflow."""

    cart_id: int = 0
    customer_id: int = 0
    amount: float = 0.0
    currency: str = ""


@dataclass
class ValidateCartInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    cart_id: int = 0


@dataclass
class AuthorisePaymentInput:
    """Input to the matching activity / child workflow."""

    amount: float = 0.0
    currency: str = ""


@dataclass
class CreateOrderInput:
    """Input to the matching activity / child workflow."""

    cart_id: int = 0
    payment_authorisation_id: str = ""


@dataclass
class ReleaseInventoryInput:
    """Input to the matching activity / child workflow."""

    inventory_reservation_id: str = ""
