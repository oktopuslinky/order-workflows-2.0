"""The Subscriptionupgradeworkflow Temporal workflow.

Workflow code must be deterministic: do all I/O inside activities, and use
``workflow.*`` helpers (``execute_activity``, ``execute_child_workflow``,
``sleep``, signals, queries) rather than calling the outside world directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import (
        validaterequestpayload,
        resolvetargetplan,
        checksubscriptioneligibility,
        calculateprorationamount,
        validatepromocode,
        preauthoriseprorationcharge,
        updateentitlements,
        reprovisionservice,
        updateresourceinventory,
        capturepreauthorisedcharge,
        publishevents,
        sendupgradeconfirmation,
        recordaudittrail,
        restoreoldentitlements,
        reprovisionwitholdplan,
        restoreoldresourcereservation,
        releasepreauthorisation,
        reversechargecapture,
        publishrollbackevent,
    )
    from shared import (
        WorkflowInput,
        ValidaterequestpayloadInput,
        ResolvetargetplanInput,
        ChecksubscriptioneligibilityInput,
        CalculateprorationamountInput,
        ValidatepromocodeInput,
        PreauthoriseprorationchargeInput,
        UpdateentitlementsInput,
        ReprovisionserviceInput,
        UpdateresourceinventoryInput,
        CapturepreauthorisedchargeInput,
        PublisheventsInput,
        SendupgradeconfirmationInput,
        RecordaudittrailInput,
        RestoreoldentitlementsInput,
        ReprovisionwitholdplanInput,
        RestoreoldresourcereservationInput,
        ReleasepreauthorisationInput,
        ReversechargecaptureInput,
        PublishrollbackeventInput,
    )

VALIDATION_TIMEOUT = timedelta(seconds=5)  # Timeout for request payload validation.
PLAN_RESOLUTION_TIMEOUT = timedelta(seconds=10)  # Timeout for resolving target plan details.
ELIGIBILITY_CHECK_TIMEOUT = timedelta(seconds=15)  # Timeout for checking subscription eligibility.
PRE_AUTH_TIMEOUT = timedelta(seconds=30)  # Timeout for pre-authorising proration charge.
RE_PROVISIONING_TIMEOUT = timedelta(seconds=600)  # Timeout for service re-provisioning.
WORKFLOW_TIMEOUT = timedelta(seconds=1800)  # Overall workflow timeout.
PROMO_CODE_VALIDATION_TIMEOUT = timedelta(seconds=5)  # Timeout for validating promotional code.


@workflow.defn
class Subscriptionupgradeworkflow:
    """Manages the upgrade of a subscription, including validation, pre-authorisation, provisioning, and billing updates."""

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
            is_valid = await workflow.execute_activity(
                validate_request_payload,
                ValidateRequestPayloadInput(),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            plan_details = await workflow.execute_activity(
                resolve_target_plan,
                ResolveTargetPlanInput(plan_id=arg.target_plan_id),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            is_eligible = await workflow.execute_activity(
                check_subscription_eligibility,
                CheckSubscriptionEligibilityInput(subscription_id=arg.subscription_id),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
            )
            if True:  # TODO: replace with real condition: isEligible == True
                proration_amount = await workflow.execute_activity(
                    calculate_proration_amount,
                    CalculateProrationAmountInput(subscription_id=arg.subscription_id, effective_date=arg.effective_date),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                promo_valid = await workflow.execute_activity(
                    validate_promo_code,
                    ValidatePromoCodeInput(promo_code=arg.promo_code),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                pre_auth_id = await workflow.execute_activity(
                    pre_authorise_proration_charge,
                    PreAuthoriseProrationChargeInput(subscription_id=arg.subscription_id, proration_amount=proration_amount),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((releasepreauthorisation, ReleasepreauthorisationInput()))
                await asyncio.gather(
                    workflow.execute_activity(
                        update_entitlements,
                        UpdateEntitlementsInput(subscription_id=arg.subscription_id, target_plan_id=arg.target_plan_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    ),
                    workflow.execute_activity(
                        re_provision_service,
                        ReProvisionServiceInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    ),
                    workflow.execute_activity(
                        update_resource_inventory,
                        UpdateResourceInventoryInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    ),
                    workflow.execute_activity(
                        publish_events,
                        PublishEventsInput(subscription_id=arg.subscription_id),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                    ),
                )
                charge_captured = await workflow.execute_activity(
                    capture_pre_authorised_charge,
                    CapturePreAuthorisedChargeInput(pre_auth_id=pre_auth_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((reversechargecapture, ReversechargecaptureInput()))
                s14_result = await workflow.execute_activity(
                    send_upgrade_confirmation,
                    SendUpgradeConfirmationInput(subscription_id=arg.subscription_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                s15_result = await workflow.execute_activity(
                    publish_events,
                    PublishEventsInput(subscription_id=arg.subscription_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
                compensations.append((publishrollbackevent, PublishrollbackeventInput()))
                s16_result = await workflow.execute_activity(
                    record_audit_trail,
                    RecordAuditTrailInput(subscription_id=arg.subscription_id),
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=2, maximum_attempts=3),
                )
            else:
                # Wait until: true
                await workflow.wait_condition(lambda: self._oms_subscription_upgrade_rejected_received)
            # Wait until: exception_3 || exception_4
            await workflow.wait_condition(lambda: self._oms_subscription_upgrade_rolled_back_received)
        except Exception:
            for _comp_fn, _comp_arg in reversed(compensations):
                await workflow.execute_activity(
                    _comp_fn,
                    _comp_arg,
                    start_to_close_timeout=timedelta(seconds=60),
                )
            self._status = "compensated"
            raise
        self._status = "completed"
        return self._status

    @workflow.signal
    def oms_subscription_upgrade_rejected(self, reason: str) -> None:
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
    def oms_subscription_upgrade_rolled_back(self, failure_reason: str) -> None:
        """Handle the 'oms.subscription.upgrade.rolled_back' signal."""
        self._oms_subscription_upgrade_rolled_back_received = True

    @workflow.query
    def get_upgrade_status(self) -> str:
        """Query the current status of the upgrade."""
        return self._status
