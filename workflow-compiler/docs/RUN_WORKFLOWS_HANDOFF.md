# Running generated workflows — from downloaded bundle to an in-app Run button

**Status date:** 2026-08-12 · **Branch:** `feat/spec-dialogue`

The compiler's last stage emits a runnable Temporal bundle. Until tonight nobody had
ever executed one. Doing so found three defects that no test caught, because the only
thing that proves codegen worked is running the code.

This document has two halves:

1. **§1–4 — what works today**, measured, so you can run a bundle by hand and know
   what to expect. This is prerequisite knowledge for the second half.
2. **§5–8 — the in-app Run feature.** ✅ **Built 2026-08-11** — see §8 for what is
   done and what is still unverified, and `docs/RUN_FEATURE_DESIGN.md` for the
   decisions. §5.3's three worker-lifecycle options were settled on **A**, and
   §7 (sample values in `starter.py`) shipped with it.

Everything in §1–4 was executed against a live Temporal server on 2026-08-12. Where
something is unproven it says so.

---

## 1. What "generated bundle" means

`approve-spec` runs graph → CVPA → Temporal *design* → **codegen**. The design is
specification-only; codegen is deterministic Jinja rendering of it (no LLM). One bundle
per workflow, plus shared project files:

```
<slug>/shared.py            dataclasses: WorkflowInput + one Input per activity
<slug>/activities.py        @activity.defn stubs, each returning a typed placeholder
<slug>/workflow.py          @workflow.defn — the orchestration, saga, signals, queries
<slug>/worker.py            registers workflow + activities on a task queue
<slug>/starter.py           starts one execution
<slug>/test_stepthrough.py  step-through harness
<slug>/README.md
contracts.py                every workflow's WorkflowInput in one place
README.md
```

> ⚠️ **`GET /projects/{id}/files` serves the bundle stored at approve time, not a fresh
> render.** After changing codegen you must re-approve, or re-render from the stored
> design (§4.3). This cost an hour tonight: the fix was correct and the output looked
> unchanged.

---

## 2. Running a bundle by hand (verified)

```bash
pip install temporalio                       # already in this worktree's .venv
temporal server start-dev --headless --port 7233     # terminal 1
cd generated/<project-id>/<slug>
python worker.py                             # terminal 2 — silent when healthy
python starter.py                            # terminal 3
```

`worker.py` prints nothing on success. To see what actually happened, ask the server:

```bash
temporal workflow list --address localhost:7233
temporal workflow describe --address localhost:7233 -w <workflow-id>
temporal workflow show --address localhost:7233 -w <workflow-id>     # full history
```

### Measured run — `order-fulfillment-workflow`, 2026-08-12

`temporal workflow show` gave 44 history events: a chain of
`ActivityTaskScheduled → Started → Completed` for every activity in the plan, ending at
`TimerStarted`. The workflow then sits, by design, on a **24-hour SLA timer**
(`SHIPMENT_SLATIMER = timedelta(seconds=86400)`) waiting for a signal.

So a bundle **does** execute. It does not *finish* unless you signal it (§2.1) or wait
out the timer, at which point the saga compensations fire.

### 2.1 Sending a signal

```bash
temporal workflow signal --address localhost:7233 \
  -w <workflow-id> --name <SignalName> --input '"ORD-1"' --input '"carrier delay"'
```

Two things bite here, both now fixed in codegen but present in **any bundle generated
before 2026-08-12**:

- **One `--input` per parameter.** A single JSON object is passed as one argument and
  the handler raises `TypeError: ... missing 1 required positional argument`, which
  fails the workflow task and puts it in a retry loop.
- **The signal name used to be the snake_cased method**, not the name in the spec
  (§6.2). On an old bundle, signal `slabreach_alert`, not `SLABreachAlert`.

---

## 3. The bundle is a scaffold — what needs hand-editing

This is the honest gap between "it runs" and "it does something".

| File | What ships | What you must do |
|---|---|---|
| `starter.py` | `WorkflowInput()` with a `# TODO: populate` comment | Fill in real field values |
| `activities.py` | Each activity returns a typed placeholder | Implement the real side effects |
| `workflow.py` | Complete — orchestration, saga, signals, queries | Usually nothing |

`workflow.py` is the part the compiler is actually good at. The stubs are deliberate:
the compiler knows the *shape* of the process, not your systems.

**§7 proposes closing the `starter.py` half of this automatically.**

---

## 4. Verified facts worth not rediscovering

### 4.1 Compensations survive into the saga
The handoff flagged this as the field most at risk. It holds. `workflow.py` builds
`compensations: list[tuple[Callable, Any]]`, appends on each protected step, and on any
exception runs `for _comp_fn, _comp_arg in reversed(compensations)` before setting
`self._status = "compensated"` and re-raising. Reversed order, i.e. correct saga
semantics.

### 4.2 The graph-health gate blocks codegen, and says so
`approve-spec` auto-approves the graph only above `graph_health_threshold` (default
**0.9**). Below it, the workflow stops at `stage=reviewed`, the project becomes
`NEEDS_ATTENTION`, and **no files are generated**.

