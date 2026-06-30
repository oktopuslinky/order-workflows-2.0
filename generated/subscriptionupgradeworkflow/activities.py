"""Activities for the Subscriptionupgradeworkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
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


@activity.defn(name="Validaterequestpayload")
async def validaterequestpayload(arg: ValidaterequestpayloadInput) -> str:
    """Validate incoming request payload integrity."""
    activity.logger.info("Running validaterequestpayload", extra={"input": arg})
    raise NotImplementedError("validaterequestpayload is not implemented yet.")

@activity.defn(name="Resolvetargetplan")
async def resolvetargetplan(arg: ResolvetargetplanInput) -> str:
    """Fetch target plan details from Product Catalog."""
    activity.logger.info("Running resolvetargetplan", extra={"input": arg})
    raise NotImplementedError("resolvetargetplan is not implemented yet.")

@activity.defn(name="Checksubscriptioneligibility")
async def checksubscriptioneligibility(arg: ChecksubscriptioneligibilityInput) -> str:
    """Verify if the subscription is eligible for upgrade."""
    activity.logger.info("Running checksubscriptioneligibility", extra={"input": arg})
    raise NotImplementedError("checksubscriptioneligibility is not implemented yet.")

@activity.defn(name="Calculateprorationamount")
async def calculateprorationamount(arg: CalculateprorationamountInput) -> str:
    """Calculate prorated charge for the upgrade."""
    activity.logger.info("Running calculateprorationamount", extra={"input": arg})
    raise NotImplementedError("calculateprorationamount is not implemented yet.")

@activity.defn(name="Validatepromocode")
async def validatepromocode(arg: ValidatepromocodeInput) -> str:
    """Validate promotional code if provided."""
    activity.logger.info("Running validatepromocode", extra={"input": arg})
    raise NotImplementedError("validatepromocode is not implemented yet.")

@activity.defn(name="Preauthoriseprorationcharge")
async def preauthoriseprorationcharge(arg: PreauthoriseprorationchargeInput) -> str:
    """Pre-authorise the prorated charge with the Payment Gateway."""
    activity.logger.info("Running preauthoriseprorationcharge", extra={"input": arg})
    raise NotImplementedError("preauthoriseprorationcharge is not implemented yet.")

@activity.defn(name="Updateentitlements")
async def updateentitlements(arg: UpdateentitlementsInput) -> str:
    """Update entitlements for the subscription."""
    activity.logger.info("Running updateentitlements", extra={"input": arg})
    raise NotImplementedError("updateentitlements is not implemented yet.")

@activity.defn(name="Reprovisionservice")
async def reprovisionservice(arg: ReprovisionserviceInput) -> str:
    """Re-provision the service according to the new plan."""
    activity.logger.info("Running reprovisionservice", extra={"input": arg})
    raise NotImplementedError("reprovisionservice is not implemented yet.")

@activity.defn(name="Updateresourceinventory")
async def updateresourceinventory(arg: UpdateresourceinventoryInput) -> str:
    """Update resource inventory reflecting the plan change."""
    activity.logger.info("Running updateresourceinventory", extra={"input": arg})
    raise NotImplementedError("updateresourceinventory is not implemented yet.")

@activity.defn(name="Capturepreauthorisedcharge")
async def capturepreauthorisedcharge(arg: CapturepreauthorisedchargeInput) -> str:
    """Capture the pre-authorised charge."""
    activity.logger.info("Running capturepreauthorisedcharge", extra={"input": arg})
    raise NotImplementedError("capturepreauthorisedcharge is not implemented yet.")

@activity.defn(name="Publishevents")
async def publishevents(arg: PublisheventsInput) -> str:
    """Publish upgrade events (started, completed, rolled_back)."""
    activity.logger.info("Running publishevents", extra={"input": arg})
    raise NotImplementedError("publishevents is not implemented yet.")

@activity.defn(name="Sendupgradeconfirmation")
async def sendupgradeconfirmation(arg: SendupgradeconfirmationInput) -> str:
    """Notify the customer of the upgrade completion."""
    activity.logger.info("Running sendupgradeconfirmation", extra={"input": arg})
    raise NotImplementedError("sendupgradeconfirmation is not implemented yet.")

@activity.defn(name="Recordaudittrail")
async def recordaudittrail(arg: RecordaudittrailInput) -> str:
    """Log the upgrade transaction for audit purposes."""
    activity.logger.info("Running recordaudittrail", extra={"input": arg})
    raise NotImplementedError("recordaudittrail is not implemented yet.")

@activity.defn(name="Restoreoldentitlements")
async def restoreoldentitlements(arg: RestoreoldentitlementsInput) -> str:
    """Revert entitlements to their previous state."""
    activity.logger.info("Running restoreoldentitlements", extra={"input": arg})
    raise NotImplementedError("restoreoldentitlements is not implemented yet.")

@activity.defn(name="Reprovisionwitholdplan")
async def reprovisionwitholdplan(arg: ReprovisionwitholdplanInput) -> str:
    """Re-provision using the original plan."""
    activity.logger.info("Running reprovisionwitholdplan", extra={"input": arg})
    raise NotImplementedError("reprovisionwitholdplan is not implemented yet.")

@activity.defn(name="Restoreoldresourcereservation")
async def restoreoldresourcereservation(arg: RestoreoldresourcereservationInput) -> str:
    """Revert resource inventory changes."""
    activity.logger.info("Running restoreoldresourcereservation", extra={"input": arg})
    raise NotImplementedError("restoreoldresourcereservation is not implemented yet.")

@activity.defn(name="Releasepreauthorisation")
async def releasepreauthorisation(arg: ReleasepreauthorisationInput) -> str:
    """Release the pre-authorised charge."""
    activity.logger.info("Running releasepreauthorisation", extra={"input": arg})
    raise NotImplementedError("releasepreauthorisation is not implemented yet.")

@activity.defn(name="Reversechargecapture")
async def reversechargecapture(arg: ReversechargecaptureInput) -> str:
    """Reverse the captured charge."""
    activity.logger.info("Running reversechargecapture", extra={"input": arg})
    raise NotImplementedError("reversechargecapture is not implemented yet.")

@activity.defn(name="Publishrollbackevent")
async def publishrollbackevent(arg: PublishrollbackeventInput) -> str:
    """Publish a rollback event."""
    activity.logger.info("Running publishrollbackevent", extra={"input": arg})
    raise NotImplementedError("publishrollbackevent is not implemented yet.")
