"""
OrderWorkflow — durable orchestration for the enterprise order lifecycle:
Capture -> Validate -> Provision -> Dispatch -> Complete.

See docs/technical-design/TDD-order-workflow-temporal.md for the full design,
and docs/diagrams/mermaid/order-state-machine.mmd for the state diagram this
workflow implements.

Saga pattern: if a step fails after prior steps produced real side effects
(inventory reserved, shipment created), the workflow compensates the
completed steps in reverse order before ending in a terminal state.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from src.shared.types import (
        CompletionResult,
        DispatchResult,
        OrderRequest,
        OrderState,
        OrderStatus,
        ProvisioningResult,
        ValidationResult,
    )
    from src.activities.order_activities import (
        capture_order,
        compensate_dispatch,
        compensate_provisioning,
        complete_order,
        dispatch_order,
        provision_order,
        record_terminal_state,
        validate_order,
    )


VALIDATE_TIMEOUT = timedelta(seconds=30)
PROVISION_TIMEOUT = timedelta(seconds=60)
DISPATCH_TIMEOUT = timedelta(seconds=120)
COMPLETE_TIMEOUT = timedelta(seconds=30)

DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=5,
)


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._state = OrderState(order_id="", status=OrderStatus.RECEIVED)
        self._cancel_requested = False
        self._cancel_reason: str | None = None
        self._delivery_confirmed = False

        # Track which steps actually completed so we know what to compensate.
        self._provisioning_result: ProvisioningResult | None = None
        self._dispatch_result: DispatchResult | None = None

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    @workflow.signal
    def cancel_order(self, reason: str) -> None:
        if self._state.status in (OrderStatus.COMPLETED, OrderStatus.REJECTED, OrderStatus.CANCELLED):
            self._state.history.append(f"Ignored cancel_order signal in terminal state {self._state.status}")
            return
        self._cancel_requested = True
        self._cancel_reason = reason

    @workflow.signal
    def delivery_confirmed(self) -> None:
        self._delivery_confirmed = True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @workflow.query
    def get_status(self) -> OrderState:
        return self._state

    # ------------------------------------------------------------------
    # Main workflow run
    # ------------------------------------------------------------------

    @workflow.run
    async def run(self, order: OrderRequest) -> OrderState:
        self._state.order_id = order.order_id
        self._state.received_at = workflow.now()

        await workflow.execute_activity(
            capture_order, order, start_to_close_timeout=VALIDATE_TIMEOUT, retry_policy=DEFAULT_RETRY
        )
        self._transition(OrderStatus.VALIDATING)

        if self._maybe_cancel():
            return await self._finish_cancelled()

        # --- Validate -------------------------------------------------
        validation: ValidationResult = await workflow.execute_activity(
            validate_order, order, start_to_close_timeout=VALIDATE_TIMEOUT, retry_policy=DEFAULT_RETRY
        )
        if not validation.passed:
            return await self._finish_rejected(validation.reason_code or "VALIDATION_FAILED")

        self._transition(OrderStatus.VALIDATED)
        self._state.validated_at = workflow.now()

        if self._maybe_cancel():
            return await self._finish_cancelled()

        # --- Provision --------------------------------------------------
        self._transition(OrderStatus.PROVISIONING)
        try:
            self._provisioning_result = await workflow.execute_activity(
                provision_order, order, start_to_close_timeout=PROVISION_TIMEOUT, retry_policy=DEFAULT_RETRY
            )
        except ActivityError:
            # Nothing was reserved, so nothing to compensate.
            return await self._finish_rejected("PROVISIONING_FAILED")

        self._transition(OrderStatus.PROVISIONED)
        self._state.provisioned_at = workflow.now()

        if self._maybe_cancel():
            await self._compensate_provisioning()
            return await self._finish_cancelled()

        # --- Dispatch -----------------------------------------------------
        self._transition(OrderStatus.DISPATCHING)
        # Deterministic, replay-safe UUID -> stable idempotency key even if
        # this activity is retried after a partial network failure (TDD §4.4).
        idempotency_key = str(workflow.uuid4())
        try:
            self._dispatch_result = await workflow.execute_activity(
                dispatch_order,
                args=[order, idempotency_key],
                start_to_close_timeout=DISPATCH_TIMEOUT,
                retry_policy=DEFAULT_RETRY,
            )
        except ActivityError:
            await self._compensate_provisioning()
            return await self._finish_rejected("DISPATCH_FAILED")

        self._transition(OrderStatus.DISPATCHED)
        self._state.dispatched_at = workflow.now()
        self._state.tracking_number = self._dispatch_result.tracking_number

        if self._maybe_cancel():
            await self._compensate_dispatch()
            await self._compensate_provisioning()
            return await self._finish_cancelled()

        # --- Continue-as-new before the (potentially long) delivery wait --
        # Keeps Workflow History small during multi-hour/day delivery waits
        # (TDD §4.7). In production this would carry forward the minimal
        # resume state (order + dispatch result) via a dedicated
        # `run_from_dispatched` workflow entry point; omitted here for
        # readability — see TDD §4.7 for the full design note.
        #
        # if <this run has been waiting a long time and history is large>:
        #     workflow.continue_as_new(order)

        # --- Await delivery confirmation -----------------------------------
        await workflow.wait_condition(lambda: self._delivery_confirmed or self._cancel_requested)

        if self._cancel_requested:
            await self._compensate_dispatch()
            await self._compensate_provisioning()
            return await self._finish_cancelled()

        # --- Complete -------------------------------------------------
        completion: CompletionResult = await workflow.execute_activity(
            complete_order, order.order_id, start_to_close_timeout=COMPLETE_TIMEOUT, retry_policy=DEFAULT_RETRY
        )
        self._state.invoice_id = completion.invoice_id
        self._transition(OrderStatus.COMPLETED)
        self._state.completed_at = workflow.now()
        return self._state

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _transition(self, status: OrderStatus) -> None:
        self._state.status = status
        self._state.history.append(f"{workflow.now().isoformat()} -> {status.value}")

    def _maybe_cancel(self) -> bool:
        return self._cancel_requested

    async def _compensate_provisioning(self) -> None:
        if self._provisioning_result is not None:
            await workflow.execute_activity(
                compensate_provisioning,
                self._provisioning_result.reservation_id,
                start_to_close_timeout=PROVISION_TIMEOUT,
                retry_policy=DEFAULT_RETRY,
            )
            self._state.history.append("Compensated provisioning (inventory released)")

    async def _compensate_dispatch(self) -> None:
        if self._dispatch_result is not None:
            await workflow.execute_activity(
                compensate_dispatch,
                self._dispatch_result.tracking_number,
                start_to_close_timeout=DISPATCH_TIMEOUT,
                retry_policy=DEFAULT_RETRY,
            )
            self._state.history.append("Compensated dispatch (shipment recalled)")

    async def _finish_rejected(self, reason: str) -> OrderState:
        self._state.failure_reason = reason
        self._transition(OrderStatus.REJECTED)
        await workflow.execute_activity(
            record_terminal_state,
            args=[self._state.order_id, OrderStatus.REJECTED.value, reason],
            start_to_close_timeout=VALIDATE_TIMEOUT,
            retry_policy=DEFAULT_RETRY,
        )
        return self._state

    async def _finish_cancelled(self) -> OrderState:
        self._state.failure_reason = self._cancel_reason
        self._transition(OrderStatus.CANCELLED)
        await workflow.execute_activity(
            record_terminal_state,
            args=[self._state.order_id, OrderStatus.CANCELLED.value, self._cancel_reason],
            start_to_close_timeout=VALIDATE_TIMEOUT,
            retry_policy=DEFAULT_RETRY,
        )
        return self._state
