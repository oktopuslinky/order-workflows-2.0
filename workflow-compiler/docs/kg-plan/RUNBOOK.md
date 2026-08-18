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
