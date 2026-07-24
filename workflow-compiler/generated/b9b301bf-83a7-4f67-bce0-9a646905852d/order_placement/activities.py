"""Activities for the OrderFulfillmentWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    ValidateCartInput,
    ReserveInventoryInput,
    AuthorisePaymentInput,
    CreateOrderRecordInput,
    ReleaseInventoryInput,
    SendOrderConfirmationEmailInput,
    CompensateReserveInventoryInput,
    StartOrderFulfilmentInput,
)


@activity.defn(name="ValidateCart")
async def validate_cart(arg: ValidateCartInput) -> str:
    """Validate the cart contents and eligibility."""
    activity.logger.info("Running validate_cart", extra={"input": arg})
    # TODO: implement validate_cart. Returns a placeholder so the bundle runs as-is.
    return 'eligible'

@activity.defn(name="ReserveInventory")
async def reserve_inventory(arg: ReserveInventoryInput) -> str:
    """Reserve inventory for the order items."""
    activity.logger.info("Running reserve_inventory", extra={"input": arg})
    # TODO: implement reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="AuthorisePayment")
async def authorise_payment(arg: AuthorisePaymentInput) -> str:
    """Authorise payment for the order."""
    activity.logger.info("Running authorise_payment", extra={"input": arg})
    # TODO: implement authorise_payment. Returns a placeholder so the bundle runs as-is.
    return 'success'

@activity.defn(name="CreateOrderRecord")
async def create_order_record(arg: CreateOrderRecordInput) -> str:
    """Create a formal order record in the system."""
    activity.logger.info("Running create_order_record", extra={"input": arg})
    # TODO: implement create_order_record. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReleaseInventory")
async def release_inventory(arg: ReleaseInventoryInput) -> str:
    """Release reserved inventory back to stock."""
    activity.logger.info("Running release_inventory", extra={"input": arg})
    # TODO: implement release_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="SendOrderConfirmationEmail")
async def send_order_confirmation_email(arg: SendOrderConfirmationEmailInput) -> str:
    """Send order confirmation to the customer."""
    activity.logger.info("Running send_order_confirmation_email", extra={"input": arg})
    # TODO: implement send_order_confirmation_email. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CompensateReserveInventory")
async def compensate_reserve_inventory(arg: CompensateReserveInventoryInput) -> str:
    """Release inventory if payment fails or is declined."""
    activity.logger.info("Running compensate_reserve_inventory", extra={"input": arg})
    # TODO: implement compensate_reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"
