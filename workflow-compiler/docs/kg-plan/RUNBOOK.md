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

## Phase 1 — Change request + guided wizard (2026-08-18)

### Automated gates

| Gate | Result |
|---|---|
| `pytest -q -p no:warnings` | **646 passed** (620 from Phase 0 + 26 new: 17 wizard/round-trip/ids/store/splice, 4 API flow, 1 CLI, 4 fixture checks) |
| `ruff check src tests` | clean |
| `mypy src` (strict) | clean, 166 files |
| `npm run build` | clean; routes `/changes`, `/changes/[id]` |

### Bring-up used for the live run

Same as the top of this file (backend `127.0.0.1:8010` **without** `--reload`, frontend
`127.0.0.1:3010` with `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8010`), demo account
`kgdemo@example.com`. The backend was restarted twice mid-run to pick up engine fixes found
during the run (see "Gotchas") — restarting between jobs is safe; the change request is saved
after every call.

### Live run — BCR-001 through the wizard in the browser (Nemotron `nvidia/llama-3.3-nemotron-super-49b-v1`)

Steps (Chrome, driven via Chrome DevTools; all times UTC as recorded on the change request's
chat turns — local time is UTC−5):

1. `/changes` → New change request: KB **Order lifecycle (Existing_KG)** (`86d9919378bd4ebe8329f8ff950a2a27`),
   upload `examples/change_requests/BCR-001-partial-shipment-support.docx`, provider Nemotron →
   *Create* → redirected to `/changes/dfad0d257db847919029f11dbef3c47d`. The header already shows
   the parsed metadata (BCR-001, VP Supply Chain Operations, target OrderWorkflow) — no LLM call.
2. **Start wizard** → ids reserved instantly (`EPIC-002`, `TDD-ORD-002`, next TC `TC-18`; 86 impact
   rows) and the impact questions job runs.
3. Impact step: 3 questions → answered (chip + prose) → **Draft now** → v1 (30 affected rows) →
   **Revise** ("add EPIC-001 DoD + TP §3.2 rows") → **Approve**.
4. EPIC step: 3 questions (2 answered, 1 skipped as out of scope) → Draft → hand **Edit** in the
   markdown editor (Target Release) → v2 `human_edit` → Approve.
5. Stories step: 5 questions (3 answered, 2 skipped) → Draft (8 stories, 3 batches) → Approve.
6. TDD step: 5 questions (4 answered, 1 skipped) → Draft (4 chunks) → Revise (§5 list-valued
   results + `ShipmentGroup`) → Approve → CR **complete**.

| Item | Measured |
|---|---|
| CR create (docx parse, meta/requirements/seeds) | < 1 s; 6 requirements `BCR-01-01..06`, 20 seed terms |
| Start (catalog → ids, impact BFS, glossary) | ~1 s; catalog `documents = [BRD-ORD-001, TDD-ORD-001, TP-ORD-001]` → `TDD-ORD-002` |
| Impact questions (`cr_questions`) | 15:50:50 → 15:53:22 = **2.5 min** (brief ≈ 36 k chars incl. 32 KG excerpts) |
| Impact answers (sync `answer`, per call) | 13 s / 13 s / 8 s |
| Impact draft (`cr_draft`: draft + coverage pass + render) | 15:54:41 → 15:58:24 = **3.7 min**; v1 = 30 affected rows, 6 requirement rows, 86-row KG appendix, 15 sources |
| Impact revise (`cr_revise`, whole-document rewrite — the first implementation) | 15:58:53 → 16:01:12 = 2.3 min, **but it condensed the document 17.7 KB → 5.0 KB** (rows dropped) — fixed the same session, see gotchas; the section-scoped re-run took **65 s** and kept all rows (v6 = 18.2 KB) |
| EPIC questions | 16:02:07 → 16:13:20 = 11 min wall-clock **including a Nemotron HTTP 504 + retries and a backend restart**; the call itself ≈ 2 min |
| EPIC draft | 16:16:27 → 16:18:09 = **1.7 min**; story map `US-008..US-015` |
| Human edit (PUT) | instant; v2 `human_edit` |
| Stories questions | 16:24:06 → 16:24:56 = 50 s |
| Stories draft (8 stories, batches of 3) | 16:26:37 → 16:28:42 = **2.1 min**; 23 Given… acceptance criteria |
| TDD questions | 16:29:59 → 16:31:10 = 71 s |
| TDD draft (4 chunked calls) | 16:32:29 → 16:35:46 = **3.3 min**; 14/14 sections, each Existing + Proposed |
| TDD revise | 16:36:16 → 16:39:11 = 2.9 min |
| End to end (create → complete) | 15:50:50 → 16:40:35 = 50 min including think time, one 504 stall and two restarts; pure LLM time ≈ 20 min |
| Screenshots | `docs/kg-plan/screenshots/phase1-*.png` (questions drafting, impact drafting/drafted, epic drafted, stories drafting/drafted, tdd drafting, tdd approved, cr complete) |
| Fixtures | `tests/fixtures/change_artifacts/{BCR-001-impact-analysis, EPIC-002, US-008-015-stories, TDD-ORD-002}.md` (+ `tests/test_change_fixtures.py` asserting the checks below and the round trips) |

