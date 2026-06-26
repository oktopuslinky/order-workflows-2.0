"""Shared dataclasses for the Subscriptionupgradeworkflow workflow.

Temporal passes a single dataclass argument to workflows and activities so that
inputs evolve compatibly. Refine the field types to match your real domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Input to the Subscriptionupgradeworkflow workflow."""

    subscription_id: str = ""
    target_plan_id: str = ""
    effective_date: str = ""
    requested_by: str = ""
    promo_code: str = ""


@dataclass
class ValidaterequestpayloadInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ResolvetargetplanInput:
    """Input to the matching activity / child workflow."""

    plan_id: str = ""


@dataclass
class ChecksubscriptioneligibilityInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""


@dataclass
class CalculateprorationamountInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    effective_date: str = ""


@dataclass
class ValidatepromotionaldiscountInput:
    """Input to the matching activity / child workflow."""

    promo_code: str = ""
    proration_amount: float = 0.0


@dataclass
class PreauthoriseprorationchargeInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    amount: float = 0.0


@dataclass
class UpdateentitlementsInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class ReprovisionserviceInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class UpdateresourceinventoryInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class CapturepreauthorisedchargeInput:
    """Input to the matching activity / child workflow."""

    pre_auth_id: str = ""


@dataclass
class PublisheventsInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class SendupgradeconfirmationInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class RecordupgradeaudittrailInput:
    """Input to the matching activity / child workflow."""

    subscription_id: str = ""
    new_plan_id: str = ""


@dataclass
class RestoreoldentitlementsInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ReprovisionwitholdplanInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class RestoreoldresourcereservationInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ReleasepreauthorisationInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class ReversechargecaptureInput:
    """Input to the matching activity / child workflow."""

    pass


@dataclass
class PublishrollbackeventInput:
    """Input to the matching activity / child workflow."""

    pass
