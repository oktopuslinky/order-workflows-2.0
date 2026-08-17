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
5. *Ask the graph* with "how does dispatch compensate provisioning" (budget 4000, the default).
6. *Impact* from `complete_order` (2 hops).

Recorded results: see the table below (filled from the run).

| Item | Measured |
|---|---|
| kb_id | `86d9919378bd4ebe8329f8ff950a2a27` (name "Order lifecycle (Existing_KG)", `.workflow_state/knowledge_bases/`) |
| Upload → job start | immediate (zip 108 KB, 27 files, top-level folder `order-lifecycle` stripped) |
| Static ingest (CLI, `kb init --no-enrich`) | **~5 s** incl. Python startup; 170 nodes / 392 edges |
| First enrich run (Nemotron `nvidia/llama-3.3-nemotron-super-49b-v1`, 22 file nodes + clustering) | 13:52 → 14:19 = **27 min** (~35 s per file at `max_tokens=1024`, some 60–70 s); result 382 nodes / 927 edges, `Enrichment: 4 file(s) skipped after repeated LLM failures` (BRD + EPIC docx: model answers truncated/malformed JSON; both clustering batches) |
| Reindex + enrich after the bridge fix (`max_tokens=2048`, warning-level logging) | 14:22 → 14:28 = **5.5 min**; 20/22 files served from `llm_cache`, BRD ok first try, EPIC ok on attempt 3/3 (parse errors on attempts 1–2), clustering ok → **401 nodes / 979 edges**, no warnings |
| Node counts (final) | Document 16, Module 6, Class 10, Function 27, Chunk 60, Epic 3, UserStory 13, TestCase 18, Requirement 14, Service 3 (`svc:.` + 2 `svc:proc:*` clusters), DataArtifact 229 (topics + entities), Config 1, Repository 1 |
| Edges (final) | CONTAINS 420, RELATES_TO 472, NEXT 39, DOCUMENTED_BY 38, IMPORTS 9, READS_CONFIG 1 |
| Catalog | epics `EPIC-001`, `EPIC-001-A`; stories `US-001..007`; test cases `TC-01..17`; requirements `BCR-001`, `BR-01..12` |
| Ask: "how does dispatch compensate provisioning", budget 4000 | coverage **100 %**, 3011 tokens, 8 sections; sources `existing_Codebase/workflows/order_workflow.py` **lines 1-112, 57-243**, `system-flow-diagram.md` 5-43, `order-state-machine.mmd` 1-32. (At budget 2000 the two diagrams win and `order_workflow.py` is only summarised — hence the UI default of 4000 = `kg_retrieve_budget`.) |
| Impact from `complete_order`, 2 hops | 50 rows; seeds `US-005-complete-order.docx` chunk/doc + `order_activities.py` chunk 009; hop 1 reaches `BR-06`, `EPIC-001`, `TC-01`, `TC-11`, `TC-14`, `US-005`, entities `audit-log`, `continue-as-new`, … |
| Screenshots | `docs/kg-plan/screenshots/phase0-kb-indexing.png`, `phase0-kb-ready-ask.png` |

Everything the plan's live-verification asked for was observed: Document ≈ 15 (16 incl. README),
Module 6 (the plan guessed ≈ 8; the corpus has 6 `.py` modules outside `__init__`), Function/Class,
Chunk, `US-001..007`, `TC-01..17`, `EPIC-001`, `BR-xx`, and a packet that dereferences
`order_workflow.py` line spans.

### Gotchas found in this phase

- **Ports** — see bring-up. `netstat -ano | findstr :8000` before assuming a free port.
- **Enrichment cost** — one Nemotron call per Document/Module node (22 for this corpus, ~35 s each
  with the 49B model) + clustering (2 batches of 12); static ingest alone is ~1 s. Results are
  cached by content hash under `.contexthub/llm_cache/`, so *Reindex + enrich* only re-asks for
  files that failed (5.5 min for 2 files + clustering here).
- **Nemotron JSON hygiene** — the model prefaces JSON with prose and occasionally emits malformed
  objects (unescaped quotes → `Expecting ',' delimiter`), and at `max_tokens=1024` the BRD/EPIC
  answers and the clustering answer were truncated. `ProviderJsonClient` now uses 2048 tokens,
  retries 3× and logs each failure at WARNING (`kg enrichment call '<node>' attempt i/3 failed: …`);
  a file that fails all attempts is skipped and counted in `kb.warnings`, never fatal.
- **`.pdf`** is now indexed (routed through `workflow_compiler.ingestion`); the manager's corpus has
  none, so this path is exercised only by unit tests.
- **Requirement ids** — the reference BRD numbers requirements `BR-01..12` and the change request is
  `BCR-001`; upstream Context Hub only knew `REQ-`, so `BR`/`BCR` were added to the id families
  (VENDORED.md edit 10). Without it the catalog's `requirements` list is empty.
- **Windows path separators** — upstream put `\` inside node ids on Windows; the vendored ingest
  normalises ids and path metadata to POSIX at the end of `ingest()` (VENDORED.md edit 7). The
  test suite asserts no backslash survives.
- **Shared `JobManager` across API tests** — the FastAPI `app` (and its job registry) is module-level,
  so `GET /jobs` in one test can see jobs from another; assert on scope filtering, not emptiness.
- **Bash-tool heredocs containing backticks** fail to parse in the Claude Code harness on this
  machine; write patch scripts to a file and run them.
