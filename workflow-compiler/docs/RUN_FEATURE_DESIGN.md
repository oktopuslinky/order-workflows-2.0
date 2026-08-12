# In-app Run feature — build notes

Working notes for the RUN_WORKFLOWS_HANDOFF §5 build. Decisions confirmed with the
user 2026-08-11; folded into the handoff when the feature lands.

## Decisions taken

| Question | Answer | Why |
|---|---|---|
| Worker lifecycle | **A — subprocess** (§5.3) | Matches how the bundle is already designed to run; keeps generated code out of the API process. |
| Which bundle executes | **The files on disk** under `generated/<project-id>/<slug>/` | §3 expects users to hand-edit `activities.py`. Running the stored bundle would silently execute placeholder stubs instead of their real implementations. Absent directory ⇒ a reported precondition, never a click-time failure. |
| Input form | **Typed per-field**, prefilled from §7 samples | What §5.1 asks for; makes §7 pay off twice. |
| Run persistence | **In-memory registry**, Temporal is the durable truth | Mirrors `JobManager` (`api/jobs.py`), which is explicit that jobs live only in memory. Temporal itself retains history, so a restarted API can still describe a past run by id. |
| `temporalio` dependency | **Optional extra `[run]`**, imported lazily | It is currently a *dev-only* dep. The API must import cleanly without it — which is also what §5.4 requires: absent Temporal is a disabled control, not an error. |

## Shape

```
interfaces/executor.py     WorkflowExecutor ABC + RunHandle / RunStatus / RunEvent
                           + ExecutorUnavailableError. No vendor SDK.
execution/bundles.py       locate the on-disk bundle; read inputs + signals from
                           the stored TemporalWorkflowDesign (deterministic).
execution/workers.py       subprocess supervisor: one `python worker.py` per slug,
                           started lazily, reused across runs, reaped when idle.
execution/temporal.py      TemporalExecutor — the only module importing temporalio.
execution/runs.py          RunManager — in-memory run registry.
execution/fake.py          FakeExecutor for tests (no server, no subprocess).
```

## API

```
GET    /projects/{id}/runnable                 per-slug: inputs, signals, bundle present?
POST   /projects/{id}/runs      {slug, input}  → {run_id, workflow_id}
GET    /projects/{id}/runs                     list, newest first
GET    /runs/{run_id}                          status + step trail
POST   /runs/{run_id}/signal    {name, args}
DELETE /runs/{run_id}                          terminate
```

`GET /health` gains a `temporal` block: `{reachable, address, detail}`.

## Invariants to keep

- No `temporalio` import in `compiler`, `agents`, `project_compiler`, or `codegen`.
- Signals are sent by their **spec** name (§6.2), never the snake_cased method.
- A compensated run must be visually distinct from a completed one (§8).
- One `--input` per signal parameter (§2.1) — the executor passes an arg *list*.
