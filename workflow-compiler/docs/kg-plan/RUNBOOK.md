# KG change pipeline — runbook

Live-run recipe and recorded results, one section per phase. Everything here was executed
against the real `Existing_KG` corpus; numbers are measured, not estimated.

## Bring-up (this worktree)

```powershell
cd "C:\Users\devag\Documents\Code (local)\order-workflows-kg\workflow-compiler"
# one-time: py -3.12 -m venv .venv; .venv\Scripts\pip install -e ".[dev]"; copy ..\..\order-workflows-demo\workflow-compiler\.env .env; cd frontend; npm install
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python -m uvicorn workflow_compiler.api.app:app --host 127.0.0.1 --port 8010
# second terminal
cd frontend; $env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:8010"; npx next dev --hostname 127.0.0.1 --port 3010
```

Why 8010/3010 and `127.0.0.1`: on 2026-08-17 the `order-workflows-demo` worktree's servers held
8000/3000; a different host string also keeps the two apps' session cookies apart. If the default
ports are free, `python -m uvicorn workflow_compiler.api.app:app --reload` + `npm run dev` work as
before (but do not use `--reload` while a long ingest job is running — a reload drops in-flight
jobs). Demo account: `kgdemo@example.com` / `kgdemo-pass-2026` (local account on this machine).

Demo zip: `python scripts/make_kb_zip.py` → `examples/knowledge_bases/order-lifecycle.zip`
(the corpus folder is a verbatim copy of the manager's `Existing_KG`).

## Phase 0 — Knowledge base foundation (2026-08-17)

### Automated gates

| Gate | Result |
|---|---|
| `pytest -q -p no:warnings` | 620 passed (29 kg unit, 6 KB API, 2 CLI kb, rest untouched) |
| `ruff check src tests` | clean (vendored `kg/contexthub/**` runs with style rules relaxed) |
| `mypy src` (strict) | clean, 155 files (35 pre-existing errors fixed; vendored subpackage `ignore_errors`) |
| `npm run build` | clean; routes `/knowledge`, `/knowledge/[id]` |

### Live run — upload through the UI with enrichment on Nemotron

Steps (browser, driven via Chrome DevTools):

1. `/login` → Create account → `/knowledge`.
2. Drop `examples/knowledge_bases/order-lifecycle.zip`, name "Order lifecycle (Existing_KG)",
   provider **Nemotron (cloud)**, LLM enrichment **on** → *Upload and index*.
3. Redirected to `/knowledge/<kb_id>`; header pill "indexing…", banner shows the job progress
   (`doc:README.md (1/22)` → … → `process clustering`); *Reindex* buttons disabled meanwhile.
4. On completion the pill turns "ready", the Graph card fills, the runs poller toasts
   "Knowledge base indexed and ready."
5. *Ask the graph* with "how does dispatch compensate provisioning" (budget 2000).
6. *Impact* from `complete_order` (2 hops).

Recorded results: see the table below (filled from the run).

RESULTS_PLACEHOLDER

### Gotchas found in this phase

- **Ports** — see bring-up. `netstat -ano | findstr :8000` before assuming a free port.
- **Enrichment cost** — one Nemotron call per Document/Module node (22 for this corpus, ~30 s each
  with the 49B model) + one clustering call; static ingest alone is ~1 s. Results are cached by
  content hash under `.contexthub/llm_cache/`, so *Reindex + enrich* is free after the first run.
- **`.pdf`** is now indexed (routed through `workflow_compiler.ingestion`); the manager's corpus has
  none, so this path is exercised only by unit tests.
- **Requirement ids** — the reference BRD numbers requirements `BR-01..10` and the change request is
  `BCR-001`; upstream Context Hub only knew `REQ-`, so `BR`/`BCR` were added to the id families
  (VENDORED.md edit 10). Without it the catalog's `requirements` list is empty.
- **Windows path separators** — upstream put `\` inside node ids on Windows; the vendored ingest
  normalises ids and path metadata to POSIX at the end of `ingest()` (VENDORED.md edit 7). The
  test suite asserts no backslash survives.
- **Shared `JobManager` across API tests** — the FastAPI `app` (and its job registry) is module-level,
  so `GET /jobs` in one test can see jobs from another; assert on scope filtering, not emptiness.
- **Bash-tool heredocs containing backticks** fail to parse in the Claude Code harness on this
  machine; write patch scripts to a file and run them.
