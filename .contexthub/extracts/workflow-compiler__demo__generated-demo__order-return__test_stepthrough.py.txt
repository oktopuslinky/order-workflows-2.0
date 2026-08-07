"""Local step-through harness for the ReturnProcessingWorkflow workflow.

Runs this bundle under a time-skipping Temporal test environment with the
generated stub activities (they return placeholders, no I/O) and **mocked
trigger activities** (the real ones call the Temporal client), then inspects
the read-only debug queries — proving which steps ran, which branch each
decision took, and which cross-workflow triggers fired.

Run from inside this bundle directory::

    pytest test_stepthrough.py -s

Requires: temporalio, pytest, pytest-asyncio (asyncio_mode=auto or the marker).
"""

from __future__ import annotations

import uuid

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from activities import (
    authorise_return,
    receive_returned_item,
    issue_refund,
    revoke_refund,
    cancel_return_authorization,
)
from shared import WorkflowInput
from workflow import ReturnProcessingWorkflow
TRIGGERS_CALLED: list[str] = []


@pytest.mark.asyncio
async def test_stepthrough() -> None:
    """Run the workflow end to end and inspect the debug queries."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="return-processing-queue",
            workflows=[ReturnProcessingWorkflow],
            activities=[authorise_return, receive_returned_item, issue_refund, revoke_refund, cancel_return_authorization, ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                ReturnProcessingWorkflow.run,
                WorkflowInput(),
                id=f"stepthrough-{uuid.uuid4()}",
                task_queue="return-processing-queue",
            )
            result = await handle.result()
            assert result == "completed"
            print("last step:", await handle.query("current_step"))
            print("decisions:", await handle.query("decisions_taken"))
            print("triggers fired:", await handle.query("triggers_fired"))
    finally:
        await env.shutdown()