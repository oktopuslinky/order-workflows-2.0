"""Shared dataclasses for the SubscriptionUpgradeWorkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the SubscriptionUpgradeWorkflow workflow."""

    subscription_id: str = ""
    target_plan_id: str = ""
    effective_date: str = ""
    requested_by: str = ""
    promo_code: str = ""


@dataclass
class ValidateRequestPayloadInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ResolveTargetPlanInput:
    """Input to the matching activity / child workflow."""

    plan_id: str = ""


@dataclass
class CheckSubscriptionEligibilityInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class CalculateProrationAmountInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    effective_date: str = ""


@dataclass
class ValidateAndApplyPromotionalDiscountInput:
    """Input to the matching activity / child workflow."""

    promo_code: str = ""


@dataclass
class PreAuthoriseProrationChargeInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    amount: float = 0.0


@dataclass
class UpdateEntitlementsInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class ReProvisionServiceInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class UpdateResourceInventoryInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class CapturePreAuthorisedChargeInput:
    """Input to the matching activity / child workflow."""

    pre_auth_id: str = ""


@dataclass
class PublishEventsInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class SendUpgradeConfirmationInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class RecordAuditTrailInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class RestoreOldEntitlementsInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    old_plan_id: str = ""


@dataclass
class ReProvisionWithOldPlanInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class RestoreOldResourceReservationInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class ReleasePreAuthorisationInput:
    """Input to the matching activity / child workflow."""

    pre_auth_id: str = ""


@dataclass
class ReverseChargeCaptureInput:
    """Input to the matching activity / child workflow."""

    charge_id: str = ""


@dataclass
class PublishRollbackEventInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