The reason is reported as a blocking finding — not in `project.warnings`, which is
empty and misled me at first:

```
[blocking] Graph review :: graph health 0.45 below threshold 0.90 — left pending
           for manual review
           suggestion: review and approve the graph manually
```

The manual override is `POST /approve {workflow_id}` (the classic graph gate). It runs
CVPA → design → codegen and takes several minutes.

> Health 0.45 came from orphan / dead-end / unreachable nodes in a spec extracted from a
> single-workflow document. That is a *content* problem, not a pipeline bug.

### 4.3 Re-rendering a bundle without re-approving

```python
import json, pathlib
from workflow_compiler.models import TemporalWorkflowDesign
from workflow_compiler.codegen.temporal import TemporalPythonCodeGenerator

data = json.loads(pathlib.Path(".workflow_state/<workflow-id>.json").read_text("utf-8"))
design = TemporalWorkflowDesign.model_validate(data["temporal_design"])
bundle = TemporalPythonCodeGenerator().generate(design)   # bundle.files
```

Useful for iterating on templates without paying for an LLM re-approval.

### 4.4 Client timeouts that are not failures
Node's `fetch` (undici) has a **300s headers timeout**. Long API calls surface as
`UND_ERR_HEADERS_TIMEOUT` on the client while the server keeps working — and the request
may be cancelled on disconnect. Use `POST /projects/{id}/jobs` (`kind: validate|approve`)
for anything long; those runs survive disconnection and are pollable at `GET /jobs/{id}`.

---

## 5. The in-app Run feature — what to build

Today a user downloads a zip and opens three terminals. The goal is a **Run** control in
the project page's Results tab that starts an execution and streams status back.

### 5.1 Shape

```
Results tab
  └── [ Run workflow ]  ← per generated workflow (slug)
        ├── input form   ← generated from WorkflowInput fields (§7)
        ├── status       ← Running / Completed / Failed / Compensated
        ├── step trail   ← from workflow history, or the current_step query
        └── signals      ← a button per declared signal
```

### 5.2 Server side

Suggested surface, mirroring the existing jobs API rather than inventing a new one:

```
POST   /projects/{id}/runs      {slug, input}     → {run_id, workflow_id}
GET    /projects/{id}/runs                        → list, newest first
GET    /runs/{run_id}                             → status + history projection
POST   /runs/{run_id}/signal    {name, args}
DELETE /runs/{run_id}                             → terminate
```

The compiler package must not import the Temporal SDK — keep the split the codebase
already enforces (`interfaces/`, no vendor SDK in agent or compiler code). Put the client
behind an interface, e.g. `interfaces/executor.py::WorkflowExecutor`, with a
`TemporalExecutor` implementation and an in-memory fake for tests.

### 5.3 The hard part: worker lifecycle

Starting a workflow is easy. **Something must run the worker**, and the generated
activities are stubs in files on disk, not importable modules of the API process.

Three options, in ascending order of effort:

| Option | How | Trade-off |
|---|---|---|
| **A. Subprocess worker** | API spawns `python worker.py` in the bundle directory, tracked like a `Job` | Simplest; the bundle already works this way (§2). Process lifecycle, port/queue collisions, and cleanup are yours |
| **B. In-process dynamic import** | `importlib` the bundle and register it on a worker owned by the API | No subprocess, but generated code executes inside the API process — sandboxing and reload problems |
| **C. Sandbox / container** | Run each bundle in its own container | Correct for anything multi-tenant; heaviest |

**Recommendation: A.** It matches how the bundle is already designed to run, keeps
generated code out of the API process, and reuses the `Job` machinery (background,
cancellable, survives navigation) that already exists for validate/approve.

### 5.4 Prerequisite: is Temporal even there?

The feature needs a reachable Temporal server. Decide and surface it explicitly:
detect at `GET /health`, show the UI control disabled with "no Temporal server
configured" rather than failing on click, and make the address configurable
(`WORKFLOW_COMPILER_TEMPORAL_ADDRESS`, default `localhost:7233`).

---

## 6. Defects found by running bundles — full record

All three were invisible to unit tests, `ruff`, `mypy`, and `next build`.

### 6.1 `WorkflowInput` missing fields the workflow reads — **FIXED**

```
AttributeError: 'WorkflowInput' object has no attribute 'customer_order_items'.
                Did you mean: 'customer_order'?
```

`WorkflowInput` is built from `design.workflow_inputs`; the `arg.<ref>` expressions come
from step **bindings**. Those two halves of the design are produced together and can
disagree, and the emitter wrote the reference without checking the field existed — so
the bundle imported cleanly, passed every static check, and died on its first activity.

Fixed in `generator.py::_workflow_input_fields`, which now also declares every workflow
input a binding cites, typed from the activity parameter it feeds. Note the adjacent
`STEP_OUTPUT` branch already had exactly this discipline (it drops unresolvable refs
rather than emitting a fabricated name) — only `WORKFLOW_INPUT` lacked it.

Regression: `tests/test_codegen_workflow_input.py` asserts the invariant statically —
the set of `arg.X` reads in `workflow.py` is a subset of the fields declared in
`shared.py`.

