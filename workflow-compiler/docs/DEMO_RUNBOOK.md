# Demo runbook — combined spec-dialogue + run stack

Branch `demo/dialogue-plus-run` (= `feat/run-workflows` + `feat/spec-dialogue`, merged
2026-08-13, zero conflicts; full pytest suite, `tsc`, and `next build` verified, plus a
live browser run of the Run panel).

The stack runs on **isolated ports** so the plain spec-dialogue stack (8000/3000 in the
`order-workflows-dialogue` worktree) can stay up side by side.

## Bring-up (three terminals, in this order)

All commands from `order-workflows-demo/workflow-compiler/`.

```bash
# 1. Temporal dev server (isolated: server 7243, web UI 8243)
temporal server start-dev --port 7243 --ui-port 8243 --db-filename .temporal-demo.db

# 2. Backend on 8010, pointed at that Temporal
set WORKFLOW_COMPILER_TEMPORAL_ADDRESS=localhost:7243     # PowerShell: $env:WORKFLOW_COMPILER_TEMPORAL_ADDRESS="localhost:7243"
.venv\Scripts\python -m uvicorn workflow_compiler.api.app:app --port 8010

# 3. Frontend on 3001 (CORS-allowed by default), pointed at 8010
cd frontend
set NEXT_PUBLIC_API_BASE=http://localhost:8010            # PowerShell: $env:NEXT_PUBLIC_API_BASE="http://localhost:8010"
npx next dev -p 3001
```

Ready when `GET http://127.0.0.1:8010/health` shows `"temporal": {"reachable": true}`.

## Demo flow that is verified to work

1. Sign in at `http://localhost:3001/login` (`acceptance@demo.local` / `acceptance123`).
2. Open **Order Management Operations** (`6090ee25-ef28-408d-a1aa-c4e49ee812cc`) —
   stage Completed, three workflows, all cross-references confirmed.
3. Spec / Resolve tabs: the dialogue feature (suggested answers included).
4. **Results tab → RUN card**: pick a workflow chip, the input form is pre-filled with
   sample values, click **Run workflow**.
   - `order-placement`: completes in ~2 s; step trail shows ValidateCart →
     ReserveInventory → AuthorizePayment → CreateOrder plus the two cross-workflow
     trigger activities.
   - `order-fulfilment`: parks on the carrier-pickup wait — deliver the
     `carrier_picked_up` signal from the panel to finish it. Best moment of the demo.
   - `order-return`: AuthoriseReturn → ReceiveReturnedItem → IssueRefund.
5. Optional: the Temporal web UI at `http://localhost:8243` shows the same executions.

## Gotchas (each cost real time — do not rediscover)

- **Do not copy old bundles into `generated/<project>/<slug>/`.** Runs execute files on
  disk and never overwrite them; a bundle rendered before `TEMPORAL_ADDRESS` support is
  refused up front. Delete the directory and let the run materialize a fresh bundle.
- The demo keeps its own `.env`, `.workflow_state/`, and venv — copied from the dialogue
  worktree on 2026-08-13. Projects created later in one worktree do NOT appear in the
  other.
- Keep the demo on the happy path: a worker that dies *after* startup leaves a run stuck
  in `running` with no explanation (known gap), and the compensation path is implemented
  but was never verified live.
- Two pytest tests (`test_jobs_list_reports_the_run`,
  `test_confirm_with_stale_fingerprint_raises`) fail in a checkout without `.env`: they
  assume predraft is off, which only holds for `local*` providers. Not a code defect.
