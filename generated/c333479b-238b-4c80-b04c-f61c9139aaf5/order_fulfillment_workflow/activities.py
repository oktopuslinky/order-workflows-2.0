"""Activities for the OrderFulfillmentWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    ValidateOrderAndPaymentInput,
    ReserveInventoryInput,
    SendOrderConfirmationInput,
    NotifyWarehouseInput,
    PickAndPackItemsInput,
    CreateShipmentViaCarrierAPIInput,
    ShipOrderInput,
    ReleaseReservedInventoryInput,
    ObtainManagerApprovalInput,
    NotifyFinanceTeamInput,
    CompensateReserveInventoryInput,
)


@activity.defn(name="ValidateOrderAndPayment")
async def validate_order_and_payment(arg: ValidateOrderAndPaymentInput) -> str:
    """Checks order validity and payment status."""
    activity.logger.info("Running validate_order_and_payment", extra={"input": arg})
    # TODO: implement validate_order_and_payment. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReserveInventory")
async def reserve_inventory(arg: ReserveInventoryInput) -> str:
    """Reserves inventory for the order."""
    activity.logger.info("Running reserve_inventory", extra={"input": arg})
    # TODO: implement reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="SendOrderConfirmation")
async def send_order_confirmation(arg: SendOrderConfirmationInput) -> str:
    """Sends confirmation to the customer."""
    activity.logger.info("Running send_order_confirmation", extra={"input": arg})
    # TODO: implement send_order_confirmation. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="NotifyWarehouse")
async def notify_warehouse(arg: NotifyWarehouseInput) -> str:
    """Notifies the warehouse to prepare for picking."""
    activity.logger.info("Running notify_warehouse", extra={"input": arg})
    # TODO: implement notify_warehouse. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="PickAndPackItems")
async def pick_and_pack_items(arg: PickAndPackItemsInput) -> str:
    """Executes picking and packing of order items."""
    activity.logger.info("Running pick_and_pack_items", extra={"input": arg})
    # TODO: implement pick_and_pack_items. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CreateShipmentViaCarrierAPI")
async def create_shipment_via_carrier_api(arg: CreateShipmentViaCarrierAPIInput) -> str:
    """Creates a shipment via the carrier's API."""
    activity.logger.info("Running create_shipment_via_carrier_api", extra={"input": arg})
    # TODO: implement create_shipment_via_carrier_api. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ShipOrder")
async def ship_order(arg: ShipOrderInput) -> str:
    """Finalizes the shipment process."""
    activity.logger.info("Running ship_order", extra={"input": arg})
    # TODO: implement ship_order. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReleaseReservedInventory")
async def release_reserved_inventory(arg: ReleaseReservedInventoryInput) -> str:
    """Releases inventory if shipment fails or is cancelled."""
    activity.logger.info("Running release_reserved_inventory", extra={"input": arg})
    # TODO: implement release_reserved_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ObtainManagerApproval")
async def obtain_manager_approval(arg: ObtainManagerApprovalInput) -> str:
    """Seeks approval for high-value orders."""
    activity.logger.info("Running obtain_manager_approval", extra={"input": arg})
    # TODO: implement obtain_manager_approval. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="NotifyFinanceTeam")
async def notify_finance_team(arg: NotifyFinanceTeamInput) -> str:
    """Notifies finance for high-value orders."""
    activity.logger.info("Running notify_finance_team", extra={"input": arg})
    # TODO: implement notify_finance_team. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CompensateReserveInventory")
async def compensate_reserve_inventory(arg: CompensateReserveInventoryInput) -> str:
    """Releases inventory on failure or cancellation."""
    activity.logger.info("Running compensate_reserve_inventory", extra={"input": arg})
    # TODO: implement compensate_reserve_inventory. Returns a placeholder so the bundle runs as-is.
    return "stub-result"
