"""Activities for the SubscriptionUpgradeWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    ValidateRequestPayloadInput,
    ResolveTargetPlanInput,
    CheckSubscriptionEligibilityInput,
    CalculateProrationAmountInput,
    ValidateAndApplyPromotionalDiscountInput,
    PreAuthoriseProrationChargeInput,
    UpdateEntitlementsInput,
    ReProvisionServiceInput,
    UpdateResourceInventoryInput,
    CapturePreAuthorisedChargeInput,
    PublishEventsInput,
    SendUpgradeConfirmationInput,
    RecordAuditTrailInput,
    RestoreOldEntitlementsInput,
    ReProvisionWithOldPlanInput,
    RestoreOldResourceReservationInput,
    ReleasePreAuthorisationInput,
    ReverseChargeCaptureInput,
    PublishRollbackEventInput,
)


@activity.defn(name="ValidateRequestPayload")
async def validate_request_payload(arg: ValidateRequestPayloadInput) -> str:
    """Validate incoming request data."""
    activity.logger.info("Running validate_request_payload", extra={"input": arg})
    # TODO: implement validate_request_payload. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ResolveTargetPlan")
async def resolve_target_plan(arg: ResolveTargetPlanInput) -> str:
    """Fetch target plan details from catalog."""
    activity.logger.info("Running resolve_target_plan", extra={"input": arg})
    # TODO: implement resolve_target_plan. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="CheckSubscriptionEligibility")
async def check_subscription_eligibility(arg: CheckSubscriptionEligibilityInput) -> str:
    """Determine if subscription is eligible for upgrade."""
    activity.logger.info("Running check_subscription_eligibility", extra={"input": arg})
    # TODO: implement check_subscription_eligibility. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="CalculateProrationAmount")
async def calculate_proration_amount(arg: CalculateProrationAmountInput) -> str:
    """Calculate prorated charge for the upgrade."""
    activity.logger.info("Running calculate_proration_amount", extra={"input": arg})
    # TODO: implement calculate_proration_amount. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ValidateAndApplyPromotionalDiscount")
async def validate_and_apply_promotional_discount(arg: ValidateAndApplyPromotionalDiscountInput) -> str:
    """Validate promo code and apply discount if valid."""
    activity.logger.info("Running validate_and_apply_promotional_discount", extra={"input": arg})
    # TODO: implement validate_and_apply_promotional_discount. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PreAuthoriseProrationCharge")
async def pre_authorise_proration_charge(arg: PreAuthoriseProrationChargeInput) -> str:
    """Pre-authorise the prorated charge with the payment gateway."""
    activity.logger.info("Running pre_authorise_proration_charge", extra={"input": arg})
    # TODO: implement pre_authorise_proration_charge. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="UpdateEntitlements")
async def update_entitlements(arg: UpdateEntitlementsInput) -> str:
    """Update user entitlements to reflect the new plan."""
    activity.logger.info("Running update_entitlements", extra={"input": arg})
    # TODO: implement update_entitlements. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReProvisionService")
async def re_provision_service(arg: ReProvisionServiceInput) -> str:
    """Re-provision the service with the new plan configuration."""
    activity.logger.info("Running re_provision_service", extra={"input": arg})
    # TODO: implement re_provision_service. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="UpdateResourceInventory")
async def update_resource_inventory(arg: UpdateResourceInventoryInput) -> str:
    """Update inventory to reflect resource changes."""
    activity.logger.info("Running update_resource_inventory", extra={"input": arg})
    # TODO: implement update_resource_inventory. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="CapturePreAuthorisedCharge")
async def capture_pre_authorised_charge(arg: CapturePreAuthorisedChargeInput) -> str:
    """Capture the pre-authorised payment."""
    activity.logger.info("Running capture_pre_authorised_charge", extra={"input": arg})
    # TODO: implement capture_pre_authorised_charge. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PublishEvents")
async def publish_events(arg: PublishEventsInput) -> str:
    """Publish upgrade events to the event bus."""
    activity.logger.info("Running publish_events", extra={"input": arg})
    # TODO: implement publish_events. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="SendUpgradeConfirmation")
async def send_upgrade_confirmation(arg: SendUpgradeConfirmationInput) -> str:
    """Notify the user of the successful upgrade."""
    activity.logger.info("Running send_upgrade_confirmation", extra={"input": arg})
    # TODO: implement send_upgrade_confirmation. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="RecordAuditTrail")
async def record_audit_trail(arg: RecordAuditTrailInput) -> str:
    """Log the upgrade in the audit archive."""
    activity.logger.info("Running record_audit_trail", extra={"input": arg})
    # TODO: implement record_audit_trail. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="RestoreOldEntitlements")
async def restore_old_entitlements(arg: RestoreOldEntitlementsInput) -> str:
    """Restore entitlements to their previous state."""
    activity.logger.info("Running restore_old_entitlements", extra={"input": arg})
    # TODO: implement restore_old_entitlements. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReProvisionWithOldPlan")
async def re_provision_with_old_plan(arg: ReProvisionWithOldPlanInput) -> str:
    """Re-provision with the old plan configuration."""
    activity.logger.info("Running re_provision_with_old_plan", extra={"input": arg})
    # TODO: implement re_provision_with_old_plan. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="RestoreOldResourceReservation")
async def restore_old_resource_reservation(arg: RestoreOldResourceReservationInput) -> str:
    """Restore resource inventory to previous state."""
    activity.logger.info("Running restore_old_resource_reservation", extra={"input": arg})
    # TODO: implement restore_old_resource_reservation. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReleasePreAuthorisation")
async def release_pre_authorisation(arg: ReleasePreAuthorisationInput) -> str:
    """Release the pre-authorised payment."""
    activity.logger.info("Running release_pre_authorisation", extra={"input": arg})
    # TODO: implement release_pre_authorisation. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReverseChargeCapture")
async def reverse_charge_capture(arg: ReverseChargeCaptureInput) -> str:
    """Reverse the captured charge."""
    activity.logger.info("Running reverse_charge_capture", extra={"input": arg})
    # TODO: implement reverse_charge_capture. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PublishRollbackEvent")
async def publish_rollback_event(arg: PublishRollbackEventInput) -> str:
    """Publish rollback event to the event bus."""
    activity.logger.info("Running publish_rollback_event", extra={"input": arg})
    # TODO: implement publish_rollback_event. Returns a placeholder so the bundle runs as-is.
    return ""
