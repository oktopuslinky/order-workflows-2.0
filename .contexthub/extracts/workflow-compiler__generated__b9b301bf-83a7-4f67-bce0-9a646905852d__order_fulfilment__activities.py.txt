"""Activities for the FulfilmentWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    PickOrderItemsInput,
    PackShipmentInput,
    DispatchShipmentInput,
    CapturePaymentInput,
    RecordFulfilmentLedgerEntryInput,
    UnpackShipmentInput,
    RefundCapturedPaymentInput,
    StartPaymentReconciliationInput,
)


@activity.defn(name="PickOrderItems")
async def pick_order_items(arg: PickOrderItemsInput) -> str:
    """Retrieves items from the warehouse"""
    activity.logger.info("Running pick_order_items", extra={"input": arg})
    # TODO: implement pick_order_items. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="PackShipment")
async def pack_shipment(arg: PackShipmentInput) -> str:
    """Prepares the shipment for dispatch"""
    activity.logger.info("Running pack_shipment", extra={"input": arg})
    # TODO: implement pack_shipment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="DispatchShipment")
async def dispatch_shipment(arg: DispatchShipmentInput) -> str:
    """Sends the shipment via a carrier"""
    activity.logger.info("Running dispatch_shipment", extra={"input": arg})
    # TODO: implement dispatch_shipment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CapturePayment")
async def capture_payment(arg: CapturePaymentInput) -> str:
    """Captures payment for the order"""
    activity.logger.info("Running capture_payment", extra={"input": arg})
    # TODO: implement capture_payment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="RecordFulfilmentLedgerEntry")
async def record_fulfilment_ledger_entry(arg: RecordFulfilmentLedgerEntryInput) -> str:
    """Updates the fulfilment ledger"""
    activity.logger.info("Running record_fulfilment_ledger_entry", extra={"input": arg})
    # TODO: implement record_fulfilment_ledger_entry. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="UnpackShipment")
async def unpack_shipment(arg: UnpackShipmentInput) -> str:
    """Unpacks the shipment in case of failure"""
    activity.logger.info("Running unpack_shipment", extra={"input": arg})
    # TODO: implement unpack_shipment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="RefundCapturedPayment")
async def refund_captured_payment(arg: RefundCapturedPaymentInput) -> str:
    """Refunds the captured payment in case of failure"""
    activity.logger.info("Running refund_captured_payment", extra={"input": arg})
    # TODO: implement refund_captured_payment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"
