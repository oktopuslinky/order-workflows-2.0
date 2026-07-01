"""Start a Cancelrequestworkflow workflow execution.

Start the Temporal dev server and the worker first::

    temporal server start-dev      # terminal 1
    python worker.py               # terminal 2

Then, from inside this package directory::

    python starter.py              # terminal 3
"""

from __future__ import annotations

import asyncio
import uuid

from temporalio.client import Client

from workflow import Cancelrequestworkflow
from shared import WorkflowInput

TASK_QUEUE = "cancel-requests"


async def main() -> None:
    """Connect to Temporal and start a single workflow execution."""
    client = await Client.connect("localhost:7233")

    handle = await client.start_workflow(
        Cancelrequestworkflow.run,
        WorkflowInput(),  # TODO: populate the workflow input fields.
        id=f"cancelrequestworkflow-{uuid.uuid4()}",
        task_queue=TASK_QUEUE,
    )
    print(f"Started workflow {handle.id}")

    # NOTE: workflows that pause on a signal gate block here until signalled
    # (e.g. via `temporal workflow signal` or a client `handle.signal(...)`).
    result = await handle.result()
    print("Workflow result:", result)


if __name__ == "__main__":
    asyncio.run(main())