### 6.2 Signals and queries registered under the wrong name — **FIXED**

The template emitted a bare `@workflow.signal`, so the SDK registered the *snake_cased
Python method*. The design, the docstring, and the workflow's own log line all said
`SLABreachAlert`; the handler answered to `slabreach_alert`.

Proven against a live server: signalling `SLABreachAlert` did **nothing at all** — no
error, no dispatch — while `slabreach_alert` reached the handler. For a bounded wait
that means the workflow hangs to its timeout and then compensates, i.e. an integration
that looks wired up and silently is not.

Fixed in `templates/workflow.py.jinja`: `@workflow.signal(name="…")` and
`@workflow.query(name="…")`. Signal payload params now also default to `""`, so a signal
delivered with fewer args than declared does not raise `TypeError` inside the handler and
fail the workflow task.

### 6.3 `MODIFY` patches wrote raw strings onto enum fields — **FIXED**

Not codegen, but same class of bug and it reached the same place. A dialogue answer
modified an event's `kind`; the applier used `model_copy(update=...)`, which bypasses
pydantic, so a plain string landed on a field typed `EventKind` and surfaced far away as
`'str' object has no attribute 'value'` in the spec renderer — returned as a 500 that
Chrome reported as a *CORS error*. Fixed in `agents/review_pipeline.py` by re-validating
the node. Affected the review pipeline and edit-request path too, not just the dialogue.

**Generalizable lesson:** treat `model_copy(update=...)` on a validated model as a smell.
It is the one mutation path in this codebase that skips validation.

---

## 7. Recommended follow-up: populate `WorkflowInput` from the spec

Agreed direction. Today `starter.py` ships:

```python
WorkflowInput(),  # TODO: populate the workflow input fields.
```

so a first run executes activities against empty inputs. The spec already knows the
input names and types, and `_default_for(annotation)` already exists in the generator.

**Proposal.** Emit sample values in `starter.py` derived from the spec's declared inputs
— `order_id="ORD-1"` for a `str`, `{}` for a `dict`, `[]` for a `list` — keeping the
`TODO` comment so it is obviously placeholder data. That makes a freshly generated
bundle runnable end to end with one command and no editing, which is also the
precondition for the in-app Run feature's input form (§5.1) to have sensible defaults.

Where it goes: `generator.py` already computes the `WorkflowInput` fields
(`_workflow_input_fields`); pass those fields to `starter.py.jinja` and render kwargs.
Keep it deterministic — no LLM, consistent with "the LLM specifies; deterministic code
emits".

The activity stubs are a separate and much larger question; leave them stubs.

---

## 8. Definition of done for the Run feature

**Built 2026-08-11 on `feat/run-workflows`** (commits `b170514`, `ab4457a`, `a31e259`).

- [x] A user can run a generated workflow from the Results tab without leaving the app
- [x] Status, current step, and terminal outcome are visible in the UI
- [x] Declared signals can be sent from the UI, by their **spec** names (§6.2)
- [x] A compensating (failed) run is visibly distinguishable from a completed one
- [x] Absent Temporal is reported as a disabled control, never a click-time error
- [x] No Temporal SDK import inside `compiler`/`agents` — executor stays behind an interface
- [x] `pytest`, `ruff check src tests` green; `mypy src` at its 35-error baseline
- [x] §7 — generated starters ship sample input (`order_id="ORD-1"`), verified by
      re-rendering the stored design of the bundle that ran on 2026-08-12

Design notes and the decisions behind them: **`docs/RUN_FEATURE_DESIGN.md`**.

### What was verified live

Against a Temporal dev server on an isolated port, driving the HTTP API the
browser uses (no LLM anywhere — the approved project was reused):

- the bundle materialized to disk (7 files) and the worker subprocess started;
- **every activity ran in plan order**, including the parallel pair
  (`SendOrderConfirmation` + `NotifyWarehouse`), each named in the step trail;
- the workflow parked on its 24-hour SLA timer exactly as §2 describes;
- a signal sent under its **spec** name was delivered (`signal_received`).

### Not yet verified

- The **browser** path. The API layer the UI calls is proven end to end; the
  React panel itself is only proven by `tsc` + `next build`.
- A genuinely **compensated** run. The compensation path is implemented and
  distinguished via the workflow's own status query, but the verified run took
  the success path. A design that declares no string-returning query will report
  a clean rollback as `failed` — honest, but a known limit.
- A **worker that dies after startup**. The pool catches an immediate exit and
  reports the child's output; a worker that dies later leaves the run sitting in
  `running` with no explanation. Surfacing that is the next obvious hardening.

---

## 9. Reference

- `docs/PIPELINE_HANDOFF.md` — the pipeline itself; §0.0 has the 2026-08-11 cloud results
- `docs/PIPELINE_RUN_LOG.md` — measured Spark runs and corrections
- `docs/HOW_IT_WORKS.md` — §9.2 CLI reference, §9.3 HTTP API reference
- `.claude/skills/temporal-workflow-generator` — the codegen skill
- Generated example verified tonight:
  `generated/6bd74f67-c355-4812-b03b-1af72837bbe3/order-fulfillment-workflow/`
