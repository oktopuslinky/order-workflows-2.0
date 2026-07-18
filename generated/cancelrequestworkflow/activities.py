"""Activities for the Cancelrequestworkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    CancelrequestintakeInput,
    EligibilitycheckInput,
    DeprovisioningInput,
    InventoryreleaseInput,
    CompensateremaininglegsInput,
)


@activity.defn(name="Cancelrequestintake")
async def cancelrequestintake(arg: CancelrequestintakeInput) -> str:
    """Intake for cancel request via OMS API"""
    activity.logger.info("Running cancelrequestintake", extra={"input": arg})
    raise NotImplementedError("cancelrequestintake is not implemented yet.")

@activity.defn(name="Eligibilitycheck")
async def eligibilitycheck(arg: EligibilitycheckInput) -> str:
    """Checks eligibility for cancellation using TMF640"""
    activity.logger.info("Running eligibilitycheck", extra={"input": arg})
    raise NotImplementedError("eligibilitycheck is not implemented yet.")

@activity.defn(name="Deprovisioning")
async def deprovisioning(arg: DeprovisioningInput) -> str:
    """Deprovisions service via TMF640 DELETE"""
    activity.logger.info("Running deprovisioning", extra={"input": arg})
    raise NotImplementedError("deprovisioning is not implemented yet.")

@activity.defn(name="Inventoryrelease")
async def inventoryrelease(arg: InventoryreleaseInput) -> str:
    """Releases inventory via TMF638 PATCH"""
    activity.logger.info("Running inventoryrelease", extra={"input": arg})
    raise NotImplementedError("inventoryrelease is not implemented yet.")

@activity.defn(name="Compensateremaininglegs")
async def compensateremaininglegs(arg: CompensateremaininglegsInput) -> str:
    """Compensates for partial deprovisioning"""
    activity.logger.info("Running compensateremaininglegs", extra={"input": arg})
    raise NotImplementedError("compensateremaininglegs is not implemented yet.")
