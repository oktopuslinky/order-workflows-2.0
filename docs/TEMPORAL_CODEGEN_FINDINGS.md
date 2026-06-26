# Temporal Codegen — Findings & Standard (subscription_upgrade_workflow post-mortem)

> **Status: resolved.** The design model now carries a typed plan IR, the design
> stage is fed the extracted facts, and the deterministic generator emits data
> flow, saga, and signal gates. The regenerated `generated/subscriptionupgradeworkflow/`
> runs under a Temporal `WorkflowEnvironment`: the happy path completes after the
> compliance signal and a forced mid-workflow failure fires compensations in reverse.
> See `tests/test_temporal_ir_runtime.py` for the validation gate. The sections below
> remain as the standard each generated bundle must continue to satisfy.

This document records why the generated `generated/subscriptionupgradeworkflow/` package
does not run correctly, traces each defect to its origin in the pipeline, and defines the
standard every generated Temporal workflow must meet going forward. It is grounded in the
Temporal Python SDK docs (`docs.temporal.io/develop/python/*`).

It is a companion to `architecture.md` (the pipeline harness) and
`DOCUMENT_FORMAT_GUIDE.md` (the input contract).

---

## 1. Root cause: facts are discarded before the Temporal design

`TemporalGeneratorAgent.run` (`agents/temporal.py`) renders the `design_temporal` prompt with
**only** `graph_to_text(workflow_graph)` and `cvpa_to_text(cvpa_classification)`. It never passes
`state.workflow_facts`.

Consequence: everything the document specified and the fact extractor captured — retry counts,
timeouts/SLAs, `compensates` relationships, API input/output field names, non-retryable error
types, business rules — is extracted and then **thrown away** before design. The LLM must
re-invent all of it from node labels, which is exactly where the hallucinations come from.

**Fix direction:** serialize the relevant `workflow_facts` (retries, timers, compensation
candidates, inputs/outputs, exceptions) into the `design_temporal` prompt so the design is
*derived from* the document, not guessed.

---

## 2. Defects in the generated package, traced to origin

| # | Symptom | Origin | Layer to fix |
|---|---------|--------|--------------|
| 1 | Saga never runs: `compensations` list never appended; rollback activities orphaned | LLM `compensates` didn't match activity `name`; `_compensations_by_activity` mapped nothing | design prompt + facts wiring |
| 2 | No data flow: activities called with empty `XInput()`; results discarded | template hardcodes `XInput()`, never binds results; design has no data-dependency model | design model + template |
| 3 | Signal gate is fake: handler sets a bool the run body never waits on | template emits no `workflow.wait_condition`; design doesn't link signal→gated step | design model + template |
| 4 | Wrong order: `applypromotionaldiscount` before `calculateprorationamount` | topo order ≠ data deps; deps not carried | design model |
| 5 | Timers dead: timer constants defined, never used | template renders constants but never applies them | template |
| 6 | Branches/parallelism flattened to a linear chain | template emits only linear `await`; no conditional/gather model | design model + template |
| 7 | Queries lie: every query returns `self._status` | template hardwires `return self._status` | design model + template |
| 8 | Weak typing: all input fields `str=""`, all activities `-> str` | design carries bare name lists; no types | design model |

---

## 3. What to note for next time (checklist for the generator)

Derived from the Temporal Python docs. A generated bundle is **correct** only if:

1. **Data flows.** Capture activity results (`result = await workflow.execute_activity(...)`) and
   thread them into downstream activity inputs. The top-level `WorkflowInput` fields must reach
   the first activities. No activity should receive an all-empty input unless it truly takes none.
2. **Saga is wired.** For each side-effecting activity with a compensation, append the
   compensation to the stack immediately after (or before) the activity succeeds; on exception,
   run the stack in reverse. (`temporal-py-failure` → "Implement rollback logic with the Saga
   pattern".)
3. **Signals gate the run.** A human/external wait must `await workflow.wait_condition(lambda: ...)`
   in the run body at the point it gates; the signal handler only flips state. (`temporal-py-message-passing`.)
4. **Retries/timeouts come from the document.** Each `execute_activity` gets a
   `start_to_close_timeout` and a `RetryPolicy` matching the doc's Retries/SLAs sections, including
   `non_retryable_error_types`. (`temporal-py-failure`.)
5. **Timers are applied,** not just declared — `await workflow.sleep(...)` or as activity timeouts.
6. **Branches/parallelism preserved.** Conditional reject paths become real branches; "in parallel"
   steps use `asyncio.gather` over `execute_activity` calls.
7. **Queries return real state,** never blanket `self._status`; query handlers never mutate.
8. **Determinism.** No I/O, `datetime.now`, or `random` in workflow code — use `workflow.now()` /
   `workflow.random()`; all I/O lives in activities. (`temporal-py-core`.)
9. **Worker registers everything** — workflow class + every activity (incl. compensations) on the
   task queue, and the bundle imports cleanly. (`temporal-py-setup`.)

---

## 4. Canonical Temporal patterns (from the docs, for the templates)

### Saga (`temporal-py-failure`)
```python
compensations = []
try:
    compensations.append({"activity": revert_inventory, "input": order})
    await workflow.execute_activity(reserve_inventory, order, start_to_close_timeout=timedelta(seconds=10))
    compensations.append({"activity": refund_payment, "input": order})
    payment_id = await workflow.execute_activity(charge_payment, order, start_to_close_timeout=timedelta(seconds=10))
except ActivityError:
    for c in reversed(compensations):
        await workflow.execute_activity(c["activity"], c["input"], start_to_close_timeout=timedelta(seconds=10))
    raise
```

### Signal-gated wait (`temporal-py-message-passing`)
```python
await workflow.wait_condition(lambda: self._approved)
```

### Custom retry (`temporal-py-failure`)
```python
retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=3.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=20,
    non_retryable_error_types=["InvalidCardFormat", "InsufficientFunds"],
)
```

---

## 5. Validation gate

Codegen is not "done" until the bundle: (a) imports without error, (b) passes a Temporal
`WorkflowEnvironment` time-skipping test that runs the workflow with mocked activities and asserts
the happy path completes and a forced mid-workflow failure triggers compensations in reverse
(`temporal-py-testing`). This converts "looks plausible" into "provably runs".
