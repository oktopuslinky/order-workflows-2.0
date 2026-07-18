"""The SubscriptionUpgradeWorkflow Temporal workflow.

Workflow code must be deterministic: do all I/O inside activities, and use
``workflow.*`` helpers (``execute_activity``, ``execute_child_workflow``,
``sleep``, signals, queries) rather than calling the outside world directly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        validate_request_payload,
        resolve_target_plan,
        check_subscription_eligibility,
        calculate_proration_amount,
        validate_and_apply_promotional_discount,
        pre_authorise_proration_charge,
        update_entitlements,
        re_provision_service,
        update_resource_inventory,
        capture_pre_authorised_charge,
        publish_events,
        send_upgrade_confirmation,
        record_audit_trail,
        restore_old_entitlements,
        re_provision_with_old_plan,
        restore_old_resource_reservation,
        release_pre_authorisation,
        reverse_charge_capture,
        publish_rollback_event,
    )
    from shared import (
        WorkflowInput,
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

REQUEST_VALIDATION_TIMEOUT = timedelta(seconds=5)  # Timeout for request payload validation.
PLAN_RESOLUTION_TIMEOUT = timedelta(seconds=10)  # Timeout for resolving the target plan.
ELIGIBILITY_CHECK_TIMEOUT = timedelta(seconds=15)  # Timeout for checking subscription eligibility.
PRE_AUTH_TIMEOUT = timedelta(seconds=30)  # Timeout for pre-authorising the charge.
RE_PROVISIONING_TIMEOUT = timedelta(seconds=600)  # Timeout for service re-provisioning.
WORKFLOW_TIMEOUT = timedelta(seconds=1800)  # Overall workflow timeout.
PROMO_CODE_VALIDATION_TIMEOUT = timedelta(seconds=5)  # Timeout for validating the promo code.


@workflow.defn
class SubscriptionUpgradeWorkflow:
    """Manages the upgrade of a subscription, including validation, billing, and provisioning."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._oms_subscription_upgrade_rejected_received: bool = False
        self._oms_subscription_upgrade_started_received: bool = False
        self._oms_subscription_upgrade_completed_received: bool = False
        self._oms_subscription_upgrade_rolled_back_received: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            workflow.logger.info("Running step: ValidateRequestPayload")
            is_valid = await workflow.execute_activity(
                validate_request_payload,
                ValidateRequestPayloadInput(),
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            workflow.logger.info("Running step: ResolveTargetPlan")
            plan_details = await workflow.execute_activity(
                resolve_target_plan,
                ResolveTargetPlanInput(plan_id=arg.target_plan_id),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2, maximum_attempts=2),
            )
            workflow.logger.info("Running step: CheckSubscriptionEligibility")
            is_eligible = await workflow.execute_activity(
                check_subscription_eligibility,
                CheckSubscriptionEligibilityInput(subscription_id=arg.subscription_id),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            should_is_eligible_true = True  # TODO: set from a real condition: isEligible == True
            if should_is_eligible_true:
                workflow.logger.info("Running step: CalculateProrationAmount")
                proration_amount = await workflow.execute_activity(
                    calculate_proration_amount,
                    CalculateProrationAmountInput(subscription_id=arg.subscription_id, effective_date=arg.effective_date),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2, maximum_attempts=2),
                )
                workflow.logger.info("Running step: ValidateAndApplyPromotionalDiscount")
                discount_applied = await workflow.execute_activity(
                    validate_and_apply_promotional_discount,
                    ValidateAndApplyPromotionalDiscountInput(promo_code=arg.promo_code),
                    start_to_close_timeout=timedelta(seconds=5),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                workflow.logger.info("Running step: PreAuthoriseProrationCharge")
                pre_auth_id = await workflow.execute_activity(
                    pre_authorise_proration_charge,
                    PreAuthoriseProrationChargeInput(subscription_id=arg.subscription_id, amount=proration_amount),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=10), backoff_coefficient=2, maximum_attempts=1, non_retryable_error_types=['PAYMENTPREAUTH_FAILED']),
                )
                compensations.append((release_pre_authorisation, ReleasePreAuthorisationInput(pre_auth_id=pre_auth_id)))
                should_pre_auth_id_is_not_none = True  # TODO: set from a real condition: preAuthId is not None
                if should_pre_auth_id_is_not_none:
                    workflow.logger.info("Running step: UpdateEntitlements")
                    s9_result = await workflow.execute_activity(
                        update_entitlements,
                        UpdateEntitlementsInput(subscription_id=arg.subscription_id, new_plan_id=plan_details),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    compensations.append((restore_old_entitlements, RestoreOldEntitlementsInput(subscription_id=is_valid, old_plan_id=arg.subscription_id)))
                    workflow.logger.info("Running step: ReProvisionService")
                    s10_result = await workflow.execute_activity(
                        re_provision_service,
                        ReProvisionServiceInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=600),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3, non_retryable_error_types=['ProvisioningTimeout']),
                    )
                    compensations.append((re_provision_with_old_plan, ReProvisionWithOldPlanInput(subscription_id=is_valid)))
                    workflow.logger.info("Running step: UpdateResourceInventory")
                    s11_result = await workflow.execute_activity(
                        update_resource_inventory,
                        UpdateResourceInventoryInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=10), backoff_coefficient=2, maximum_attempts=3),
                    )
                    compensations.append((restore_old_resource_reservation, RestoreOldResourceReservationInput(subscription_id=is_valid)))
                    workflow.logger.info("Running step: CapturePreAuthorisedCharge")
                    s12_result = await workflow.execute_activity(
                        capture_pre_authorised_charge,
                        CapturePreAuthorisedChargeInput(pre_auth_id=pre_auth_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=15), backoff_coefficient=2, maximum_attempts=2, non_retryable_error_types=['ChargeCaptureFailure']),
                    )
                    compensations.append((reverse_charge_capture, ReverseChargeCaptureInput(charge_id=s12_result)))
                    workflow.logger.info("Running step: PublishEvents")
                    s13_result = await workflow.execute_activity(
                        publish_events,
                        PublishEventsInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    )
                    compensations.append((publish_rollback_event, PublishRollbackEventInput(subscription_id=is_valid)))
                    workflow.logger.info("Running step: SendUpgradeConfirmation")
                    s14_result = await workflow.execute_activity(
                        send_upgrade_confirmation,
                        SendUpgradeConfirmationInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=5),
                    )
                    workflow.logger.info("Running step: RecordAuditTrail")
                    s15_result = await workflow.execute_activity(
                        record_audit_trail,
                        RecordAuditTrailInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2, maximum_attempts=3),
                    )
            workflow.logger.info("Sleeping on timer: WorkflowTimeout")
            await workflow.sleep(WORKFLOW_TIMEOUT)
        except Exception:
            for _comp_fn, _comp_arg in reversed(compensations):
                await workflow.execute_activity(
                    _comp_fn,
                    _comp_arg,
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
            self._status = "compensated"
            raise
        self._status = "completed"
        return self._status

    @workflow.signal
    def oms_subscription_upgrade_rejected(self) -> None:
        """Handle the 'oms.subscription.upgrade.rejected' signal."""
        self._oms_subscription_upgrade_rejected_received = True

    @workflow.signal
    def oms_subscription_upgrade_started(self) -> None:
        """Handle the 'oms.subscription.upgrade.started' signal."""
        self._oms_subscription_upgrade_started_received = True

    @workflow.signal
    def oms_subscription_upgrade_completed(self) -> None:
        """Handle the 'oms.subscription.upgrade.completed' signal."""
        self._oms_subscription_upgrade_completed_received = True

    @workflow.signal
    def oms_subscription_upgrade_rolled_back(self) -> None:
        """Handle the 'oms.subscription.upgrade.rolled_back' signal."""
        self._oms_subscription_upgrade_rolled_back_received = True

    @workflow.query
    def get_upgrade_status(self) -> str:
        """Query the current status of the upgrade."""
        return self._status
