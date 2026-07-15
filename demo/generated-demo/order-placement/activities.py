"""Activities for the EcommerceOrderWorkflow workflow.

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
    ReleaseInventoryReservationInput,
    CompensateReserveInventoryInput,
    StartOrderFulfilmentInput,
    StartOrderReturnInput,
)


@activity.defn(name="ValidateCart")
async def validate_cart(arg: ValidateCartInput) -> str:
    """Validate cart contents and eligibility"""
    activity.logger.info("Running validate_cart", extra={"input": arg})
    # TODO: implement validate_cart. Returns a placeholder so the bundle runs as-is.
    return 'eligible'

@activity.defn(name="ReserveInventory")
async def reserve_inventory(arg: ReserveInventoryInput) -> str:
    """Reserve inventory for the order"""
    activity.logger.info("Running reserve_inventory", extra={"input": arg})
    # TODO: implement reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="AuthorisePayment")
async def authorise_payment(arg: AuthorisePaymentInput) -> str:
    """Authorise payment for the order"""
    activity.logger.info("Running authorise_payment", extra={"input": arg})
    # TODO: implement authorise_payment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CreateOrder")
async def create_order(arg: CreateOrderInput) -> str:
    """Create the order in the system"""
    activity.logger.info("Running create_order", extra={"input": arg})
    # TODO: implement create_order. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReleaseInventoryReservation")
async def release_inventory_reservation(arg: ReleaseInventoryReservationInput) -> str:
    """Release the inventory reservation if necessary"""
    activity.logger.info("Running release_inventory_reservation", extra={"input": arg})
    # TODO: implement release_inventory_reservation. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CompensateReserveInventory")
async def compensate_reserve_inventory(arg: CompensateReserveInventoryInput) -> str:
    """Compensate by releasing the inventory reservation"""
    activity.logger.info("Running compensate_reserve_inventory", extra={"input": arg})
    # TODO: implement compensate_reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"