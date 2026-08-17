"""
Activities for the Order Lifecycle Workflow.

Each activity wraps a call to a downstream enterprise system (Inventory,
Payments, Fraud, WMS, Carrier, Finance). In this reference repo the actual
downstream calls are stubbed out with clearly-marked mock implementations —
swap the body of each `_call_*` helper for a real HTTP/gRPC client in your
environment.

Activities are the unit of retry in Temporal: if one raises a retryable
exception, Temporal will re-invoke it per the RetryPolicy configured on the
workflow side (see src/workflows/order_workflow.py). Keep activities
idempotent so retries are always safe (see TDD §4.2 for the idempotency
strategy per activity).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from temporalio import activity
from temporalio.exceptions import ApplicationError

from src.shared.types import (
    CompletionResult,
    DispatchResult,
    OrderRequest,
    ProvisioningResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

@activity.defn
async def capture_order(order: OrderRequest) -> str:
    """Persist the order intake record. Returns the order_id.

    Idempotent: writing the same order_id twice is a no-op upsert.
    """
    if not order.line_items:
        # Non-retryable: this input will never succeed no matter how many
        # times we retry it, so fail fast (see US-001 / TC-17).
        raise ApplicationError("Order must contain at least one line item", non_retryable=True)

    logger.info("Captured order %s for customer %s", order.order_id, order.customer_id)
    # In production: INSERT ... ON CONFLICT (order_id) DO NOTHING
    return order.order_id


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

@activity.defn
async def validate_order(order: OrderRequest) -> ValidationResult:
    """Check inventory availability, authorize payment, and run a fraud check.

    Implements US-002 / BR-02 / BR-03.
    """
    if not await _check_inventory(order):
        return ValidationResult(passed=False, reason_code="INVENTORY_UNAVAILABLE")

    if not await _authorize_payment(order):
        return ValidationResult(passed=False, reason_code="PAYMENT_DECLINED")

    if not await _fraud_check(order):
        return ValidationResult(passed=False, reason_code="FRAUD_HOLD")

    return ValidationResult(passed=True)


async def _check_inventory(order: OrderRequest) -> bool:
    # MOCK: replace with a real Inventory Service call.
    return all(item.quantity > 0 for item in order.line_items)


async def _authorize_payment(order: OrderRequest) -> bool:
    # MOCK: replace with a real Payment Gateway authorization call.
    return order.payment_token != "DECLINE_ME"


async def _fraud_check(order: OrderRequest) -> bool:
    # MOCK: replace with a real Fraud/Risk scoring call.
    return order.customer_id != "FRAUD_FLAGGED"


# ---------------------------------------------------------------------------
# Provision
# ---------------------------------------------------------------------------

@activity.defn
async def provision_order(order: OrderRequest) -> ProvisioningResult:
    """Reserve inventory and allocate a warehouse for pick/pack.

    Implements US-003 / BR-04. Idempotency key = order_id, so retries never
    double-reserve stock.
    """
    reservation_id = f"RSV-{order.order_id}"
    warehouse_id = "WH-EAST-01"
    logger.info("Reserved inventory for order %s -> %s @ %s", order.order_id, reservation_id, warehouse_id)
    return ProvisioningResult(reservation_id=reservation_id, warehouse_id=warehouse_id)


@activity.defn
async def compensate_provisioning(reservation_id: str) -> None:
    """Release a previously-made inventory reservation. Safe to call more
    than once (releasing an already-released reservation is a no-op).
    """
    logger.info("Released reservation %s", reservation_id)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@activity.defn
async def dispatch_order(order: OrderRequest, idempotency_key: str) -> DispatchResult:
    """Select a carrier, generate a shipping label, hand off the package.

    Implements US-004 / BR-05 / BR-11. `idempotency_key` is generated
    deterministically by the workflow (see order_workflow.py) BEFORE this
    activity is first attempted, so retries after a partial failure return
    the original shipment instead of creating a duplicate.
    """
    tracking_number = f"TRK-{idempotency_key[:8].upper()}"
    logger.info(
        "Dispatched order %s via carrier (idempotency_key=%s) -> %s",
        order.order_id,
        idempotency_key,
        tracking_number,
    )
    return DispatchResult(
        tracking_number=tracking_number,
        carrier="GLOBAL-EXPRESS",
        label_url=f"https://labels.example.com/{tracking_number}.pdf",
        idempotency_key=idempotency_key,
    )


@activity.defn
async def compensate_dispatch(tracking_number: str) -> None:
    """Trigger a recall / return-to-sender flow for an already-dispatched
    shipment. Idempotent by tracking_number.
    """
    logger.info("Recalled shipment %s", tracking_number)


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------

@activity.defn
async def complete_order(order_id: str) -> CompletionResult:
    """Confirm delivery and generate an invoice.

    Implements US-005 / BR-06. Invoice generation is keyed by order_id, so
    retries never double-invoice a customer.
    """
    invoice_id = f"INV-{order_id}"
    logger.info("Order %s completed, invoice %s generated", order_id, invoice_id)
    return CompletionResult(invoice_id=invoice_id, delivered_at=datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Terminal state persistence
# ---------------------------------------------------------------------------

@activity.defn
async def record_terminal_state(order_id: str, status: str, reason: str | None) -> None:
    """Persist the final REJECTED/CANCELLED state + reason for reporting
    and audit purposes (BR-10).
    """
    logger.info("Order %s terminal state=%s reason=%s", order_id, status, reason)
