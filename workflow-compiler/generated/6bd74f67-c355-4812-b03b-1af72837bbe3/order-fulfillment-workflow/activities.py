"""Activities for the OrderFulfillmentWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    ValidateOrderAndPaymentInput,
    CancelOrderInput,
    ReserveInventoryInput,
    SendOrderConfirmationInput,
    NotifyWarehouseInput,
    PickAndPackItemsInput,
    CreateShipmentInput,
    ReleaseInventoryInput,
    ObtainManagerApprovalInput,
    EmailCustomerTrackingLinkInput,
    NotifyCustomerOfDelayInput,
    CompensateReserveInventoryInput,
    NotifyCustomerOfSLABreachInput,
)


@activity.defn(name="ValidateOrderAndPayment")
async def validate_order_and_payment(arg: ValidateOrderAndPaymentInput) -> str:
    """Validate order details and payment."""
    activity.logger.info("Running validate_order_and_payment", extra={"input": arg})
    # TODO: implement validate_order_and_payment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CancelOrder")
async def cancel_order(arg: CancelOrderInput) -> str:
    """Cancel the order if payment is invalid."""
    activity.logger.info("Running cancel_order", extra={"input": arg})
    # TODO: implement cancel_order. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReserveInventory")
async def reserve_inventory(arg: ReserveInventoryInput) -> str:
    """Reserve inventory for the order."""
    activity.logger.info("Running reserve_inventory", extra={"input": arg})
    # TODO: implement reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="SendOrderConfirmation")
async def send_order_confirmation(arg: SendOrderConfirmationInput) -> str:
    """Send confirmation to the customer."""
    activity.logger.info("Running send_order_confirmation", extra={"input": arg})
    # TODO: implement send_order_confirmation. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="NotifyWarehouse")
async def notify_warehouse(arg: NotifyWarehouseInput) -> str:
    """Notify the warehouse for pickup."""
    activity.logger.info("Running notify_warehouse", extra={"input": arg})
    # TODO: implement notify_warehouse. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="PickAndPackItems")
async def pick_and_pack_items(arg: PickAndPackItemsInput) -> str:
    """Pick and pack items in the warehouse."""
    activity.logger.info("Running pick_and_pack_items", extra={"input": arg})
    # TODO: implement pick_and_pack_items. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CreateShipment")
async def create_shipment(arg: CreateShipmentInput) -> str:
    """Create a shipment via the carrier API."""
    activity.logger.info("Running create_shipment", extra={"input": arg})
    # TODO: implement create_shipment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReleaseInventory")
async def release_inventory(arg: ReleaseInventoryInput) -> str:
    """Release inventory if shipment fails (Compensation)."""
    activity.logger.info("Running release_inventory", extra={"input": arg})
    # TODO: implement release_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ObtainManagerApproval")
async def obtain_manager_approval(arg: ObtainManagerApprovalInput) -> str:
    """Obtain approval for high-value orders."""
    activity.logger.info("Running obtain_manager_approval", extra={"input": arg})
    # TODO: implement obtain_manager_approval. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="EmailCustomerTrackingLink")
async def email_customer_tracking_link(arg: EmailCustomerTrackingLinkInput) -> str:
    """Email the tracking link to the customer."""
    activity.logger.info("Running email_customer_tracking_link", extra={"input": arg})
    # TODO: implement email_customer_tracking_link. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="NotifyCustomerOfDelay")
async def notify_customer_of_delay(arg: NotifyCustomerOfDelayInput) -> str:
    """Notify the customer of any delays."""
    activity.logger.info("Running notify_customer_of_delay", extra={"input": arg})
    # TODO: implement notify_customer_of_delay. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CompensateReserveInventory")
async def compensate_reserve_inventory(arg: CompensateReserveInventoryInput) -> str:
    """Release inventory on failure."""
    activity.logger.info("Running compensate_reserve_inventory", extra={"input": arg})
    # TODO: implement compensate_reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="NotifyCustomerOfSLABreach")
async def notify_customer_of_slabreach(arg: NotifyCustomerOfSLABreachInput) -> str:
    """Notify customer of SLA breach."""
    activity.logger.info("Running notify_customer_of_slabreach", extra={"input": arg})
    # TODO: implement notify_customer_of_slabreach. Returns a placeholder so the bundle runs as-is.
    return "stub-result"