Plan checks, as observed in the artifacts:

- **Impact** names `existing_Codebase/workflows/order_workflow.py`, the `types.py` classes
  (`OrderState`, `ProvisioningResult`, `DispatchResult`, `CompletionResult`), `provision_order`,
  `dispatch_order`, `compensate_*`, `complete_order`, TC-01/06/09/10/12/16, US-003/004/005, the
  test plan (TP-ORD-001 §3.2 after the revision), EPIC-001 (DoD/story map row after the revision),
  EPIC-002 (add), both diagrams and the new companion diagram; requirement rows for all six
  BCR-01-0N; a deterministic 86-row KG appendix and a 15-file Sources footer.
- **EPIC-002** has Epic Statement / Business Value / In-Scope Capabilities / Definition of Done /
  Story Map (`US-008..US-015`, ids assigned by the engine) / NFRs / Dependencies / Risks.
- **Stories** are one `## US-00N: Title` section each with As/I want/so that, `- [ ] Given …`
  criteria and Notes citing BCR ids, TDD-ORD-002 sections and TC ids.
- **TDD-ORD-002** keeps TDD-ORD-001's sections with Existing vs Proposed each: `PARTIALLY_PROVISIONED`
  / `PARTIALLY_DISPATCHED` + a per-group sub-state machine, per-group activities table, group saga
  pseudo-code, `cancel_shipment_group(group_id)`, `get_status` per group, timeouts, testing (TC-06/09/10
  updated + new scenarios), `list[ProvisioningResult]` / `list[DispatchResult]` + `ShipmentGroup` in §5
  (after the revision), diagram `order-state-machine-partial-shipment.mmd`.

CLI parity: the same flow was first run unattended (`cr create … --provider nemotron`, then
`cr draft <id> impact|epic|stories|tdd --auto`, `cr approve`) — impact 1 m 49 s (v1, before the
coverage pass), epic ~80 s, stories 3 min, TDD 9 min with the first prompt (~3 min after chunking
tuning). `--auto` answers every question with its first suggested option.

### Gotchas found in this phase

- **Whole-document LLM revisions are lossy.** Asked to "add two rows", Nemotron returned a
  *condensed* document (17.7 KB → 5.0 KB, most table rows and the appendix dropped). Revision is now
  section-scoped: the model returns only the `## ` sections it changed, the engine splices them by
  heading and never touches the KG appendix / Sources; and because the model still abbreviates long
  tables with `| … |` rows, a table-merge guard keeps every original row and appends only new ones
  (deleting a row is a hand edit). The v2 impact produced by the old path was superseded by
  restoring v1 (a `human_edit`) and re-running the revision.
- **Nemotron under-reports affected items on one pass.** The first impact draft listed 6 rows. Two
  changes fixed it: targeted retrieval queries + a **business-id glossary** in the brief (one corpus
  line per reached `TC-`/`US-`/`BR-` id, e.g. `TC-05 | Provisioning fails after validation …`), and a
  bounded **second coverage pass** that classifies the traversal candidates the first draft did not
  mention (modify / verify / add / unaffected). Result: 30 rows with KG node ids.
- **Decisions must be cumulative.** The EPIC and Stories steps re-asked the invoicing and
  backward-compatibility questions until the brief listed the decisions of *all* previous steps
  (they still get re-asked occasionally — Nemotron does not always honour "do not ask again"; answer
  consistently or skip).
- **Nemotron 504s.** One `HTTP 504` during the EPIC questions; the provider's retry handled it but the
  job took 11 min wall-clock. Nothing to do but wait — the UI keeps polling.
- **`PUT …/artifacts/{kind}` with `note: null`** was rejected (422) by the first schema; the note is now
  optional on both sides. Approved artifacts cannot be edited from the UI (by design in this version —
  the API allows it and flips them back to `drafted`).
- **Programmatic browser driving:** the answer textarea is a controlled React input — `fill` did not
  register; dispatch a native `input` event (see the DevTools transcript). CodeMirror is reachable via
  `document.querySelector('.cm-content').cmTile.view` for a scripted edit.
- **Timestamps** on steps/artifacts used the wizard's stale `updated_at` until fixed mid-run — the EPIC
  approve time in the recorded CR equals its draft time for that reason.
- **Bash-tool heredocs** in the Claude Code harness on this machine unescape `\n`/`\b`/backticks even
  with a quoted delimiter — patch scripts with regexes or multi-line strings must be written to a
  file with the Write tool and executed, not pasted into a heredoc.
