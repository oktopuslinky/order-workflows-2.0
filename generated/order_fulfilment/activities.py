"""Activities for the OrderFulfilmentWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    PickItemsInput,
    PackShipmentInput,
    DispatchShipmentInput,
    CapturePaymentInput,
    WaitForCarrierPickupConfirmationInput,
    UnpackShipmentInput,
)


@activity.defn(name="PickItems")
async def pick_items(arg: PickItemsInput) -> str:
    """Picks items from the warehouse."""
    activity.logger.info("Running pick_items", extra={"input": arg})
    # TODO: implement pick_items. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PackShipment")
async def pack_shipment(arg: PackShipmentInput) -> str:
    """Packs the picked items for shipment."""
    activity.logger.info("Running pack_shipment", extra={"input": arg})
    # TODO: implement pack_shipment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="DispatchShipment")
async def dispatch_shipment(arg: DispatchShipmentInput) -> str:
    """Dispatches the shipment via a carrier."""
    activity.logger.info("Running dispatch_shipment", extra={"input": arg})
    # TODO: implement dispatch_shipment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="CapturePayment")
async def capture_payment(arg: CapturePaymentInput) -> str:
    """Captures payment for the order."""
    activity.logger.info("Running capture_payment", extra={"input": arg})
    # TODO: implement capture_payment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="WaitForCarrierPickupConfirmation")
async def wait_for_carrier_pickup_confirmation(arg: WaitForCarrierPickupConfirmationInput) -> str:
    """Waits for the carrier pickup confirmation."""
    activity.logger.info("Running wait_for_carrier_pickup_confirmation", extra={"input": arg})
    # TODO: implement wait_for_carrier_pickup_confirmation. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="UnpackShipment")
async def unpack_shipment(arg: UnpackShipmentInput) -> str:
    """Unpacks the shipment in case of failures."""
    activity.logger.info("Running unpack_shipment", extra={"input": arg})
    # TODO: implement unpack_shipment. Returns a placeholder so the bundle runs as-is.
    return ""
