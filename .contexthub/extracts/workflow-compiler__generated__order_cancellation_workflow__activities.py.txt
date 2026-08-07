"""Activities for the OrderCancellationWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    CancelRequestIntakeInput,
    EligibilityCheckInput,
    DeprovisioningInput,
    InventoryReleaseInput,
    PartialCancelCompensationInput,
)


@activity.defn(name="CancelRequestIntake")
async def cancel_request_intake(arg: CancelRequestIntakeInput) -> str:
    """Intakes cancellation request via OMS API."""
    activity.logger.info("Running cancel_request_intake", extra={"input": arg})
    # TODO: implement cancel_request_intake. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="EligibilityCheck")
async def eligibility_check(arg: EligibilityCheckInput) -> str:
    """Checks eligibility for cancellation using TMF640."""
    activity.logger.info("Running eligibility_check", extra={"input": arg})
    # TODO: implement eligibility_check. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="Deprovisioning")
async def deprovisioning(arg: DeprovisioningInput) -> str:
    """Deprovisions service via TMF640 API."""
    activity.logger.info("Running deprovisioning", extra={"input": arg})
    # TODO: implement deprovisioning. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="InventoryRelease")
async def inventory_release(arg: InventoryReleaseInput) -> str:
    """Releases inventory via TMF638 API."""
    activity.logger.info("Running inventory_release", extra={"input": arg})
    # TODO: implement inventory_release. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PartialCancelCompensation")
async def partial_cancel_compensation(arg: PartialCancelCompensationInput) -> str:
    """Compensates for partial cancellations."""
    activity.logger.info("Running partial_cancel_compensation", extra={"input": arg})
    # TODO: implement partial_cancel_compensation. Returns a placeholder so the bundle runs as-is.
    return ""
