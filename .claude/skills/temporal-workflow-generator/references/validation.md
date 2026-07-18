# Temporal Python Workflow Validation Guide

Common errors, their root causes, and exact fixes. Grouped by when they surface.

---

## Table of contents

1. [Determinism violations — crash the sandbox](#determinism)
2. [Import isolation errors](#imports)
3. [Missing required options on execute_activity](#missing-options)
4. [Serialization / type annotation failures](#serialization)
5. [Signal and query handler mistakes](#handlers)
6. [Worker registration gaps](#worker-registration)
7. [Compensation / saga mistakes](#saga)
8. [Child workflow pitfalls](#child-workflow)
9. [Retry policy mistakes](#retry)
10. [Syntax and type-check errors](#syntax)

---

## 1. Determinism violations — crash the sandbox {#determinism}

Temporal replays the workflow event history from the beginning on each worker restart. Any
code path that produces a different result on replay vs the original run causes a
`NonDeterminismError` and kills the workflow execution.

| Violation | Fix |
|---|---|
| `datetime.datetime.now()` | `workflow.now()` |
| `datetime.date.today()` | `workflow.now().date()` |
| `time.time()` | `workflow.now().timestamp()` |
| `random.random()` / `random.randint()` | `workflow.random().random()` |
| `random.choice(seq)` | `workflow.random().choice(seq)` |
| `uuid.uuid4()` | `workflow.uuid4()` |
| `asyncio.sleep(N)` | `await workflow.sleep(timedelta(seconds=N))` |
| `time.sleep(N)` | `await workflow.sleep(timedelta(seconds=N))` |
| Any HTTP / DB / file I/O in workflow method | Move the I/O to an `@activity.defn` function |
| `os.environ[...]` read inside workflow | Read env in the worker startup, pass as activity input |
| Iterating a `set` (non-deterministic order) | Use `sorted(my_set)` |
| Threading or multiprocessing inside workflow | Not allowed — use activities |

**Detection:** `NonDeterminismError` in workflow logs, or the workflow gets stuck.

**Example:**
```python
# WRONG — datetime.now() varies between original run and replay
@workflow.run
async def run(self, arg: WorkflowInput) -> str:
    ts = datetime.datetime.now().isoformat()   # ❌

# RIGHT
@workflow.run
async def run(self, arg: WorkflowInput) -> str:
    ts = workflow.now().isoformat()             # ✓
```

---

## 2. Import isolation errors {#imports}

Workflow sandboxing intercepts module imports. Modules that do I/O or register side effects at
import time must be isolated using `with workflow.unsafe.imports_passed_through():`.

### Symptom: ImportError or missing module at workflow startup
```
temporalio.worker._workflow_instance: ImportError: cannot import name 'process_order' from 'activities'
```
**Fix:** wrap all imports in `workflow.py` with:
```python
with workflow.unsafe.imports_passed_through():
    from activities import process_order, charge_payment
    from shared import WorkflowInput, ProcessOrderActivityInput
```

### Symptom: Module runs side-effect code during sandboxed import
```
RuntimeError: Event loop is closed
```
**Fix:** Same — wrap any third-party import that has startup I/O:
```python
with workflow.unsafe.imports_passed_through():
    import boto3          # boto3 reads ~/.aws at import
    from activities import ...
```

### Rule
All imports at the top level of `workflow.py` must be inside `with workflow.unsafe.imports_passed_through():`,
**except** for pure-stdlib modules (`asyncio`, `collections`, `datetime`, `typing`, etc.) and `temporalio`.

---

## 3. Missing required options on execute_activity {#missing-options}

### Error: `ValueError: start_to_close_timeout or schedule_to_close_timeout is required`
```python
# WRONG — missing timeout
result = await workflow.execute_activity(my_fn, MyInput())   # ❌

# RIGHT
result = await workflow.execute_activity(
    my_fn, MyInput(),
    start_to_close_timeout=timedelta(seconds=30),             # ✓
)
```

**What to use:**
- `start_to_close_timeout` — how long a single attempt can take (most common)
- `schedule_to_close_timeout` — total time across all retries (deadline)
- `schedule_to_start_timeout` — how long it can wait in the queue before starting

For most activities, set `start_to_close_timeout` conservatively (2× the expected P99 latency).

---

## 4. Serialization / type annotation failures {#serialization}

Temporal serializes inputs and outputs as JSON via its data converter. Non-serializable types
cause `PayloadEncodeError` or silent `None` values.

### Symptom: `PayloadEncodeError: Object of type X is not JSON serializable`
**Causes and fixes:**

| Problem | Fix |
|---|---|
| `datetime.datetime` field in dataclass | Use `str` (ISO format) or `int` (Unix timestamp) |
| Custom class (not `@dataclass`) | Convert to `@dataclass` |
| `Exception` object in activity return | Return a string description instead |
| `bytes` or `bytearray` | Base64-encode to `str` |
| `set` | Convert to `list` (sets aren't JSON) |
| `Decimal` | Use `float` or `str` |
| Nested non-dataclass objects | Flatten to dataclass or dict with serializable values |

### Symptom: Activity input arrives as `None` or empty
Activity input dataclasses must have **defaults for all fields**:
```python
# WRONG — no default, deserialization failure when field is missing
@dataclass
class MyInput:
    order_id: str                    # ❌ no default

# RIGHT
@dataclass
class MyInput:
    order_id: str = ""               # ✓
```

### Symptom: `from __future__ import annotations` causes annotation resolution errors
In some Temporal SDK versions, lazy annotations conflict with the SDK's runtime introspection.
If you see `TypeError: ... is not a type`, remove `from __future__ import annotations` from
`shared.py` and replace forward references with `typing.Optional[X]`.

---

## 5. Signal and query handler mistakes {#handlers}

### Error: `TypeError: signal handler must be a function, not a coroutine function`
```python
# WRONG — signal handler is async
@workflow.signal
async def approve_payment(self) -> None:   # ❌

# RIGHT — signal handler is sync
@workflow.signal
def approve_payment(self) -> None:          # ✓
    self._payment_approved = True
```

### Error: Query handler raises / has side effects
```python
# WRONG — query with side effect
@workflow.query
def get_status(self) -> str:
    self._query_count += 1    # ❌ side effect in query
    return self._status

# RIGHT — pure read
@workflow.query
def get_status(self) -> str:
    return self._status        # ✓
```

### Error: Signal state not initialized in `__init__`
Temporal replays from the beginning. If `__init__` doesn't set the attribute, any replay before
the signal arrives will raise `AttributeError`:
```python
# WRONG — attribute set only in signal handler
@workflow.signal
def approve(self) -> None:
    self._approved = True   # ❌ AttributeError on replay before signal

# RIGHT — always initialize in __init__
def __init__(self) -> None:
    self._approved: bool = False   # ✓

@workflow.signal
def approve(self) -> None:
    self._approved = True
```

---

## 6. Worker registration gaps {#worker-registration}

### Symptom: Workflow or activity poll times out silently
The workflow is submitted but no worker processes it. Check:
- The worker's `task_queue` matches the workflow submission's `task_queue`
- The workflow class is in `workflows=[...]`
- The activity function is in `activities=[...]`
- Compensation activities are also in `activities=[...]`
- Child workflow classes are also in `workflows=[...]`

### Symptom: `WorkflowNotFoundError` for a child workflow
```python
# WRONG — child registered under wrong name
@workflow.defn(name="FulfillmentV2")   # name used for lookup
class FulfillmentWorkflow: ...

# and Worker has: workflows=[FulfillmentWorkflow]  # ✓ — class is registered
# but started via: workflow.execute_child_workflow(FulfillmentWorkflow.run, ...)
# ← this is fine; the SDK uses the class to find the registered name
```
If the error persists, verify the child is on the same task queue the parent uses in
`execute_child_workflow(task_queue=...)`.

---

## 7. Compensation / saga mistakes {#saga}

### Mistake: Compensation not idempotent
Compensation activities will be retried if they fail. They must tolerate being called multiple times:
```python
# WRONG — not idempotent
@activity.defn
async def refund_payment(arg: RefundPaymentInput) -> str:
    charge(arg.payment_id)   # charges twice on retry! ❌

# RIGHT — use idempotency key
@activity.defn
async def refund_payment(arg: RefundPaymentInput) -> str:
    refund(arg.payment_id, idempotency_key=f"refund-{arg.payment_id}")  # ✓
```

### Mistake: Not registering compensation activities with the worker
Compensation functions must be in `activities=[...]` just like regular activities.

### Mistake: Compensation raises an exception
If a compensation activity raises and has `maximum_attempts=1`, the whole saga stalls.
Give compensations generous retry counts and never let them raise permanently:
```python
RetryPolicy(maximum_attempts=0)  # unlimited — compensations must eventually succeed
```

---

## 8. Child workflow pitfalls {#child-workflow}

### Mistake: Non-unique child workflow ID
```python
# WRONG — same ID every run, clashes with prior executions
await workflow.execute_child_workflow(
    ChildWorkflow.run, arg,
    id="fulfillment",                # ❌
)

# RIGHT — derive from parent ID for uniqueness
await workflow.execute_child_workflow(
    ChildWorkflow.run, arg,
    id=f"{workflow.info().workflow_id}-fulfillment",  # ✓
)
```

### Mistake: Child workflow on different task queue not configured
If `task_queue` is specified in `execute_child_workflow`, the child's activities must run on that
queue. Make sure a worker on that queue registers both the child workflow and its activities.

---

## 9. Retry policy mistakes {#retry}

### Mistake: `maximum_attempts=0` when you wanted `maximum_attempts=1`
`maximum_attempts=0` means **unlimited retries**. For "no retry", use `maximum_attempts=1`.

### Mistake: `non_retryable_error_types` typo
The error type string must exactly match the exception class name (not the fully-qualified path):
```python
# WRONG — fully qualified name
non_retryable_error_types=["mymodule.errors.InvalidInputError"]   # ❌

# RIGHT — just the class name, matching what ApplicationError(type=...) uses
non_retryable_error_types=["InvalidInputError"]                     # ✓
```

### Mistake: No `maximum_interval` on exponential backoff
Without a cap, exponential backoff grows unboundedly. Always set a reasonable ceiling:
```python
RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),   # ✓ cap at 5 min
    maximum_attempts=10,
)
```

---

## 10. Syntax and type-check errors {#syntax}

Run these before writing the generated files anywhere:

```bash
# Parse check
python -c "import ast; ast.parse(open('workflow.py').read()); print('OK')"

# Type check (if mypy installed)
mypy workflow.py activities.py shared.py --ignore-missing-imports

# Import check (detects missing deps and bad imports)
python -c "import workflow; import activities; import shared; print('imports OK')"
```

### `NameError: name 'X' is not defined`
Usually an activity or input class that was not imported inside
`with workflow.unsafe.imports_passed_through():`.

### `TypeError: __init__() takes 1 positional argument but 2 were given`
The `@workflow.run` method signature must be `async def run(self, arg: SomeInput) -> ...:` —
exactly one positional arg after `self`. Verify the dataclass name matches what is imported.

### `ModuleNotFoundError: No module named 'temporalio'`
```bash
pip install temporalio
```

For running the full test suite in this project:
```bash
pip install -e ".[dev]"
pytest tests/test_compiler.py -k temporal
```
