# Temporal Python SDK — Complete Code Patterns

Copy-paste-ready templates for every construct in a generated Temporal Python workflow.
All examples assume `temporalio` installed: `pip install temporalio`.

---

## Table of contents

1. [shared.py — input dataclasses](#shared)
2. [activities.py — activity definitions](#activities)
3. [workflow.py — workflow class](#workflow)
   - [Workflow class skeleton](#workflow-skeleton)
   - [Signals](#signals)
   - [Queries](#queries)
   - [Timers (sleep)](#timers)
   - [Parallel execution](#parallel)
   - [Branch / conditional](#branch)
   - [Signal gate (wait_condition)](#signal-gate)
   - [Child workflow](#child-workflow)
   - [Compensation / saga](#compensation)
4. [worker.py — worker process](#worker)
5. [starter.py — workflow starter](#starter)
6. [Retry policy patterns](#retry-policy)
7. [Activity implementation guide](#activity-implementation)

---

## 1. shared.py — input dataclasses {#shared}

Temporal passes a **single dataclass** to each workflow and activity so inputs evolve
compatibly via field addition (backward compatible) rather than positional changes.

```python
# shared.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowInput:
    """Top-level input to the workflow."""
    order_id: str = ""
    customer_id: str = ""
    items: list[str] = field(default_factory=list)


@dataclass
class ProcessOrderActivityInput:
    """Input to ProcessOrderActivity."""
    order_id: str = ""
    customer_id: str = ""


@dataclass
class ChargePaymentActivityInput:
    """Input to ChargePaymentActivity."""
    order_id: str = ""
    amount_cents: int = 0
```

**Rules:**
- Always use `@dataclass`, never plain `dict` — Temporal serializes via JSON converter
- Every field must have a default so the dataclass is constructable without arguments
- Supported field types: `str`, `int`, `float`, `bool`, `list[T]`, `dict[str, T]`, nested dataclasses
- Avoid `datetime.datetime` fields — serialize as ISO string `str` instead
- `from __future__ import annotations` is safe here

---

## 2. activities.py — activity definitions {#activities}

```python
# activities.py
from __future__ import annotations
from temporalio import activity

from shared import ProcessOrderActivityInput, ChargePaymentActivityInput


@activity.defn(name="ProcessOrderActivity")
async def process_order(arg: ProcessOrderActivityInput) -> str:
    """Validate and persist the order. Retryable and idempotent."""
    activity.logger.info("Processing order %s", arg.order_id)
    # Long-running activities must heartbeat so Temporal detects worker death
    activity.heartbeat()
    # ... real implementation: DB write, API call, etc. ...
    return f"processed:{arg.order_id}"


@activity.defn(name="ChargePaymentActivity")
async def charge_payment(arg: ChargePaymentActivityInput) -> str:
    """Charge the customer. Use idempotency keys to survive retries."""
    activity.logger.info("Charging %d cents for order %s", arg.amount_cents, arg.order_id)
    # Idempotency: use arg.order_id as the idempotency key with your payment provider
    return "charged"
```

**Rules:**
- `@activity.defn(name="...")` — the name string is what Temporal uses to route to the function;
  it does not need to match the Python function name, but it must be unique per task queue
- Function may be `async def` or sync `def` — never mix in the same `Worker(..., activities=[...])`
- Activities **can** do anything: HTTP, DB, file I/O, subprocess — this is the only safe place
- `activity.logger` is structurally enriched; prefer it over bare `logging`
- `activity.heartbeat()` must be called periodically if `heartbeat_timeout` is set

---

## 3. workflow.py — workflow class {#workflow}

### Workflow class skeleton {#workflow-skeleton}

```python
# workflow.py
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import process_order, charge_payment
    from shared import WorkflowInput, ProcessOrderActivityInput, ChargePaymentActivityInput


@workflow.defn
class OrderWorkflow:
    """Orchestrates the full order lifecycle."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._payment_approved: bool = False

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        self._status = "running"
        compensations: list[tuple[Callable[..., Any], Any]] = []
        try:
            # --- workflow body goes here ---
            result = await workflow.execute_activity(
                process_order,
                ProcessOrderActivityInput(order_id=arg.order_id, customer_id=arg.customer_id),
                start_to_close_timeout=timedelta(seconds=30),
            )
            compensations.append((cancel_order, CancelOrderInput(order_id=arg.order_id)))

            await workflow.execute_activity(
                charge_payment,
                ChargePaymentActivityInput(order_id=arg.order_id, amount_cents=1000),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            for _fn, _inp in reversed(compensations):
                await workflow.execute_activity(
                    _fn, _inp, start_to_close_timeout=timedelta(seconds=60)
                )
            self._status = "compensated"
            raise
        self._status = "completed"
        return self._status
```

**Critical rules for workflow code:**
- `with workflow.unsafe.imports_passed_through():` — wrap ALL imports at the top level of workflow.py
- Workflow class methods must be **deterministic**: same inputs → same outputs, always
- Never call `datetime.datetime.now()` → use `workflow.now()`
- Never call `random.*` → use `workflow.random()`
- Never call `uuid.uuid4()` → use `workflow.uuid4()`
- Never call `asyncio.sleep()` → use `await workflow.sleep(timedelta(seconds=N))`
- Never do I/O (HTTP, DB, file) inside workflow methods → move to activities

---

### Signals {#signals}

Signals let external callers push data into a running workflow.

```python
@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._payment_approved: bool = False
        self._cancellation_requested: bool = False

    # Signal handler — must be sync def, not async def
    @workflow.signal
    def approve_payment(self, approved: str) -> None:
        """Called by an external actor when payment is approved."""
        self._payment_approved = approved == "yes"

    @workflow.signal
    def request_cancellation(self) -> None:
        """Cancel the workflow gracefully."""
        self._cancellation_requested = True

    @workflow.run
    async def run(self, arg: WorkflowInput) -> str:
        # Wait for the payment approval signal before charging
        await workflow.wait_condition(lambda: self._payment_approved)
        # ... proceed with charging ...
        return "completed"
```

**Sending a signal from a client:**
```python
handle = client.get_workflow_handle("order-workflow-id")
await handle.signal(OrderWorkflow.approve_payment, "yes")
```

**Rules:**
- `@workflow.signal` handlers must be **sync** `def` (not `async def`)
- Initialize all signal state in `__init__` — Temporal replays from the start
- Signal handlers execute synchronously between workflow coroutine checkpoints

---

### Queries {#queries}

Queries let external callers read workflow state synchronously (no side effects).

```python
    @workflow.query
    def get_status(self) -> str:
        """Return the current workflow status."""
        return self._status

    @workflow.query
    def get_order_id(self) -> str:
        """Return the order ID being processed."""
        return self._order_id
```

**Reading a query from a client:**
```python
handle = client.get_workflow_handle("order-workflow-id")
status = await handle.query(OrderWorkflow.get_status)
```

**Rules:**
- `@workflow.query` handlers must be **sync** `def` and must have **no side effects**
- Cannot use `await` inside a query handler
- Return type must be serializable (str, int, float, bool, dataclass, list, dict)

---

### Timers (sleep) {#timers}

Durable timers survive worker restarts. The workflow pauses; it does not hold a thread.

```python
# At module level in workflow.py (not inside a method):
PAYMENT_TIMEOUT = timedelta(hours=24)
RETRY_DELAY = timedelta(minutes=5)

# Inside @workflow.run:
await workflow.sleep(PAYMENT_TIMEOUT)

# Dynamic duration from design.timers:
await workflow.sleep(timedelta(seconds=design_timer.duration_seconds))
```

**Rules:**
- Always use `workflow.sleep()`, never `asyncio.sleep()` or `time.sleep()`
- Timers survive worker restarts and service downtime — they are durable
- Duration is measured in wall-clock time by the Temporal service, not CPU time

---

### Parallel execution {#parallel}

Run multiple activities concurrently using `asyncio.gather`:

```python
import asyncio  # allowed in workflow.py — asyncio itself is deterministic

# Concurrent activities:
results = await asyncio.gather(
    workflow.execute_activity(
        process_order,
        ProcessOrderActivityInput(order_id=arg.order_id),
        start_to_close_timeout=timedelta(seconds=30),
    ),
    workflow.execute_activity(
        notify_warehouse,
        NotifyWarehouseActivityInput(order_id=arg.order_id),
        start_to_close_timeout=timedelta(seconds=10),
    ),
)
order_result, warehouse_result = results
```

**Rules:**
- `asyncio.gather` is allowed — `asyncio` is itself deterministic in Temporal's sandbox
- Each `execute_activity` inside `gather` must NOT have `await` — pass the coroutine directly
- All gathered coroutines must be Temporal SDK calls (execute_activity, execute_child_workflow, sleep)
- Do not `await` plain Python coroutines inside `gather` — they bypass Temporal's event loop

---

### Branch / conditional {#branch}

```python
# Predicate from a prior activity result or signal state:
if "express" in arg.shipping_type:
    await workflow.execute_activity(
        express_fulfillment,
        ExpressFulfillmentInput(order_id=arg.order_id),
        start_to_close_timeout=timedelta(seconds=60),
    )
else:
    await workflow.execute_activity(
        standard_fulfillment,
        StandardFulfillmentInput(order_id=arg.order_id),
        start_to_close_timeout=timedelta(seconds=120),
    )
```

**Rules:**
- Predicates must be **deterministic** — derive from workflow input, activity results, or signals
- Do not branch on `datetime.now()`, `random()`, environment variables, or external state read inside the workflow

---

### Signal gate (wait_condition) {#signal-gate}

Pause the workflow until a condition is true:

```python
# Simple: wait for a specific signal
await workflow.wait_condition(lambda: self._payment_approved)

# With timeout: proceed after 24h even without the signal
timed_out = not await workflow.wait_condition(
    lambda: self._payment_approved,
    timeout=timedelta(hours=24),
)
if timed_out:
    # Handle timeout path
    await workflow.execute_activity(cancel_order, ...)
```

**Rules:**
- The lambda must be **deterministic** and reference only `self` state
- `wait_condition` with a `timeout` returns `False` on timeout, `True` if condition became true
- Do not do I/O inside the lambda

---

### Child workflow {#child-workflow}

```python
# Inside @workflow.run:
child_result = await workflow.execute_child_workflow(
    FulfillmentWorkflow.run,
    FulfillmentWorkflowInput(order_id=arg.order_id),
    id=f"{workflow.info().workflow_id}-fulfillment",  # unique, deterministic ID
    task_queue="fulfillment-task-queue",
)
```

**The child workflow class (can live in the same workflow.py or a separate file):**
```python
@workflow.defn
class FulfillmentWorkflow:
    @workflow.run
    async def run(self, arg: FulfillmentWorkflowInput) -> str:
        await workflow.execute_activity(
            pick_and_pack,
            PickAndPackInput(order_id=arg.order_id),
            start_to_close_timeout=timedelta(minutes=10),
        )
        return "fulfilled"
```

**Worker must register child workflow types:**
```python
Worker(
    client,
    task_queue=TASK_QUEUE,
    workflows=[OrderWorkflow, FulfillmentWorkflow],  # both parent and child
    activities=[process_order, pick_and_pack],
)
```

---

### Compensation / saga {#compensation}

The saga pattern rolls back completed activities on failure:

```python
@workflow.run
async def run(self, arg: WorkflowInput) -> str:
    self._status = "running"
    compensations: list[tuple[Callable[..., Any], Any]] = []
    try:
        # Step 1: reserve inventory
        await workflow.execute_activity(
            reserve_inventory,
            ReserveInventoryInput(sku=arg.sku, qty=arg.qty),
            start_to_close_timeout=timedelta(seconds=30),
        )
        # Register the undo for step 1
        compensations.append((
            release_inventory,
            ReleaseInventoryInput(sku=arg.sku, qty=arg.qty),
        ))

        # Step 2: charge payment
        await workflow.execute_activity(
            charge_payment,
            ChargePaymentInput(amount=arg.amount),
            start_to_close_timeout=timedelta(seconds=30),
        )
        # Register the undo for step 2
        compensations.append((
            refund_payment,
            RefundPaymentInput(amount=arg.amount, order_id=arg.order_id),
        ))

        # Step 3: ship order (no undo needed — final step)
        await workflow.execute_activity(
            ship_order,
            ShipOrderInput(order_id=arg.order_id),
            start_to_close_timeout=timedelta(minutes=5),
        )

    except Exception:
        # Run compensations in reverse (LIFO)
        for _fn, _inp in reversed(compensations):
            await workflow.execute_activity(
                _fn, _inp,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
        self._status = "compensated"
        raise

    self._status = "completed"
    return self._status
```

**Rules:**
- Compensation activities must be **idempotent** — they may be retried
- Register compensations immediately after the activity they undo succeeds
- Run compensations with generous `maximum_attempts` — they must not fail
- The final step typically has no compensation (it's the commit point)

---

## 4. worker.py — worker process {#worker}

```python
# worker.py
from __future__ import annotations

import asyncio
from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from workflow import OrderWorkflow, FulfillmentWorkflow
    from activities import process_order, charge_payment, reserve_inventory, release_inventory

TASK_QUEUE = "order-workflow-task-queue"


async def main() -> None:
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow, FulfillmentWorkflow],
        activities=[process_order, charge_payment, reserve_inventory, release_inventory],
    )
    print(f"Worker started on {TASK_QUEUE!r}. Ctrl+C to exit.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
```

**Rules:**
- Every workflow class used in any `execute_child_workflow` must appear in `workflows=[...]`
- Every activity function used in any `execute_activity` must appear in `activities=[...]`
- Compensation activity functions must also be registered
- Task queue must match what the workflow uses — mismatches give silent poll timeouts

---

## 5. starter.py — workflow starter {#starter}

```python
# starter.py
from __future__ import annotations

import asyncio
import uuid
from temporalio.client import Client
from workflow import OrderWorkflow
from shared import WorkflowInput

TASK_QUEUE = "order-workflow-task-queue"


async def main() -> None:
    client = await Client.connect("localhost:7233")

    handle = await client.start_workflow(
        OrderWorkflow.run,
        WorkflowInput(order_id="ORD-001", customer_id="CUST-42", items=["sku-1"]),
        id=f"order-{uuid.uuid4()}",
        task_queue=TASK_QUEUE,
    )
    print(f"Started workflow {handle.id!r}")

    result = await handle.result()
    print("Result:", result)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Retry policy patterns {#retry-policy}

```python
from temporalio.common import RetryPolicy
from datetime import timedelta

# Conservative: try 3 times with exponential backoff, cap at 1 minute
RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    maximum_interval=timedelta(seconds=60),
)

# Aggressive for idempotent activities (payment webhooks, DB writes)
RetryPolicy(
    initial_interval=timedelta(milliseconds=100),
    backoff_coefficient=1.5,
    maximum_attempts=10,
    non_retryable_error_types=["InvalidInputError", "AuthorizationError"],
)

# Unlimited retries for critical steps (use with care)
RetryPolicy(maximum_attempts=0)  # 0 = unlimited

# No retry
RetryPolicy(maximum_attempts=1)
```

**non_retryable_error_types** should list exception class names for errors that are permanent
(bad input, auth failure) — retrying them wastes time and quota.

---

## 7. Activity implementation guide {#activity-implementation}

### HTTP call
```python
@activity.defn(name="CallExternalApiActivity")
async def call_external_api(arg: CallExternalApiActivityInput) -> str:
    import httpx  # safe to import in activities
    async with httpx.AsyncClient() as client:
        resp = await client.post(arg.url, json={"order_id": arg.order_id}, timeout=10.0)
        resp.raise_for_status()
        return resp.json().get("status", "ok")
```

### Database write
```python
@activity.defn(name="PersistOrderActivity")
async def persist_order(arg: PersistOrderActivityInput) -> str:
    import asyncpg  # safe to import in activities
    conn = await asyncpg.connect(dsn=os.environ["DATABASE_URL"])
    try:
        await conn.execute(
            "INSERT INTO orders (id, status) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            arg.order_id, "pending",
        )
    finally:
        await conn.close()
    return "persisted"
```

### Long-running with heartbeat
```python
@activity.defn(name="ProcessLargeFileActivity")
async def process_large_file(arg: ProcessLargeFileActivityInput) -> str:
    for i, chunk in enumerate(read_chunks(arg.file_path)):
        activity.heartbeat(i)           # must call before heartbeat_timeout expires
        process_chunk(chunk)
    return "done"
```

### Raising non-retryable errors
```python
from temporalio.exceptions import ApplicationError

@activity.defn(name="ValidateOrderActivity")
async def validate_order(arg: ValidateOrderActivityInput) -> str:
    if not arg.order_id:
        raise ApplicationError(
            "Order ID is required",
            type="InvalidInputError",   # matches non_retryable_error_types
            non_retryable=True,
        )
    return "valid"
```
