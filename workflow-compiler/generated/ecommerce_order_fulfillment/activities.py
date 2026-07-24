"""Activities for the EcommerceOrderFulfillment workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    ValidateCartInput,
    ReserveInventoryInput,
    AuthorisePaymentInput,
    CreateOrderInput,
    PickItemsInput,
    PackShipmentInput,
    DispatchShipmentInput,
    CapturePaymentInput,
    AuthoriseReturnInput,
    ReceiveReturnedItemInput,
    IssueRefundInput,
    ReleaseInventoryInput,
    UnpackShipmentInput,
)


@activity.defn(name="ValidateCart")
async def validate_cart(arg: ValidateCartInput) -> str:
    """Checks if the cart is eligible for checkout."""
    activity.logger.info("Running validate_cart", extra={"input": arg})
    # TODO: implement validate_cart. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReserveInventory")
async def reserve_inventory(arg: ReserveInventoryInput) -> str:
    """Reserves inventory for the order items."""
    activity.logger.info("Running reserve_inventory", extra={"input": arg})
    # TODO: implement reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="AuthorisePayment")
async def authorise_payment(arg: AuthorisePaymentInput) -> str:
    """Attempts to authorise the payment."""
    activity.logger.info("Running authorise_payment", extra={"input": arg})
    # TODO: implement authorise_payment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="CreateOrder")
async def create_order(arg: CreateOrderInput) -> str:
    """Creates a new order in the system."""
    activity.logger.info("Running create_order", extra={"input": arg})
    # TODO: implement create_order. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PickItems")
async def pick_items(arg: PickItemsInput) -> str:
    """Picks the ordered items from the warehouse."""
    activity.logger.info("Running pick_items", extra={"input": arg})
    # TODO: implement pick_items. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="PackShipment")
async def pack_shipment(arg: PackShipmentInput) -> str:
    """Prepares the shipment."""
    activity.logger.info("Running pack_shipment", extra={"input": arg})
    # TODO: implement pack_shipment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="DispatchShipment")
async def dispatch_shipment(arg: DispatchShipmentInput) -> str:
    """Dispatches the shipment to the carrier."""
    activity.logger.info("Running dispatch_shipment", extra={"input": arg})
    # TODO: implement dispatch_shipment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="CapturePayment")
async def capture_payment(arg: CapturePaymentInput) -> str:
    """Captures the authorised payment."""
    activity.logger.info("Running capture_payment", extra={"input": arg})
    # TODO: implement capture_payment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="AuthoriseReturn")
async def authorise_return(arg: AuthoriseReturnInput) -> str:
    """Checks if a return is eligible."""
    activity.logger.info("Running authorise_return", extra={"input": arg})
    # TODO: implement authorise_return. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReceiveReturnedItem")
async def receive_returned_item(arg: ReceiveReturnedItemInput) -> str:
    """Processes the receipt of a returned item."""
    activity.logger.info("Running receive_returned_item", extra={"input": arg})
    # TODO: implement receive_returned_item. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="IssueRefund")
async def issue_refund(arg: IssueRefundInput) -> str:
    """Issues a refund for the return."""
    activity.logger.info("Running issue_refund", extra={"input": arg})
    # TODO: implement issue_refund. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReleaseInventory")
async def release_inventory(arg: ReleaseInventoryInput) -> str:
    """Releases reserved inventory upon failure."""
    activity.logger.info("Running release_inventory", extra={"input": arg})
    # TODO: implement release_inventory. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="UnpackShipment")
async def unpack_shipment(arg: UnpackShipmentInput) -> str:
    """Unpacks shipment if dispatch fails."""
    activity.logger.info("Running unpack_shipment", extra={"input": arg})
    # TODO: implement unpack_shipment. Returns a placeholder so the bundle runs as-is.
    return ""
