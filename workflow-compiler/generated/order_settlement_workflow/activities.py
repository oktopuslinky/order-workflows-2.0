"""Activities for the OrderSettlementWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    ValidateOrderInput,
    ReserveInventoryInput,
    ChargePaymentInput,
    NotifyCustomerInput,
    RecordSettlementEventInput,
    WaitForShippingConfirmationInput,
    FinaliseSettlementInput,
    ReleaseInventoryInput,
    RefundPaymentInput,
)


@activity.defn(name="ValidateOrder")
async def validate_order(arg: ValidateOrderInput) -> str:
    """Validate the order for settlement."""
    activity.logger.info("Running validate_order", extra={"input": arg})
    # TODO: implement validate_order. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReserveInventory")
async def reserve_inventory(arg: ReserveInventoryInput) -> str:
    """Reserve inventory for the order."""
    activity.logger.info("Running reserve_inventory", extra={"input": arg})
    # TODO: implement reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ChargePayment")
async def charge_payment(arg: ChargePaymentInput) -> str:
    """Charge the customer for the order."""
    activity.logger.info("Running charge_payment", extra={"input": arg})
    # TODO: implement charge_payment. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="NotifyCustomer")
async def notify_customer(arg: NotifyCustomerInput) -> str:
    """Notify the customer of the order status."""
    activity.logger.info("Running notify_customer", extra={"input": arg})
    # TODO: implement notify_customer. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="RecordSettlementEvent")
async def record_settlement_event(arg: RecordSettlementEventInput) -> str:
    """Record the settlement event in analytics."""
    activity.logger.info("Running record_settlement_event", extra={"input": arg})
    # TODO: implement record_settlement_event. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="WaitForShippingConfirmation")
async def wait_for_shipping_confirmation(arg: WaitForShippingConfirmationInput) -> str:
    """Wait for shipping confirmation."""
    activity.logger.info("Running wait_for_shipping_confirmation", extra={"input": arg})
    # TODO: implement wait_for_shipping_confirmation. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="FinaliseSettlement")
async def finalise_settlement(arg: FinaliseSettlementInput) -> str:
    """Finalise the settlement process."""
    activity.logger.info("Running finalise_settlement", extra={"input": arg})
    # TODO: implement finalise_settlement. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="ReleaseInventory")
async def release_inventory(arg: ReleaseInventoryInput) -> str:
    """Release reserved inventory for an order."""
    activity.logger.info("Running release_inventory", extra={"input": arg})
    # TODO: implement release_inventory. Returns a placeholder so the bundle runs as-is.
    return ""

@activity.defn(name="RefundPayment")
async def refund_payment(arg: RefundPaymentInput) -> str:
    """Refund a payment for an order."""
    activity.logger.info("Running refund_payment", extra={"input": arg})
    # TODO: implement refund_payment. Returns a placeholder so the bundle runs as-is.
    return ""
