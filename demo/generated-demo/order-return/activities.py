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
    RevokeRefundInput,
    CancelReturnAuthorizationInput,
)


@activity.defn(name="AuthoriseReturn")
async def authorise_return(arg: AuthoriseReturnInput) -> str:
    """Authorizes the return via the Returns Service."""
    activity.logger.info("Running authorise_return", extra={"input": arg})
    # TODO: implement authorise_return. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="ReceiveReturnedItem")
async def receive_returned_item(arg: ReceiveReturnedItemInput) -> str:
    """Notifies the Warehouse Service of the returned item."""
    activity.logger.info("Running receive_returned_item", extra={"input": arg})
    # TODO: implement receive_returned_item. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="IssueRefund")
async def issue_refund(arg: IssueRefundInput) -> str:
    """Issues a refund through the Payment Gateway."""
    activity.logger.info("Running issue_refund", extra={"input": arg})
    # TODO: implement issue_refund. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="RevokeRefund")
async def revoke_refund(arg: RevokeRefundInput) -> str:
    """Reverses a refund if issuance failed or was inappropriate."""
    activity.logger.info("Running revoke_refund", extra={"input": arg})
    # TODO: implement revoke_refund. Returns a placeholder so the bundle runs as-is.
    return "stub-result"

@activity.defn(name="CancelReturnAuthorization")
async def cancel_return_authorization(arg: CancelReturnAuthorizationInput) -> str:
    """Cancels return authorization if the process fails post-authorization."""
    activity.logger.info("Running cancel_return_authorization", extra={"input": arg})
    # TODO: implement cancel_return_authorization. Returns a placeholder so the bundle runs as-is.
    return "stub-result"