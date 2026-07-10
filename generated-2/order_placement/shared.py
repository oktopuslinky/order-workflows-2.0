"""Shared dataclasses for the EcommerceOrderWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the EcommerceOrderWorkflow workflow."""

    cart_id: str = ""
    customer_id: str = ""
    amount: float = 0.0
    currency: str = ""


@dataclass
class ValidateCartInput:
    """Input to the matching activity / child workflow."""

    cart_id: str = ""


@dataclass
class ReserveInventoryInput:
    """Input to the matching activity / child workflow."""

    cart_id: str = ""


@dataclass
class AuthorisePaymentInput:
    """Input to the matching activity / child workflow."""

    amount: float = 0.0
    currency: str = ""


@dataclass
class CreateOrderInput:
    """Input to the matching activity / child workflow."""

    cart_id: str = ""
    authorisation_id: str = ""


@dataclass
class ReleaseInventoryReservationInput:
    """Input to the matching activity / child workflow."""

    reservation_id: str = ""
