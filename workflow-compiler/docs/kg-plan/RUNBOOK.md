# KG change pipeline — runbook

The **end-to-end demo script** (bring-up → exact clicks → ids → expected timings → gotchas → reset
recipe) comes first; then one section per phase with the live-run recipe and the recorded results.
Everything here was executed against the real `Existing_KG` corpus; numbers are measured, not
estimated.

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
before — but never bare `--reload` with knowledge bases: the reloader watches every `*.py` under the
cwd, and the corpus zip's own `.py` files extracted under `.workflow_state/` trigger a restart a
second into indexing, dropping the in-flight job (reproduced 2026-08-25 on a fresh install; the
routes now report such a record as failed/"interrupted" instead of "ingesting" forever). Use
`--reload --reload-dir src` if you need reload. Demo account: `kgdemo@example.com` / `kgdemo-pass-2026` (local account on this machine).

Demo zip: `python scripts/make_kb_zip.py` → `examples/knowledge_bases/order-lifecycle.zip`
(the corpus folder is a verbatim copy of the manager's `Existing_KG`).

## Demo script — the whole business-change pipeline in one sitting (Phase 5, 2026-08-19)

This is the script the Phase 5 demo pass followed end to end (measured timings are in the
Phase 5 section below; the ids named here are the pass's own, kept on this machine). Everything
happens in the browser except where a curl/API call is noted; every model call goes to cloud
Nemotron (`nvidia/llama-3.3-nemotron-super-49b-v1`, the KB/CR default). Budget **≈ 75–90 min**
wall-clock, of which ≈ 55 min is model time; the long stretches are marked so the presenter can
talk over them (or pre-run steps 1–2 and open the ready KB / CR instead).

### 0. Bring-up (5 min, once)

1. Servers as at the top of this file: backend `127.0.0.1:8010` (no `--reload`), frontend
   `127.0.0.1:3010` with `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8010`. On Windows start them
   detached (`Start-Process`) — a shell that exits takes its children with it.
2. Open `http://127.0.0.1:3010/login`, sign in as `kgdemo@example.com` / `kgdemo-pass-2026`
   (or *Create account*).
3. Optional reset — see *Reset the demo state* below (nothing in this script needs it; a second
   KB/CR/project with the same name is fine).

### 1. Knowledge base (≈ 23 min cold, ≈ 6 min when the KB directory already has an `llm_cache/`)

1. **Knowledge** (nav) → drop `examples/knowledge_bases/order-lifecycle.zip` (or click the file
   input), name *Order lifecycle (Existing_KG) — Phase 5 demo*, provider **Nemotron (cloud)**,
   *LLM enrichment* **on** → **Upload and index** (`phase5-kb-upload-form.png`).
2. Redirected to `/knowledge/<kb_id>`; the header pill says *indexing…*, the banner walks the
   22 file nodes (`doc:README.md (1/22)` … `mod:existing_Codebase/starter.py` … `process
   clustering`) — **≈ 35 s per file + 2 clustering batches**; talk over it, or open a ready KB
   (`phase5-kb-indexing.png`).
3. Pill *ready* → Graph card ≈ 390–400 nodes / ≈ 960 edges, catalog `EPIC-001`, `US-001..007`,
   `TC-01..17`, `BR-01..12`, documents `BRD-ORD-001` / `TDD-ORD-001` / `TP-ORD-001`
   (`phase5-kb-ready.png`). If the warnings say *N file(s) skipped after repeated LLM failures*,
   **Reindex + enrich** re-asks only those (≈ 30 s each; the rest come from `llm_cache/`).
4. **Ask the graph** → *how does dispatch compensate provisioning*, budget 4000 → coverage 100 %,
   sources `existing_Codebase/workflows/order_workflow.py` lines …, the state-machine diagram
   (`phase5-kb-ask.png`). Optional: **Impact** from `complete_order`, 2 hops.

### 2. Change request + wizard (≈ 20 min of model time; 4 steps)

1. **Changes** (nav) → *New change request*: KB = the one above, upload
   `examples/change_requests/BCR-001-partial-shipment-support.docx`, provider Nemotron →
   **Create change request** (`phase5-cr-new-form.png`). The page opens with the parsed
   metadata (BCR-001 · VP Supply Chain Operations · target OrderWorkflow) and 6 requirements —
   no model call (`phase5-cr-created.png`).
2. **Start wizard** → ids reserved instantly (`EPIC-002`, `TDD-ORD-002`, next TC `TC-18`, 86-row
   impact traversal) and the *impact questions* job runs (**≈ 40 s**, `phase5-wizard-started.png`).
3. **Impact**: 2–3 questions → click a suggested chip (it fills the box) → **Answer** (3–15 s
   each; or **Skip**) → **Draft now** (**≈ 3.5 min**: draft + coverage pass;
   `phase5-impact-drafting.png` → `phase5-impact-drafted.png`: ≈ 25–30 affected rows, KG
   appendix, Sources) → optional **Revise** (*add EPIC-001 DoD + TP §3.2 rows*, ≈ 1 min) or
   **Edit** → **Approve** (`phase5-impact-approved.png`). Approve auto-starts the next step's
   questions (**≈ 1 min**).
4. **EPIC**: 3 questions → chips → **Draft now** (**≈ 1.5 min**; Epic Statement / Business
   Value / In-Scope Capabilities / DoD / Story Map `US-008…` / NFRs / Dependencies / Risks) →
   **Approve** (`phase5-epic-*.png`).
5. **Stories**: 3 questions → **Draft now** (**≈ 2.5 min**, batches of 3; one `## US-00N` section
   each with Given/When ACs) → **Approve** (`phase5-stories-*.png`).
6. **TDD**: 5 questions → **Draft now** (**≈ 2.5 min**, 4 chunked calls; 8 numbered sections,
   each *Existing* / *Proposed*, `PARTIALLY_*` states, `list[ProvisioningResult]`, `get_status`
   per group, the companion diagram named) → **Approve** → header pill **complete**
   (`phase5-tdd-*.png`, `phase5-wizard-complete.png`).
7. **Export**: on the TDD panel **.docx** (`TDD-ORD-002-…docx`, < 1 s), header **Export all
   (.zip)** (`BCR-001-<cr>-export.zip`: 4 + N docx, xlsx preview, markdown, MANIFEST) — open the
   TDD next to `TDD-ORD-001` in Word for the look (`phase5-cr-export.png`).

### 3. Send to workflow GUI → the spec gate (≈ 5.5 min compile + 2.5 min validate)

1. **Send to workflow GUI** (visible once the TDD is approved; `phase5-cr-send-button.png`) →
   overlay *Compiling the TDD into a grounded workflow project* (`phase5-cr-sending.png`) —
   **≈ 4–5.5 min** (segmentation → grounded facts → change spec) → redirected to
   `/projects/<id>` (`phase5-project-after-send.png`); the CR page now lists the project.
2. Spec tab: the workflow spec + **`changes.md`** (≈ 35–40 components with KG node ids,
   requirement ids, Sources; `phase5-project-changes-md.png`); header *Grounded by … · from
   BCR-001*.
3. Hand edits that Nemotron variance may need (Phase 3/4/5 all differed): if `- triggers:` is
   empty give it a value; drop the descriptive *State Transitions* bullets (R9); if the spec has
   no `## Inputs` / `## Outputs`, add them. **Save** (compare-and-swap: the editor sends the
   project version; a *409 … changed since it was loaded* means another tab or a job saved
   first → *Reload the latest version*).
4. **Validate** (**≈ 2–2.5 min**, `phase5-project-validating.png` → `phase5-project-validated.png`):
   expect completeness WARNs on the new states, a `changes.md` WARN for a diagram path the KB does
   not have (the model named the *new* file) — none blocking in this pass.
5. Optional **Resolve** tab (guided Q&A over both files; wait for *Questions ready* before
   *Start resolving*).

### 4. Approve → change outputs (≈ 3–4 min approve + ≈ 25–30 min outputs)

1. **Approve** (tick *accept incomplete* only if a BLOCK remains) → **≈ 3–4 min** → stage
   **COMPLETED**, graph health, Temporal design + code (`phase5-project-approving.png` →
   `phase5-project-approved.png`).
2. The approve job's `after` hook starts the **change_outputs** job on cloud Nemotron: Results →
   **Workflows | Change outputs** shows *diagrams… → code… → tests_doc…* with per-file persistence
   (`phase5-outputs-running.png`); **≈ 3 min diagrams + ≈ 20 min code (6 files, up to 2 repair
   rounds each, keep-style, bundle smoke) + ≈ 2 min test docs**.
3. When done: **Diagrams** (Updated / Original toggle, the companion
   `order-state-machine-partial-shipment.mmd`; `phase5-outputs-diagrams-*.png`), **Code** (status
   / ast / ruff / `repaired ×N` / `style kept` pills, the *Bundle smoke test* card, unified /
   side-by-side; `phase5-outputs-code-*.png`), **Test cases** (TC-18…, updated TC-06/09/10/12,
   addendum; `phase5-outputs-tests*.png`), **Download all (.zip)** →
   `BCR-001-<project>-change-outputs.zip` (README layout; `phase5-final-outputs-*.png` show the final state with the smoke test **passed 11/11**).
4. Honesty slide: the smoke card and the RUNBOOK's *Running the generated tests* — the corpus's own
   tests fail 4/4 in a fresh env (str-Enum decode), so a green run is not the bar; the deliverable
   is a checked, reviewable diff.

### Reset the demo state (document-only recipe; nothing was deleted this session)

```powershell
cd "…\order-workflows-kg\workflow-compiler"
.\.venv\Scripts\python scripts\reset_demo_state.py                 # dry run — lists every KB / CR / project (+ workflow states)
.\.venv\Scripts\python scripts\reset_demo_state.py --only projects  # dry run, projects only
.\.venv\Scripts\python scripts\reset_demo_state.py --yes --keep 86d9919378bd4ebe8329f8ff950a2a27 --keep dfad0d257db847919029f11dbef3c47d
#   deletes everything except the reference KB + CR, after writing .workflow_state\backup-<stamp>.zip
```

Stop the backend first (a running job would keep writing), keep `users/` (the script never
touches accounts), and `generated/<project-id>/` only goes with `--generated`. To start truly
empty, delete `.workflow_state\` after stopping both servers and register the demo account
again.

### Gotchas that bite a live demo (collected over phases 0–5)

- **Ports / servers**: 8000/3000 may belong to another worktree; `netstat -ano | findstr :8010`.
  Never `--reload` with a job running; on Windows start servers with `Start-Process` (a closing
  shell kills its children).
- **Nemotron pace + hygiene**: ≈ 35 s per enrichment file, 504s happen (the client retries; the
  UI keeps polling); JSON answers occasionally carry stray strings — every plan tolerates them.
- **Wizard re-asks**: the model sometimes re-asks a recorded decision — answer consistently or
  Skip. Whole-document revisions are section-spliced; deleting a table row is a hand edit.
- **Spec variance at the gate**: the trigger line, State-Transitions bullets, missing
  Inputs/Outputs, a thin spec — the gate catches them; one hand edit each.
- **Chrome + downloads**: the automation profile blocks rapid multi-downloads; click one at a
  time (Playwright's context is fine).
- **Two tabs on one project**: saves are compare-and-swap now — the second tab gets a 409 and a
  *Reload the latest version* link instead of overwriting.
- **Generated tests**: the bundle imports (smoke) but a long test module can still hold a syntax
  slip after two repair rounds; the verdict is on the card, the file is kept with the error.


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
| Fresh install (`pip install .`, `init --provider nemotron`), UI upload with enrichment, no `--reload` — 2026-08-25 | 12:18 → 13:22 = **64 min**; files 1–8 ≈ 13 s each, then `tests/test_order_workflow.py` held for **28 min** by a stalled cloud request (one 400 s ReadTimeout, retry succeeded), median 60 s/file afterwards, clustering 10 min; 393 nodes / 957 edges; EPIC docx + both `process_cluster_2*` skipped on JSON parse errors. Same upload **with** `--reload`: WatchFiles restarted the server 0.2 s after the corpus `.py` files were extracted, the job vanished and the KB stayed `ingesting` forever — fixed (routes report it as interrupted; bridge bounds each call by `llm_timeout` and no longer pins the old process at exit) |
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

## Phase 2 — Document export, .docx / .xlsx in the manager's template style (2026-08-18)

### Automated gates

| Gate | Result |
|---|---|
| `pytest -q -p no:warnings` | **664 passed** (646 from Phase 1 + 18 new: 15 `test_docs_export.py` golden-structure/xlsx/bundle, 2 API export routes, 1 fixture identity; the CLI round-trip test grew the docx/xlsx/zip steps) |
| `ruff check src tests` | clean |
| `mypy src` (strict) | clean, 173 files |
| `npm run build` | clean (routes unchanged; `npm run lint` reports the same 2 pre-existing `RunPanel`/`SpecChatPanel` findings as before this phase) |

### What was measured on the reference documents (and reproduced)

Inspected with python-docx/lxml/openpyxl before writing the writer (numbers are the reference's,
not the digest's guesses): Letter page, 0.75 in margins; **no font defaults** in the styles → Word
renders Times New Roman 10 pt; title run bold `2F5496` sz 44 (22 pt) with 10 pt after; subtitle
`444444` sz 28 (14 pt) with 15 pt after; a bottom-bordered empty paragraph (`AAAAAA`, sz 6) before
and after the metadata block; meta lines `Label: ` bold + value, 3 pt after; Heading 1 `2E74B5`
16 pt (before 16 / after 8 pt), Heading 2 13 pt (before 13 / after 6), Heading 3 `1F4D78` 12 pt;
tables `tblW` 9500 dxa, single `auto` borders, header row `tblHeader` + `shd 2F5496` + white bold
runs, body cells `shd FFFFFF`, cell margins 80/100 dxa, an empty paragraph after each table;
bullets = `ListParagraph` + `numPr` (`•`, ind 460/260; the EPIC also uses real decimal numbering
for capabilities); checklists = plain paragraphs, `ind left 360`, run `☑  `/`☐  `; inline code =
Consolas runs coloured `AA3377`; code blocks = one paragraph with `CCCCCC` borders, `F5F5F5`
shading, Consolas 9.5 pt, `w:br` line breaks; the EPIC statement = paragraph with a `2F5496`
sz 18 left border and 400 dxa indent. Xlsx: header Arial 10 bold white on `2F5496`, wrapped,
30 pt row, frozen at A2, autofilter; body Arial 10 on `F2F2F2`, thin borders, top-aligned;
column widths 8/30/32/30/48/20/15/16/30; Summary A1 Arial 14 bold `2F5496`, widths 32/28.

Deliberate deviations: totals in the Summary sheet are **literal numbers** (the reference uses
`COUNTIF` formulas, which openpyxl cannot evaluate and non-Excel readers see as blank); the
`Existing` / `Proposed` split of TDD sections is rendered as Heading 3 (the reference TDD has no
such split); every export adds an `Export: Approved vN (date)` / `DRAFT vN — not approved` line.

### Live run — export BCR-001's artifacts from the UI (CR `dfad0d257db847919029f11dbef3c47d`)

Bring-up as at the top of this file (backend restarted from this worktree on 127.0.0.1:8010, frontend
on :3010). Steps (Chrome via DevTools):

1. `/changes/dfad0d257db847919029f11dbef3c47d` (all four artifacts approved) — the artifact panel shows
   **Export: .docx .md** (impact also **.xlsx**), the header **Export all (.zip)**
   (`docs/kg-plan/screenshots/phase2-export-buttons.png`).
2. TDD → `.docx`: `GET …/artifacts/tdd/export?format=docx` → 200 in < 1 s, the browser saved
   `TDD-ORD-002-orderworkflow-temporal-implementation.docx` (40.7 KB). Impact → `.docx` / `.xlsx`,
   EPIC / Stories → `.docx` (stories = `EPIC-002-user-stories.zip`, 8 files), **Export all** →
   `BCR-001-dfad0d25-export.zip` (421 KB: 4 + 8 docx, 1 xlsx, 4 md, MANIFEST.txt).
3. Opened next to the originals in Word/Excel: `phase2-word-tdd-side-by-side.png` (TDD-ORD-001 vs
   TDD-ORD-002), `phase2-word-epic-side-by-side.png` (EPIC-001 vs EPIC-002), `phase2-word-story-side-by-side.png`
   (US-003 vs US-008), `phase2-excel-tc-side-by-side.png` (TC-order-workflow.xlsx vs TC-preview-BCR-001.xlsx —
   6 affected rows TC-01/06/09/10/12/16 with the original Title/Preconditions/Steps/Expected/Type/Automated
   and the change note appended in Notes).

| Item | Measured |
|---|---|
| Export latency (any artifact, docx) | < 1 s (pure CPU; no LLM) |
| TC preview | 6 rows, all merged from the KB's `Business_Docs/test-cases/TC-order-workflow.xlsx` (17 original rows read via `KgService.read_bytes`) |
| Bundle | 18 files, 420 939 bytes; byte-identical on re-export |
| Fixture | `tests/fixtures/change_artifacts/TDD-ORD-002.docx` = `examples/change_requests/TDD-ORD-002.docx` (40 706 bytes; asserted equal to the deterministic render of `TDD-ORD-002.md`) |

### Gotchas found in this phase

- **The reference look is Word's fallback, not a chosen font.** The manager's docx files (generated
  with the `docx` npm library, creator "Un-named") define no `rPrDefault`, so Word renders Times New
  Roman 10 pt. python-docx's default template pins Calibri 11 via theme fonts — the first export
  looked visibly different in Word until `Normal`/`Heading n` were set to Times New Roman explicitly
  and the theme font attributes removed.
- **OOXML packages are not byte-stable by default.** python-docx and openpyxl stamp zip members with
  the current time and openpyxl overwrites `dcterms:modified` on save; `docs_export/package.py`
  re-zips with fixed timestamps so identical input → identical bytes (the bundle test relies on it).
- **`Content-Disposition` must be CORS-exposed** (`expose_headers=["Content-Disposition"]`), or the
  frontend's fetch cannot read the filename and falls back to `tdd.docx` — the first UI run saved
  fallback names.
- **Chrome's automation profile blocks rapid multi-file downloads** ("multiple downloads" permission);
  the first click saved, later ones were silently dropped. Verified the rest through the API with the
  same session cookie (`scratchpad/fetch_exports.py`), then opened them in Word/Excel.
- **Word/Excel screenshots via COM** need `SetProcessDPIAware()` in the PowerShell process (125 % DPI:
  window geometry is in points ÷ DPI, `CopyFromScreen` otherwise captures the top-left 80 %), and
  `Shell.Application.MinimizeAll()` before activating the Office windows.
- `pytest` collects imported classes named `Test*` — `TestCaseRow`/`TestCaseSummary` carry
  `__test__ = False`.
- Bash-tool heredocs still unescape `\n`, `\"` and backticks — patch scripts and doc edits went
  through the Write tool.

## Phase 3 — KG-grounded workflow project + change spec, "upload the TDD to the GUI" (2026-08-18)

### Automated gates

| Gate | Result |
|---|---|
| `pytest -q -p no:warnings` | **681 passed** (664 from Phase 2 + 17 new: 13 `test_change_spec.py` — prompts with/without `kg_context`, grounder no-op + block/sources/cache, render⇄parse identity incl. provenance, human-edit merge, validator findings, agent cleaning/seeds, change_ops, agenda, grounded compile → validate → approve gate, dialogue over `__changes__`; 4 `test_api_grounded_projects.py` — upload with `kb_id` + `PUT /spec` + validate job, kb/cr error codes, send-to-workflow links ids, CLI `compile --kb`) |
| `ruff check src tests` | clean |
| `mypy src` (strict) | clean, 181 files |
| `npm run build` | clean; `npx tsc --noEmit` clean; `npm run lint` = the same 2 pre-existing `RunPanel`/`SpecChatPanel` findings |

### Bring-up used for the live run

As at the top of this file (backend `127.0.0.1:8010` without `--reload`, frontend `127.0.0.1:3010`,
demo account `kgdemo@example.com`). The Chrome DevTools MCP server did not connect this session, so
the browser was driven with Playwright (`scratchpad/pw/run.mjs`, staged: `login` → `upload` /
`send` → `shots` → `validate` → `resolve` → `approve` → `results`; cookies persisted in
`state.json`; the ms-playwright Chromium already on the machine). The backend was restarted three
times between runs to pick up prompt/agent fixes found during the run (see gotchas) — never while
a job was running.

### Live run 1 — home page upload with the KB selected (Nemotron `nvidia/llama-3.3-nemotron-super-49b-v1`)

`/` → drop `examples/change_requests/TDD-ORD-002.docx`, provider **Nemotron (cloud)**, *Ground with
knowledge base* = **Order lifecycle (Existing_KG)** (`86d9919378bd4ebe8329f8ff950a2a27`), nickname →
**Compile** (`phase3-home-kb-selector.png`, `phase3-home-compiling.png`) → redirected to
`/projects/9fd540d5-c345-4bd1-a7ed-5d2d6625c909` (`phase3-project-after-upload.png`).

| Item | Measured |
|---|---|
| Compile (docx parse → grounded segmentation → grounded facts → change spec) | **338 s** wall-clock: segmentation 41 s, `extract:orderlifecycleworkflow` 223 s (3-pass review on), `change_spec` 50 s |
| Segmentation | **one** workflow segment (`orderlifecycleworkflow`, 7.5 KB) — the TDD hint held; Nemotron also emitted a self-dependency/trigger `OrderLifecycleWorkflow → OrderLifecycleWorkflow` which the assembler dropped with a warning (shown in the left rail) |
| Grounding record | KB name, 6 corpus source spans (TDD-ORD-001 docx lines 1-60, US-004/US-005, BRD, TP, `order_workflow.py`), coverage 0.81, `low_confidence` (⚠ on the header pill) |
| Spec names | activities `capture_order`, `validate_order`, `provision_order`, `dispatch_order`, `provision_group`, `dispatch_group`, `compensate_provisioning`, `compensate_dispatch`, `compensate_group_provision`, `consolidate_complete`; events `cancel_order`, `delivery_confirmed`, `cancel_shipment_group`; states RECEIVED → … → COMPLETED / REJECTED / CANCELLED, `PARTIALLY_DISPATCHED` as an end state — **not** `complete_order` (the Phase-1 TDD itself names the completion step `consolidate_complete`, "Generate final invoice") and **not** `get_status` (a query; `WorkflowFacts` has no query category — the change spec carries it) |
| `changes.md` (KB only, no CR → no seed rows, no requirement ids) | 6 components: `order_workflow.py`, `order_activities.py`, `shared/types.py` (modify), `order-state-machine-partial-shipment.mmd` (add), `TC-06, TC-09, TC-10` + `TC-18…20` under `tests/test_order_workflow.py`; 2 assumptions, 2 open questions, 6 sources — file paths corpus-relative, no node ids yet |

### Live run 2 — "Send to workflow GUI" from CR `dfad0d257db847919029f11dbef3c47d`

`/changes/dfad0d25…` shows the new **Send to workflow GUI** button next to Export all (TDD approved;
`phase3-wizard-send-button.png`) → overlay "Compiling the TDD into a grounded workflow project"
(`phase3-wizard-sending.png`) → redirected to the new project; the CR page then lists the project
under "Workflow project from this TDD" (`phase3-wizard-linked-project.png`). Run 2 (project
`f64d88c4…`, 223 s) surfaced two things fixed before run 2b: Nemotron kept only 10 of the 30
approved impact rows, and `get_status`/signals were folded into module entries. Run 2b (project
**`d64a03d8-939d-425a-b649-8816dce80ff3`**, the one driven through the gate):

| Item | Measured |
|---|---|
| Send → project (TDD markdown, seeded, requirement ids restricted) | **212 s**: segmentation 27 s, extraction 150 s, `change_spec` 35 s; nickname `TDD-ORD-002 — Partial Shipment Support for Multi-Line Orders`; `cr.project_ids` = `[f64d88c4…, d64a03d8…]` |
| Grounding record | KB + CR title, 7 source spans (adds `shared/types.py`, `tests/test_order_workflow.py`), coverage 0.85, `requirement_ids` BCR-01-01…06 |
| Spec | same activity/event names as run 1 plus 5 decisions and 5 exceptions; `PARTIALLY_PROVISIONED`/`PARTIALLY_DISPATCHED` in the state transitions |
| `changes.md` | **39 components** (28 modify, 1 remove, 8 add, 2 verify): `mod:existing_Codebase/workflows/order_workflow.py`, `fn:…shared/types.py:OrderState` / `ProvisioningResult` / `DispatchResult` / `CompletionResult`, activities `provision_order` (remove) / `provision_group` (add) / `dispatch_order` / `compensate_*` / `complete_order`, query `get_status`, signal `cancel_shipment_group`, diagrams `order-state-machine.mmd` (modify) + `order-state-machine-partial-shipment.mmd` (add) + `system-flow-diagram.md`, tests TC-01/06/09/10/12/16 + TC-18, docs US-003/004/005, TP-ORD-001 (+§3.2), EPIC-001/002, BR-06/07/09, TC matrix; requirement ids on the model's rows (BCR-01-01…06); Sources footer with 7 spans (`phase3-spec-changes-md.png`) — `order-sequence.mmd` / `system-architecture.mmd` are **absent** because neither the TDD nor the approved impact analysis names them |
| Validate (Nemotron 3 passes + deterministic change validator) | **113 s** (`validate:orderlifecycleworkflow` 112 s, `validate:__changes__` < 1 s); workflow: 6 grounding WARNs + 2 BLOCK (no trigger event; `d5` missing branch); `__changes__`: 1 WARN — `get_status` path `fn:…order_workflow.py:get_status` not in the KB with *did you mean* `chk:` suggestions (methods are not `fn:` nodes; `resolve_ref` now accepts `fn:<file>:<method>` when the file defines it — fixed after this run) (`phase3-validated-changes-findings.png`) |
| Resolve (guided) | agenda 7 questions across both files (`phase3-resolve-first-question.png`); `dialogue:start` **707 s** because the predraft job and a live `start` drafted concurrently (the first driver attempt aborted mid-flow — see gotchas); answers 6–36 s each (`dialogue:answer` 125 s total); result **4 answered, 3 parked** (`phase3-resolve-done.png`); the `get_status` chip answer set the path to `fn:existing_CodeBase/…` (the LLM-drafted option carried a typo — the next validate flagged it again: the gate works, suggestions are model text) — change spec v2, `human_provided` |
| Approve | 1st: 2 s — workflow **skipped** by the 2 BLOCKs (`needs_attention`), `changes.md` WARN does not block. Hand edits via `PUT /spec` (`- triggers: order request received`, `[d5] … yes: a7; no: e5`, dropped the junk `d6`) → validate 60 s → approve: compiled but **graph health 0.25** (15 orphan/unreachable *state* nodes from the descriptive State Transitions section) → dropped those bullets (R9 says descriptive) → validate 55 s → the trigger line was **stripped again** (pre-existing OPEN defect, memory `llm-timeout-and-trigger-stripping-defects`) → approve with `accept_incomplete=true` (the Approve-overrides toggle): **231 s**, `compile:orderlifecycleworkflow` 375 s cumulative → **COMPLETED**, health **0.95**, design `OrderWorkflow` with activities CaptureOrder…ConsolidateComplete, signal `delivery_confirmed`, query `get_status`, 7 generated files; `WorkflowState.kg_context` present (13 KB — the design prompt was grounded) (`phase3-results.png`) |
| Screenshots | `docs/kg-plan/screenshots/phase3-*.png` (home selector, compiling, project after upload, wizard send button/sending/linked project, spec workflow, spec changes.md, validating, validated workflow/changes findings, resolve first question/answered/done, pre-approve, approving, results) |

Plan checks, as observed: spec names `capture_order`, `validate_order`, `provision_order`,
`dispatch_order`, `cancel_order`, `delivery_confirmed`, states incl. `PARTIALLY_*` ✔;
`complete_order` ✘ (the TDD says `consolidate_complete`), `get_status` ✘ in the *workflow* spec
(no query category) but ✔ in `changes.md` and in the Temporal design; `changes.md` lists
`shared/types.py`, `workflows/order_workflow.py`, `activities/order_activities.py`,
`tests/test_order_workflow.py` ✔, the state-machine diagram + the new companion + the system-flow
doc ✔ (the sequence/architecture diagrams are not named by the inputs); validate → resolve →
approve completes ✔ (with two hand edits and the `accept_incomplete` override, both explained above).

### Gotchas found in this phase

- **`send-to-workflow` names a provider by design (cloud Nemotron default), so it bypassed the test
  override of `get_project_compiler` and built a real Nemotron provider — the API test hung on a
  network call.** Fixed with a `get_compiler_selector` dependency (`api/dependencies.py`) that
  `_select_compiler` uses for explicit selections; tests override it to return the mock compiler.
- **Nemotron under-reports change-spec rows on one pass** (10 of 30 approved impact rows kept). The
  approved impact analysis is human-approved: `ChangeSpecAgent.to_spec` now keeps every seed the
  model does not return (dropping is a hand edit in `changes.md`) and matches model rows to seeds
  by basename (`order_workflow.py` ↔ `existing_Codebase/workflows/order_workflow.py`); the prompt
  asks for one entry per activity / type / signal / query and for affected existing diagrams.
  39 rows on the next run.
- **Seed kinds**: impact rows say `document` for `.mmd` files and `requirement` for `BR-xx`;
  `coerce_kind(value, name)` now decides by name (`.mmd` → diagram, `.py` → module) and maps
  requirement/other → doc.
- **Methods are not `fn:` nodes** in the vendored ingest (only top-level defs/classes), so a change
  spec path like `fn:…/order_workflow.py:get_status` looked unknown. `KgService.resolve_ref` accepts
  `fn:<file>:<symbol>` when the file exists and defines the symbol (`def`/`class`).
- **The TDD's state machine becomes free-form State Transitions facts**, which the graph builder
  turns into orphan/unreachable state nodes → graph health 0.25 and a manual-review gate even
  though R9 says they are descriptive. Deleting the bullets at the gate fixes it; the pipeline was
  not forked (plan design note) — a Phase 4/5 candidate: skip state nodes when R9 is confirmed.
- **Validate strips the human `- triggers:` line** (pre-existing OPEN defect); the way through is
  the `accept_incomplete` override, which the UI only offers while the buffers are dirty — the
  override was sent through the jobs API here.
- **Predraft + live start ran concurrently**: opening the Resolve tab starts the `predraft` job, and
  clicking *Start resolving* before it finishes drafts the same agenda live (11.8 min for 7
  questions). Wait for "Questions ready." before starting, or accept the double cost.
- **LLM-drafted suggested answers are model text**: a chip carried `existing_CodeBase` (wrong case);
  applying it is by design (human authority), and the next validate flagged the path again.
- **Playwright's request context got `ECONNRESET` from uvicorn while approve ran** (codegen is CPU
  heavy); `curl` and the browser poller were fine — retry the poll.
- Bash-tool heredocs in this harness still turn `\b` into backspaces and unescape `\n` — every
  patch script went through the Write tool.

## Phase 4 — Post-approval change outputs: diagrams, modified code + diff, test docs (2026-08-18/19)

### Automated gates

| Gate | Result |
|---|---|
| `pytest -p no:warnings` | **699 passed** (681 from Phase 3 + 18 new: 16 `test_change_outputs.py` — models round trip, rewrite plan/order/dependents, component→file resolution, fence extract/continue, diagram checks + flow assembly, TC ids/merge/addendum + xlsx round trip + docx, engine end-to-end with `MockProvider` (ordered rewrite, continuation, syntax repair, unchanged copies, per-file persistence), stage failure keeps other stages, design summary/labels, auto-import, sibling-import coherence, dataclass check, tolerant plans, corpus exports; 2 `test_api_change_outputs.py` — approve job chains `change_outputs`, GET/regenerate/export.zip/files routes, 409/422/404s, CLI `approve-spec --change-outputs` + `change-outputs`) |
| `ruff check src tests` | clean |
| `mypy src` (strict) | clean, 189 files |
| `npm run build` | clean; `npx tsc --noEmit` clean; `npm run lint` = the same 2 pre-existing `RunPanel`/`SpecChatPanel` findings |

### Bring-up used for the live runs

As at the top of this file (backend `127.0.0.1:8010` **without** `--reload`, frontend `127.0.0.1:3010`,
demo account `kgdemo@example.com`). Playwright driver `scratchpad/pw/phase4.mjs` (`login` → `send` →
`gate` → `approve` → `outputs`) plus `scratchpad/live_regen.py` (API: `POST …/change-outputs/regenerate`
+ poll) and `peek.py`. The backend was restarted three times between jobs to pick up fixes found
during the runs (see gotchas) — never while a job was running. Every LLM call went to cloud
Nemotron `nvidia/llama-3.3-nemotron-super-49b-v1` (`regenerate` defaults to `KB_DEFAULT_PROVIDER`;
the first chained run used the server default `local-fallback`, fixed the same session — see gotchas).

### Live run 1 — `POST /projects/d64a03d8…/change-outputs/regenerate {stage: all}` (the COMPLETED Phase-3 project)

| Item | Measured |
|---|---|
| Job | `change_outputs` job, progress `diagrams… 0/3 → code… 1/3 → tests_doc… 2/3`, **1453 s** wall-clock, succeeded |
| Diagrams stage | **187 s**; `order-state-machine.mmd` gains `PARTIALLY_PROVISIONED` / `PARTIALLY_DISPATCHED` with real transitions (incl. cancel → `CANCELLING_*`), `order-sequence.mmd` gains a `par` block per shipment group + per-group `delivery_confirmed(order_id, group_id)` signals, `system-architecture.mmd` gains a Shipment Group Manager node, new `order-state-machine-partial-shipment.mmd`, plus the spec's `orderlifecycleworkflow-workflow.mmd`; `system-flow-diagram.md` re-assembled (sections 1–3 original titles/intros, 4 = spec diagram, 5 = companion). Checks: all passed except the companion (`missing state(s): PARTIALLY_DISPATCHED, PARTIALLY_PROVISIONED` — the model drew a stand-alone group lifecycle with a stray `[state]` line; the prompt now asks for composite `state PARTIALLY_* { … }` blocks — see run 2b) |
| Code stage | **1153 s**, 8 files rewritten in order `types → activities/__init__ → activities → workflows/__init__ → workflow → worker → starter → tests`; `types.py` gains `ShipmentGroup`, `PARTIALLY_PROVISIONED/PARTIALLY_DISPATCHED`, `list[ProvisioningResult]` / `list[DispatchResult]` / `shipment_groups` on `OrderState`; `order_workflow.py` (243 → 297 lines) fans out with `asyncio.gather(*provision_tasks, return_exceptions=True)` and again for dispatch, per-group compensation helpers (`_compensate_provisioning_up_to/_all`, `_compensate_dispatch_up_to/_all`), `@workflow.signal cancel_shipment_group(group_id)`, `get_status` with per-group state; `worker.py` registers `provision_group`/`dispatch_group`; `test_order_workflow.py` gains `test_partial_shipment_happy_path`, `test_cancel_single_shipment_group`, `test_compensation_for_failed_group`, `test_status_query_reflects_group_states`. Two spurious rewrites: `activities/__init__.py` (90 lines) and `workflows/__init__.py` (11 KB) — the "new component with no path" fallback picked the shortest path containing `activit`/`workflow` (fixed: package `__init__` files are never targets). `order_activities.py`: `ruff` F821 `timedelta` after the repair round (fixed: deterministic `auto_import`); `dispatch_group` imported by the workflow but the activities module kept `dispatch_order` (fixed: sibling-import coherence check → repair) |
| Test-docs stage | **109 s**; matrix 17 → **23 rows**: new **TC-18…TC-23** (split into groups at provisioning; independent per-group dispatch failure/compensation; cancel one group, others continue; cancel whole order across groups; per-group status query; consolidated completion), updated **TC-06 / TC-09 / TC-10 / TC-12** (notes appended, originals kept); addendum for **TP-ORD-001** with the §3.2 out-of-scope line removed, §4.2 *Functional / Group-Level Compensation* added, §4.4 test data, deliverables, exit criteria, risks; linked TDD-ORD-002 / EPIC-002. The change label was `dfad0d25` (CR id) — fixed: the grounding record now stores the BCR id (`BCR-001`) and the API passes it |
| Export | `GET …/change-outputs/export.zip` → 83 KB: `src/…` (README layout, imports `src.*` as the code expects), `tests/…`, `docs/diagrams/mermaid/*.mmd` (5) + `system-flow-diagram.md`, `docs/test-cases/TC-order-workflow.xlsx` + `TP-ORD-001-addendum-….docx/.md`, `changes.patch` (71 KB), `CHANGES.md` |

### Live run 2 — fresh project: Send to workflow GUI → gate → approve → chained change outputs

`/changes/dfad0d25…` → **Send to workflow GUI** → project **`76bdad1c-558d-4454-b4e6-27fe38e5006b`**
(`phase4-project-after-send.png`).

| Item | Measured |
|---|---|
| Send (TDD → grounded project, 38-component `changes.md`) | **232 s** (Phase 3: 212 s; a code job was running concurrently) |
| Hand edits + validate | trigger line + State-Transitions bullets dropped (as in Phase 3) → validate **385 s** (concurrent with a code job): 2 grounding WARNs, **1 BLOCK "No workflow inputs were declared"** — this spec came out thin (2.4 KB vs 7.5 KB in Phase 3: Nemotron variance) → hand-added `## Inputs` / `## Outputs` bullets |
| Approve (`accept_incomplete`, via jobs API) | **144 s** → **COMPLETED**, workflow `orderworkflow-partial-shipment` |
| Chained `change_outputs` job (auto-started by the approve job's `after` hook) | started 5 s after approve; **diagrams FAILED at 325 s** — Nemotron leaked two bare strings into the `diagrams` JSON array (`"notes"`, `"Added PARTIALLY_PROVISIONED…"`), pydantic rejected the plan on both attempts; **code (1176 s) and tests_doc (163 s) still ran and were persisted**, the job reported `failed` with the diagrams error — exactly the per-stage resumability the plan asked for. Fixed the same session: the plans drop non-object list items |
| `regenerate {stage: diagrams}` after the fix | **200 s**, all checks pass — the companion diagram is now `state PARTIALLY_PROVISIONED { GROUP_PROVISIONING → GROUP_PROVISIONED → GROUP_DISPATCHING → … }` / `state PARTIALLY_DISPATCHED { … }`; the other stages kept |
| Test docs | new TC-18…TC-23, updated TC-06/09/10/12, addendum `TP-ORD-001-addendum-BCR-001` (label correct on this project) |
| UI (`phase4-fresh-outputs-*.png`) | Results → **Workflows \| Change outputs 3/3** switch; Diagrams with Updated/Original toggle (`diagrams-updated`, `diagrams-original`, `diagram-partial`, `diagram-sequence`), Code with status badges + ast/ruff/repaired pills and unified / side-by-side viewers (`code-unified`, `code-split`, `code-workflow`, `code-tests`), Test cases with new/updated highlighting + only-changed filter (`tests`, `tests-changed`), **Download all (.zip)** → `BCR-001-76bdad1c-change-outputs.zip` (76 KB); the Time-saved card lists `change_outputs` 31 min against the 2 h estimate |
| Provider label | the chained job ran on the approve job's compiler = server default `local-fallback` (Spark first, cloud fallback) — plan D6 says file rewrites never go to the gateway by default; fixed: the chained job now uses `KB_DEFAULT_PROVIDER` (cloud Nemotron) through the compiler selector |

### Live run 3 — code stage re-runs on `d64a03d8…` after the fixes

| Run | Result |
|---|---|
| Re-run A (auto-import + no `__init__` targets live) | **1132 s**; 6 files (types, activities, workflow, worker, starter, tests), no `__init__` rewrites; workflow still imported `dispatch_group` while activities kept `dispatch_order`; `types.py` declared `tracking_number` twice → `TypeError` at import — the coherence + dataclass checks were added after this run |
| Re-run B (dataclass + coherence checks live) | **1102 s**; `types.py` **repaired** (duplicate field), `order_workflow.py` **repaired** and now imports only names the activities module defines (`dispatch_group`, `provision_group`, …), `test_order_workflow.py` failed `ast.parse` even after the repair round (an `async def` inside a list literal) — recorded as `ast_ok=false` + warning; `LineItem` still undefined in activities (corpus-aware auto-import came after) |
| Re-run C (everything live: auto-import incl. corpus exports, sibling coherence, dataclass check) | **832 s**; **every file `ast ok` + `ruff ok`** (activities and types repaired once each, workflow and tests clean on the first answer); the bundle **imports and collects** for the first time |

### Running the generated tests (scratch venv, `temporalio` + `pytest-asyncio`, `WorkflowEnvironment.start_time_skipping()`)

Recorded honestly:

- **Baseline first:** the corpus's *own* `tests/test_order_workflow.py` (unchanged, `src/` layout)
  fails **4/4** in a fresh venv — `temporalio` 1.20.0 and 1.31.0, Python 3.11 and 3.12 alike: the
  default data converter decodes an `OrderStatus(str, Enum)` field into a list of characters
  (`status=['R','E','J',…]`), so every assertion on `.status` fails. Anything generated on top of
  this code base inherits that unless it avoids `str`-Enum result fields.
- Run-1 / re-run-A bundles: **collection error** — `types.py` duplicate `tracking_number` field
  (`TypeError: non-default argument 'carrier' follows default argument`).
- Fresh-project bundle (76bdad1c): **collection error** `NameError: LineItem` in activities; after a
  one-line import fix, `ImportError: cannot import name 'dispatch_group'` (workflow ≠ activities).
- Re-run-B bundle: **collection error** — `SyntaxError` at line 194 of the rewritten test module.
- Re-run-C bundle: **collects, 4 tests run, 4 fail at runtime** — `make_order() got an unexpected keyword argument 'line_items'` (the rewritten helper kept the old signature while the new tests call it with `line_items=`) and `ValueError: More than one activity named compensate_group_provision` (a test double is registered twice) — internal slips inside the generated test module, not the workflow code (which imports cleanly).

So: **no generated bundle ran green in this phase.** What the pipeline delivers today is a
reviewable, checked draft (ast / ruff / coherence / dataclass verdicts on every file, a diff per
file) rather than a passing test suite; the deterministic checks caught every failure listed above
before a human did, and each round of fixes removed a failure class. Remaining model-quality issues
(style drift, invented APIs such as `activity.defn(retry_policy=…)`, syntax slips in long test
files) are Phase 5 candidates: a second repair round for the tests file, and a `py_compile`/import
smoke test of the bundle in a subprocess.

### Gotchas found in this phase

- **A whole Python file inside JSON is what long-context models break** — the fenced-`complete`
  protocol (decision) never truncated on `order_workflow.py`, but Nemotron *did* leak bare strings
  into the diagrams JSON array once (structured plan rejected twice → stage failed, other stages
  persisted). Plans now drop non-object list items.
- **New components must never land in package `__init__.py`** — the "shortest path containing
  'activit' / 'workflow'" fallback for a component with an empty path picked
  `activities/__init__.py` and `workflows/__init__.py` (two wasted rewrites, 20 min).
- **The model invents sibling names despite being given the signatures** (`dispatch_group` vs
  `dispatch_order`), forgets imports (`timedelta`, `LineItem`) and duplicates dataclass fields —
  each now a deterministic check feeding the single repair round (`missing_imports`,
  `dataclass_problems`, `auto_import` incl. the corpus's own exports).
- **The companion state diagram** came out as a stand-alone group lifecycle until the prompt asked
  for composite `state PARTIALLY_* { … }` blocks; the required-state check is what surfaced it.
- **The chained job inherits the approve job's compiler** — which is the server default
  (`local-fallback`); D6 requires cloud for long generations, so the chain now selects
  `KB_DEFAULT_PROVIDER` explicitly.
- **The BCR id lives on the change request** (`bcr_meta.doc_id`), not on the project — the
  grounding record now carries `change_request_label`, and the API/CLI pass it for older projects.
- **Nemotron variance at the gate**: the fresh compile produced a 2.4 KB spec with no Inputs (a
  BLOCK the Phase-3 run did not have); the gate did its job, one hand edit fixed it.
- **The corpus's own tests do not pass in a fresh env** (see above) — establish the baseline before
  judging generated tests.
- Harness: background Bash calls die at 600 s (detach long drivers and watch the log with Monitor);
  Bash heredocs still unescape `\n` — every multi-line patch went through the Write tool; the
  Chrome DevTools MCP server was again unavailable, Playwright (`pw/phase4.mjs`) drove the browser.

## Phase 5 — Hardening, docs, demo runbook (2026-08-18/19)

### Automated gates

| Gate | Result |
|---|---|
| `pytest -p no:warnings` | **718 passed** (699 from Phase 4 + 19 new: 11 `test_hardening.py` — id/slug guards, `next_version` / `stored_version`, every file store refusing path-shaped ids on load *and* save, `bundle_dir`, CAS on the project / CR / KB stores (file + in-memory), filename sanitising, HTTP `ETag` / `expected_version` / `If-Match` → 409 on `PUT /spec` + `PATCH`, path-shaped ids over HTTP; 1 CR artifact-PUT CAS test; 8 in `test_change_outputs.py` — `normalise_style`, subprocess smoke verdicts (failed / passed / compile error / interpreter missing), engine second repair round + smoke, `repair_rounds=0`, `change_outputs` time-saved bucket, `describe_syntax_error`, nested-import coherence, `late_annotation_names`) |
| `ruff check src tests` | clean |
| `mypy src` (strict) | clean, 191 files |
| `npm run build` | clean; `npx tsc --noEmit` clean; `npm run lint` = the same 2 pre-existing `RunPanel`/`SpecChatPanel` findings |

### What was hardened (and how to see it)

- **Store-boundary guards** — `storage/ids.py`; every file store + `bundle_dir` + export filenames.
  `GET /projects/..%2Fx` → 404, a crafted id can never build a path; export names like
  `BCR-001-41cec612-change-outputs.zip` come out of `safe_filename_part`.
- **Compare-and-swap** — `version` on projects / KBs / CRs, bumped on every save; opt-in
  `expected_version` / `If-Match`; `ETag` on the GETs. Live (project `41cec612…`, script stage
  `cas`): `PUT /spec` with the current version 4 → **200, ETag "5"**; the same PUT again with 4 →
  **409** *"changed since it was loaded (stored version 5, expected 4). Reload and retry."*;
  `PATCH` with `If-Match: "4"` → **409**. The editors send the version and show *Reload the latest
  version* on 409.
- **scrypt off the event loop** — register / login hash in `asyncio.to_thread`.
- **Phase-4 backlog** — N targeted repair rounds (all failing verdicts in one prompt, syntax
  errors with the offending lines + the def-inside-a-list hint), the bundle **smoke test**
  (`py_compile` + import of the export layout in a child interpreter, on the card), the
  **keep-style** pass, the temporalio API surface pinned in the rewrite prompt, the
  `change_outputs` baseline key (16 h; the Time-saved card lists it), the sibling-import check
  walking nested imports, the export zip named after the BCR id, mermaid errors no longer
  appended to the page, 409 hint on Regenerate.

### Live run 1 — code stage re-run on `d64a03d8…` with the second repair round + smoke test (Nemotron)

`POST …/change-outputs/regenerate {stage: code}` (`scratchpad/live_regen_p5_code.log/.json`, bundle
+ pytest log under `scratchpad/p5_run1/`):

| Item | Measured |
|---|---|
| Job | **1233 s** (code stage 1227 s), succeeded; 6 files rewritten in order types → activities → workflow → worker → starter → tests |
| Per-file verdicts | `types.py` clean first answer (0 rounds), `starter.py` 0 rounds; `order_activities.py` **1 round** (verdict: must define `compensate_provisioning`, `compensate_dispatch` + `LineItem` undefined — fixed), `worker.py` 1 round (imports names the rewritten activities do not define — fixed), `order_workflow.py` 1 round (F821 — fixed); **every source file `ast ok` + `ruff ok` + `style kept`** (`List[...]` → `list[...]`, blank lines restored) |
| `tests/test_order_workflow.py` | **still does not parse after 2 repair rounds** — the model wrote `async def fake_dispatch_group_failing(…)` *inside* the `activities=[…]` list literal (line 160) three times running; the repair prompt only carried *"invalid syntax (line 160)"* → `describe_syntax_error` now adds the lines and the explicit "define it at module level, put the NAME in the list" hint (landed after this run; exercised by run 2) |
| Bundle smoke test | **failed** — `compiled 10`, `imported 10/11` (**every `src.*` module imports**), the one error is the test module's SyntaxError; 1.5 s |
| Generated tests in `tvenv` (py 3.12, temporalio 1.20) | **collection error** at the same line — exactly what the smoke card said before the download (baseline: the corpus's own tests fail 4/4, re-confirmed 2026-08-19) |

### Live run 2 — the full demo pass (fresh KB → CR → wizard → export → send → gate → approve → outputs)

Driven with `scratchpad/pw/phase5.mjs` (`login → kb → cr → wizard → export → send → gate → cas →
approve → outputs`) following the *Demo script* section; all model calls on cloud Nemotron
`nvidia/llama-3.3-nemotron-super-49b-v1`; the backend was restarted three times between jobs to pick up
fixes found during the run (never while a job ran). Ids: KB **`4fc250d8b4cf4f3bbcb0fdcba0ec95fc`**
(*Order lifecycle (Existing_KG) — Phase 5 demo*), CR **`61087a8b847c4d67b0f708378fff4c2a`**,
project **`41cec612-b4b5-45c9-94d0-4678de821283`** (all under `.workflow_state/` on this machine).

| Step | Measured |
|---|---|
| KB upload + enrich (cold, 22 file nodes + clustering) | **1387 s = 23 min**; 394 nodes / 960 edges; catalog `EPIC-001`, `US-001..007`, `TC-01..17`, `BR-01..12`, `BCR-001`, documents `BRD/TDD/TP-ORD-001`; warnings: top-level folder stripped, *3 file(s) skipped after repeated LLM failures* (Nemotron JSON hygiene — Reindex + enrich would re-ask only those); *Ask the graph* "how does dispatch compensate provisioning" → coverage 100 % (`phase5-kb-*.png`) |
| CR create (docx → meta / 6 requirements / 20 seeds) | < 1 s; `phase5-cr-created.png` |
| Start wizard → impact questions | **39 s** (ids EPIC-002 / TDD-ORD-002 / TC-18, 86 impact rows) |
| Impact: 2 questions (chips) → draft → approve | answers 3 s / 12 s; draft **202 s** (draft + coverage pass); v1 = 25 affected rows naming `order_workflow.py`, `types.py`, `complete_order`, TC-06/09/10, US-003/004/005, EPIC-001, the state-machine diagram; 14 sources, coverage 0.75 |
| EPIC: 3 questions → draft → approve | next-step questions ≈ 48 s; draft **88 s**; Epic Statement / Business Value / In-Scope Capabilities / DoD / Story Map / NFRs / Dependencies / Risks |
| Stories: 3 questions → draft → approve | questions ≈ 5.6 min (one slow Nemotron call); draft **149 s** (3 batches) → **US-008…US-014** (7 stories, 21 Given/When ACs) |
| TDD: 5 questions → draft → approve | questions ≈ 54 s; draft **136 s** (4 chunks) → 8 sections × Existing/Proposed, `PARTIALLY_PROVISIONED/DISPATCHED`, `list[ProvisioningResult]`, `get_status`, companion diagram; CR **complete** |
| Wizard end to end | 02:22:22 → 02:42:43 = **20 min** wall-clock, unattended (`phase5-<step>-*.png`, `phase5-wizard-complete.png`) |
| Export (UI) | TDD `.docx` 40 103 B, `BCR-001-61087a8b-export.zip` 382 644 B, both < 1 s (`phase5-cr-export.png`) |
| Send to workflow GUI | **330 s** (segmentation 81 s, extraction 157 s, change spec 91 s); grounding coverage 0.82, 9 sources, requirement ids BCR-01-01…06; `changes.md` **34 components** (21 modify / 7 add / 6 verify: 4 modules, 7 activities, 3 types, 1 signal, 1 query, 4 diagrams, 6 tests, 8 docs); spec 3.2 KB with the trigger line **present** this time (`phase5-project-after-send.png`, `phase5-project-changes-md.png`) |
| Hand edits + `PUT /spec` (expected_version 2 → ETag "3") + validate | validate **141 s** — findings: 2 completeness WARNs (`state: PARTIALLY_PROVISIONED / _DISPATCHED`), 1 `changes.md` WARN (`updated-system-architecture.mmd` not in the KB — the model named the *new* file); **no BLOCK** (`phase5-project-validat*.png`) |
| CAS demo | see *What was hardened* (200 → 409 → 409) |
| Approve (no override needed) | **247 s** → **COMPLETED**, workflow `orderlifecycleworkflow` (`phase5-project-approv*.png`) |
| Chained `change_outputs` (auto, cloud Nemotron) | started 5 s after approve; **1675 s = 28 min**: diagrams 266 s, code 1315 s, tests_doc 98 s (`phase5-outputs-running.png`) |
| Diagrams | `order-sequence.mmd` (par block per group), `system-architecture.mmd`, companion `order-state-machine-partial-shipment.mmd` (all checks pass), spec diagram; `order-state-machine.mmd` **check failed** (the model rewrote it as a coarse 6-state machine dropping `PROVISIONING/DISPATCHING/…` — flagged, original kept side by side); `updated-system-architecture.mmd` (a companion the change spec invented) — model returned no diagram (flagged) |
| Code (first chained run) | 6 files, **every file `ast ok` + `ruff ok`**, tests file clean on the first answer, `types.py`/`starter.py` 0 rounds, activities / worker / workflow 1 round each, `style kept` on all; **bundle smoke test FAILED**: `src.workflows.order_workflow` (and `worker`, `starter`, `tests`) — `ImportError: cannot import name 'compensate_provisioning' from src.activities.order_activities`. Root cause: the workflow imports its activities inside Temporal's `with workflow.unsafe.imports_passed_through():` block and the sibling-import coherence check only walked top-level imports → **fixed** (`ast.walk`), test added; the smoke test did exactly what it was added for (`phase5-outputs-code-smoke.png`) |
| Generated tests in `tvenv` (first chained run) | **collection error** — the same ImportError (`scratchpad/p5_demo/pytest.log`) |
| Test docs | 17 → **23 rows**: new **TC-18…TC-23**, updated **TC-05/06/09/10/12**; addendum `TP-ORD-001-addendum-BCR-001` (`phase5-outputs-tests*.png`) |
| Export | **Download all (.zip)** → `BCR-001-41cec612-change-outputs.zip` (75 023 B, README layout) |
| Time-saved card | lists `change_outputs` 28 min against the new **16 h** estimate (`phase5-outputs-diagrams-updated.png`) |
| Code re-runs on the same project (`regenerate {stage: code}`) after the nested-import fix | **run 2 — 902 s**: every file `ast ok` / `ruff ok`, `types.py` 1 round (F821), activities 1 round (`dispatch_order` symbol), workflow 1 round (F821), tests clean; **smoke FAILED** again, differently: `NameError: name 'GroupStatus' is not defined` — the model redefined `GroupStatus` *below* the workflow class and used it in a `@workflow.query` annotation, which Temporal evaluates at import (`typing.get_type_hints`); ruff was satisfied (the name exists in the file) → new deterministic check `late_annotation_names` (+ prompt rule) landed. **run 3 — failed at 1093 s: Nemotron `HTTP 504`** on the activities file (the provider's retries gave up; the stage is recorded `failed`, the job re-runnable — a partial bundle stays persisted). **run 4 — 692 s**: activities 1 round, workflow 1 round, four files clean first answer, all `style kept`; **bundle smoke test PASSED — 11 compiled, 11/11 modules imported** (`phase5-final-outputs-code-smoke.png`), the first bundle of the whole project that imports end to end |
| Generated tests of the final bundle, one process per test, 120 s hard timeout (`scratchpad/p5_demo_rerun2/per_test.log`) | 6 tests: **0 pass · 4 fail · 2 hang** — `test_validation_failure_rejects_without_provisioning` and `test_cancel_after_provisioning_compensates_reservation` fail **exactly like the corpus baseline** (`status == ['R','E','J',…]`, the str-Enum decode); `test_partial_shipment_provisioning` `TypeError: LineItem.__init__() missing 'unit_price'` and `test_mixed_cancellations` `signal() got an unexpected keyword argument 'group_id'` are slips inside the generated test module (helper / signal signature vs. the rewritten types and workflow); `test_happy_path_reaches_dispatched` and `test_status_query_reflects_current_state` **hang** — the rewritten workflow waits for a per-group `delivery_confirmed` the old-style test never sends. The workflow / activities / types / worker / starter modules themselves import and run under the time-skipping test server. |
| Final export | `BCR-001-41cec612-change-outputs.zip` (75 420 B); note the outputs' warning list still shows the *previous* runs' smoke failures twice — fixed after this run (smoke warnings now carry the `code ` prefix a stage re-run drops) |

### Running the generated tests (scratch venv `tvenv`: py 3.12, temporalio 1.20, pytest-asyncio 1.4)

Recorded honestly, against the corpus baseline (**the corpus's own tests fail 4/4** — str-Enum
decode through temporalio's default converter — re-confirmed at the start of this phase):

- `d64a03d8…` re-run (run 1): **collection error** — `SyntaxError` at line 160 of the rewritten
  test module (`async def` inside a list literal), predicted by the smoke card.
- `41cec612…` chained run: **collection error** — `ImportError: cannot import name
  'compensate_provisioning'` (workflow ≠ activities inside `imports_passed_through`), predicted by
  the smoke card; check fixed the same session.
- `41cec612…` code re-run 2: **collection error** — `NameError: GroupStatus` (annotation evaluated at
  import, name defined below the class), predicted by the smoke card; check + prompt rule added.
- `41cec612…` code re-run 4 (final): **the bundle imports (smoke passed 11/11)**; per test with a
  120 s timeout: **0 pass · 4 fail · 2 hang** — 2 baseline-class failures (str-Enum decode, same
  as the corpus), 2 generated-test slips (helper kwargs / signal kwargs), 2 hangs (test signals
  the order-level `delivery_confirmed`, the workflow now waits per group).

So: **still no generated test suite ran green in this phase — but for the first time a generated
bundle imports end to end** (smoke 11/11 on the demo project's final run), and the gap moved from
"does not import" to "the generated *tests* disagree with the generated *workflow* about the
contract" (per-group delivery signals, helper kwargs) plus the corpus's own str-Enum decode. The
smoke test tells the reviewer *before* the download exactly where a bundle breaks, and each live
slip became a deterministic check or a better verdict (nested imports, late annotations, syntax
context + hint). The deliverable remains a checked, reviewable diff.

### Gotchas found in this phase

- **A shell that exits kills its children on Windows** — servers started with `(… &)` from the
  Bash tool died with the call; `Start-Process … -WindowStyle Hidden` (PowerShell) keeps uvicorn
  / `next dev` alive across tool calls.
- **Every heredoc path unescapes** — `\n` inside a JS/TS string literal, `\\.` in a regex — even a
  Python here-string; the only safe path for multi-line patches is the Write tool + running the
  file (Bash `sed` one-liners are fine).
- **Temporal workflow modules import inside `with workflow.unsafe.imports_passed_through():`** — any
  import-coherence check must `ast.walk`, not iterate `tree.body`.
- **The smoke test is the honest verdict** — per-file `ast`/ruff/coherence all passed on the
  demo project's first chained run and the bundle still did not import; without the child
  interpreter the reviewer would have found out from pytest.
- **Nemotron variance on the same corpus**: run 1 wrote a `def` inside a list three times running;
  the demo run's test module was clean on the first answer but the workflow imported a name the
  activities dropped. Every deterministic verdict added this phase came from one of these.
- **Fresh KB = cold `llm_cache/`** (23 min); a KB directory that already has the cache re-enriches
  in ≈ 5 min — for a live demo, pre-index or reuse the KB.
- Mermaid appends a "bomb" to `document.body` on a syntax error unless
  `suppressErrorRendering: true` — a regenerated diagram with a slip put it at the bottom of the
  Results tab.
