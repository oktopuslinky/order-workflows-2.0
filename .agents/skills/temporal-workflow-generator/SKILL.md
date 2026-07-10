---
name: temporal-workflow-generator
description: Generate, validate, and implement Temporal Python SDK workflows from a TemporalWorkflowDesign plan. Use this skill whenever the user asks to generate Temporal workflow code, implement Temporal activities or workers, set up a Temporal Python project, create a saga/compensation pattern, handle signals or queries in Temporal, translate a workflow plan into running code, or debug/fix generated Temporal Python code. Also use when the user has a TemporalWorkflowDesign JSON/dict and wants runnable code, or when the user says "generate the Temporal code", "implement the workflow", or "run codegen".
---

# Temporal Workflow Generator

Turn a `TemporalWorkflowDesign` blueprint into validated, runnable Temporal Python SDK code.

The `TemporalWorkflowDesign` is produced by `TemporalGeneratorAgent` in this project and carries:
declarations (activities, signals, queries, timers, child workflows, compensations) plus an optional
plan IR of typed `TemporalStep` nodes. The deterministic `TemporalPythonCodeGenerator` renders it
into 6 Python files — no LLM required at generation time.

---

## Step 1 — Generate

**Using the built-in generator (preferred):**
```python
from workflow_compiler.codegen.temporal.generator import to_temporal_python
from workflow_compiler.models import TemporalWorkflowDesign

design = TemporalWorkflowDesign(**design_dict)   # or load from WorkflowState.temporal_design
bundle = to_temporal_python(design, graph=state.workflow_graph)
out = Path("generated") / bundle.package_name
out.mkdir(parents=True, exist_ok=True)
for f in bundle.files:
    (out / f.path).write_text(f.content)
print(f"Written to {out}/")
```

**Using the CLI (offline mock, no API key):**
```bash
workflow-compiler compile examples/order_workflow.md --provider mock
```

**Writing code without the generator** — read `references/patterns.md` and produce all 6 files
from the annotated templates. The mapping from design fields to code is in the table below.

---

## Generated file layout

Every bundle produces 6 files under `<package_name>/`:

| File | Purpose |
|---|---|
| `shared.py` | `WorkflowInput` + per-activity input dataclasses |
| `activities.py` | `@activity.defn` stubs — implement business logic here |
| `workflow.py` | `@workflow.defn` class: `@workflow.run`, signals, queries |
| `worker.py` | Worker process (`python worker.py`) |
| `starter.py` | Workflow starter (`python starter.py`) |
| `README.md` | Setup and run instructions |

---

## Step 2 — Validate

Run the bundled validator on the generated directory before implementing anything:
```bash
python .Codex/skills/temporal-workflow-generator/scripts/validate_workflow.py <out_dir>
```

The validator catches: determinism violations, missing timeouts, import isolation errors, and
non-serializable type annotations. Read `references/validation.md` for the full catalogue of
errors, root causes, and fixes.

**Critical: these WILL crash the Temporal sandbox at runtime:**
- `datetime.datetime.now()` inside workflow → `workflow.now()`
- `random.random()` / `random.randint()` inside workflow → `workflow.random()`
- `uuid.uuid4()` inside workflow → `workflow.uuid4()`
- `asyncio.sleep()` inside workflow → `await workflow.sleep(timedelta(seconds=N))`
- Any direct I/O (HTTP, DB, file) inside `@workflow.defn` methods → move to an activity
- Top-level imports in `workflow.py` outside `with workflow.unsafe.imports_passed_through():` → wrap them

**These cause ActivityError or serialization failures:**
- `execute_activity()` without `start_to_close_timeout` → always set it
- Using plain `dict` as activity input/output → use a typed `@dataclass`
- `@workflow.signal` defined as `async def` → must be sync `def`

---

## Step 3 — Implement stubs

Activities are generated with `raise NotImplementedError(...)`. For each:

1. Replace the stub with real logic (HTTP call, DB write, queue publish, etc.)
2. Add `activity.heartbeat()` inside long-running loops to prevent heartbeat timeout
3. Use `activity.logger` — never `print` or `logging.getLogger` directly
4. Keep each activity retryable and idempotent by default

```python
@activity.defn(name="ProcessOrderActivity")
async def process_order(arg: ProcessOrderActivityInput) -> str:
    activity.logger.info("Processing order %s", arg.order_id)
    activity.heartbeat()          # required if activity may exceed heartbeat_timeout
    # ... real implementation ...
    return "processed"
```

---

## Design → code mapping

| `TemporalStep.kind` | Emitted code pattern |
|---|---|
| `activity` | `await workflow.execute_activity(fn, InputClass(...), start_to_close_timeout=timedelta(...), retry_policy=RetryPolicy(...))` |
| `child_workflow` | `await workflow.execute_child_workflow(ChildClass.run, ChildInput(...), id=f"...-{slug}", task_queue="...")` |
| `signal_gate` | `await workflow.wait_condition(lambda: self._signal_name_received)` |
| `timer` | `await workflow.sleep(TIMER_CONST)` where `TIMER_CONST = timedelta(seconds=N)` |
| `parallel` | `await asyncio.gather(workflow.execute_activity(...), workflow.execute_activity(...))` |
| `branch` | `if <condition>: ... else: ...` with TODO comment for the predicate |

**Compensation (saga pattern):** After each compensatable activity succeeds, push its undo function
onto a `compensations` list. The `except Exception` block runs them in reverse:
```python
compensations.append((rollback_order, RollbackOrderInput(order_id=arg.order_id)))
# ... more activities ...
except Exception:
    for _fn, _arg in reversed(compensations):
        await workflow.execute_activity(_fn, _arg, start_to_close_timeout=timedelta(seconds=60))
    raise
```

---

## Filling in an empty plan

When `TemporalWorkflowDesign.plan` is empty, `to_temporal_python` synthesises a linear plan from
`design.activities` ordered by `source_node_id` graph position. If writing manually:

1. List all activities from `design.activities` in declaration order
2. Emit one `execute_activity` call per activity
3. For each signal in `design.signals`, emit a `wait_condition` gate where it belongs in the flow
4. For each timer in `design.timers`, emit `workflow.sleep(timedelta(seconds=N))`

---

## Reference files

- **`references/patterns.md`** — complete, copy-paste-ready code for every construct:
  workflow class, activity, signal, query, timer, child workflow, parallel group, compensation saga,
  worker, starter. Read this when writing code from scratch.
- **`references/validation.md`** — determinism checklist, import rules, common runtime errors
  with root causes and exact fixes, type serialization gotchas, retry policy pitfalls.
