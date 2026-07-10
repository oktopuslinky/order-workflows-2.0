"""Activities for the ReturnProcessingWorkflow workflow.

Each activity is a thin, retryable unit of work. Replace the ``NotImplementedError``
with real logic; activities may use I/O, SDKs, and blocking calls freely.
"""

from __future__ import annotations

from temporalio import activity

from shared import (
    AuthoriseReturnInput,
    ReceiveReturnedItemInput,
    IssueRefundInput,
    CancelRefundInput,
)


@activity.defn(name="AuthoriseReturn")
async def authorise_return(arg: AuthoriseReturnInput) -> str:
    """Authorise the return via Returns Service API."""
    activity.logger.info("Running authorise_return", extra={"input": arg})
    # TODO: implement authorise_return. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReceiveReturnedItem")
async def receive_returned_item(arg: ReceiveReturnedItemInput) -> str:
    """Receive the returned item via Warehouse Service API."""
    activity.logger.info("Running receive_returned_item", extra={"input": arg})
    # TODO: implement receive_returned_item. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="IssueRefund")
async def issue_refund(arg: IssueRefundInput) -> str:
    """Issue a refund via Payment Gateway API."""
    activity.logger.info("Running issue_refund", extra={"input": arg})
    # TODO: implement issue_refund. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CancelRefund")
async def cancel_refund(arg: CancelRefundInput) -> str:
    """Cancel a refund if issuance fails or needs reversal."""
    activity.logger.info("Running cancel_refund", extra={"input": arg})
    # TODO: implement cancel_refund. Returns a placeholder so the bundle runs as-is.
    return "stub-result"
