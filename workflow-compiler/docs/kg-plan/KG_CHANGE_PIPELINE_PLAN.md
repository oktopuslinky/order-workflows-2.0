# KG-Grounded Business-Change Pipeline — Multi-Phase Plan

**Branch:** `feat/kg-change-pipeline` (worktree `../order-workflows-kg`, based on `demo/dialogue-plus-run` @ `0a6e84d`)
**Written:** 2026-08-17 · **Status:** plan approved by the user; **Phase 0 done 2026-08-17** (see `HANDOFF.md`), Phase 1 next

This document is the contract for a sequence of implementation sessions. Each phase is sized to
fit one context window, ends with a green test suite + a live run against the real corpus, and
leaves a handoff note so the next session can start cold. **Read §0 first in every phase.**

---

## 0. Context recipe (read this at the start of every phase)

The manager's ask (verbatim intent, re-ordered into a pipeline):

1. **Initialize a knowledge graph (KG)** from the `Existing_KG` folder of
   `github.com/SoumyajitPodder/Intelligent_Workflow_Builder` (branch `Sample_Doc_Code`) —
   business docs (BRD, EPIC, user stories, TDD, test plan, TC matrix, mermaid diagrams) +
   `existing_Codebase` (Temporal Python `OrderWorkflow`) + tests.
2. Treat `New_business-change/BCR-001-partial-shipment-support.docx` as the **new requirement**.
3. **Use conversational chat** to produce (a) detailed changes + impact analysis, (b) a **new EPIC
   and user stories** from the BCR informed by the KG, (c) a **technical design document** with
   existing vs. to-be-changed.
4. **Upload that TDD into the workflow GUI**, analyze it into a `.md` (spec) that references the
   existing codebase, then generate: an **updated system flow diagram**, **new code** (an updated
   version of the existing codebase), and an **updated test-case document** (new + updated TCs).

**User decisions (locked — do not re-litigate):**

| # | Decision | Choice |
|---|---|---|
| D1 | Base branch | `demo/dialogue-plus-run` |
| D2 | KG-Context integration | **Vendor** `contexthub/{model,bootstrap,retrieval,identity.py,paths.py}` into `workflow_compiler/kg/contexthub/` at a pinned SHA, adapt behind a thin service layer |
| D3 | "Generate new code bases" | **Updated copies of `Existing_KG/existing_Codebase` + tests** implementing BCR-001, with a diff view (not a greenfield bundle; running them in the Run panel is out of scope) |
| D4 | Document format | **Markdown source of truth + `.docx`/`.xlsx` export** styled like the manager's templates |
| D5 | Corpus ingress | **Zip/folder upload in the UI** (a "Knowledge Base" screen); BCR uploaded as a change-request docx |
| D6 | LLM | **Selectable per request, default cloud Nemotron** (reuse the per-compile provider selector) |
| D7 | Rigor | **Full**: pytest + ruff + mypy on new code + a **live LLM E2E** on the real BCR-001 corpus recorded in the runbook, every phase |
| D8 | Chat style | **Guided step-by-step wizard** (Impact → EPIC → Stories → TDD) that asks clarifying questions before drafting each artifact, like the Resolve dialogue |
| D9 | TDD analysis | **Both**: existing `WorkflowSpec` pipeline (KG-grounded prompts) **plus** a change-spec section (existing vs. changed per component) |
| D10 | Diagrams | **Both**: regenerate the 3 Existing_KG diagrams + the BCR-named companion `order-state-machine-partial-shipment.mmd`, **and** the per-workflow spec mermaid |
| D11 | Timeline | No fixed date — optimize for quality |

**Research digests (read the relevant one, not the source, when you need facts):**

- `docs/kg-plan/research/reference-repo-digest.md` — every doc/code file in the manager's repo,
  BCR-001 in full, and the **exact docx/xlsx template conventions** to reproduce.
- `docs/kg-plan/research/kg-context-digest.md` — contexthub's `init_repo` / `build_context`
  signatures, node/edge schema, gotchas, and what to vendor.
- `docs/kg-plan/research/workflow-compiler-digest.md` — this app's extension points: agent
  recipe, route inventory, job kinds, frontend layout, storage.

**Repo-level ground rules that still apply:** `CLAUDE.md` (LLM specifies / deterministic code
emits; every semantic field must render + parse back; human gate stays the oracle), `ruff check
src tests`, `pytest` offline via `MockProvider`, keep `README.md` / `docs/HOW_IT_WORKS.md` /
`docs/architecture.md` in sync when behavior changes. Windows: `PYTHONUTF8=1` for any redirected
CLI output; read API JSON with explicit utf-8.

**Live-run environment (from the demo runbook / memory):** backend `python -m uvicorn
workflow_compiler.api.app:app --reload` (:8000), frontend `npm run dev` (:3000), provider
`nemotron` for anything long (Spark serves one model at a time and the 30B model times out on long
generations). Only `/projects/compile*` currently takes a per-request provider — the new KB/CR
routes must accept `provider`/`model` the same way (D6).

**Reference corpus:** cloned at
`%LOCALAPPDATA%\Temp\claude\...\scratchpad\iwb` this session; Phase 0 copies it into
`examples/knowledge_bases/order-lifecycle/` so every later phase (and the demo) has it in-repo.

---

## 1. Target architecture (what exists at the end)

```
                ┌──────────────────────────── Knowledge Base (new) ─────────────────────────────┐
  zip upload ─▶ │ unzip → corpus/  → contexthub ingest (static) → optional LLM enrich → graph.json │
                │ KgService.retrieve(prompt, budget) → ContextPacket (BM25 anchor → BFS → fetch)  │
                │ KgService.impact(seeds) → deterministic affected-node table                     │
                └───────────────────────────────────────────────────────────────────────────────┘
                                 ▲ grounds every LLM prompt below
  BCR docx ───▶ Change Request (new) ── guided wizard (D8) ──▶ artifacts (markdown, versioned)
                   Impact analysis → EPIC-002 + US-00N → TDD-ORD-002       + docx/xlsx export (D4)
                                                             │ "Send to workflow GUI" / upload
                                                             ▼
                Workflow project (existing pipeline, now KG-grounded, + change spec (D9))
                   compile-upload(kb_id, cr_id) → segmentation → specs/*.md + changes.md
                   [HUMAN GATE: edit ⇄ validate ⇄ resolve]  → approve-spec
                                                             │
                                                             ▼ post-approval change outputs (new)
                   updated diagrams (D10) · modified codebase + diff (D3) · updated TC matrix/TP + tests
```

New top-level packages: `workflow_compiler/kg/` (Phase 0), `workflow_compiler/change/` (Phase 1),
`workflow_compiler/docs_export/` (Phase 2), `workflow_compiler/change_outputs/` (Phase 4).
Everything LLM-facing follows the existing agent recipe (`prompts/templates/*.md` +
`llm.structured(...)` returning a pydantic plan; deterministic engine applies it).

---

## 2. Phases

Each phase lists: goal · deliverables (files) · design notes · tests · live verification · exit
criteria · handoff. Phase order is a dependency chain; do not start N+1 until N's exit criteria
are met and `docs/kg-plan/HANDOFF.md` is updated.

### Phase 0 — Knowledge-base foundation (vendor KG, ingest, retrieve)

**Goal:** a user can upload a zip of `Existing_KG`, get a persisted knowledge base with a
contexthub graph, and query it. Nothing about change requests yet.

**Deliverables**

- `src/workflow_compiler/kg/contexthub/` — vendored from
  `C:\Users\devag\Documents\Code (local)\KG-Context-bm-devansh` @ `0447cad`:
  `model/`, `bootstrap/` (`pipeline, ingest, chunking, formats, store, enrich, cluster, llm,
  catalogs, idlinks, build`), `retrieval/` (`index, hub, context, fetcher`), `identity.py`,
  `paths.py`. Add `VENDORED.md` (source path, SHA, date, list of local edits). Exclude from
  `mypy --strict` via `pyproject.toml` `[[tool.mypy.overrides]] module = "workflow_compiler.kg.contexthub.*"; ignore_errors = true`; keep ruff on it but allow per-file ignores if needed.
- **Local edits to the vendored code (each recorded in VENDORED.md):**
  1. `paths.py`: drop `REPO_ROOT/examples` + default graph path assumptions.
  2. `bootstrap/enrich.py` / `cluster.py`: accept an injected client object with
     `chat_json(messages, *, label, retries) -> dict` instead of constructing `LlmClient(config)` —
     so `kg/llm_bridge.py::ProviderJsonClient(BaseLLMProvider)` (uses `provider.complete` +
     the existing `llm/json_utils` repair) can be passed. Mock provider works in tests.
  3. `bootstrap/ingest.py`: normalise node ids / `metadata.path` to POSIX separators (`/`) so
     graphs are OS-independent (gotcha in the KG digest); route `.pdf` through
     `workflow_compiler.ingestion` instead of skipping it.
- `src/workflow_compiler/kg/models.py` — `KnowledgeBase{kb_id, name, owner_id, root_dir,
  source: {kind: "zip"|"path", filename}, status: ingesting|ready|failed, stats: {nodes, edges,
  by_type}, indexed_at, llm_enriched: bool, provider_used, catalog: {epics:[ids], stories:[ids],
  test_cases:[ids], requirements:[ids]}, warnings, created_at, updated_at}`;
  `KgRetrieveRequest{prompt, budget=4000, max_hops=2}`; `KgPacket` (rendered, sections, files,
  coverage, low_confidence, seeds); `KgImpactRow{node_id, type, name, path, hops, via}`.
- `src/workflow_compiler/kg/store.py` — `KnowledgeBaseStore` protocol + `FileKnowledgeBaseStore`
  under `<state-root>/knowledge_bases/<kb_id>.json`, corpus + graph under
  `<state-root>/knowledge_bases/<kb_id>/{corpus/, .contexthub/}`; `InMemoryKnowledgeBaseStore`.
  **Reject ids not matching `[A-Za-z0-9_-]+`** (path-traversal P0 from the audit memory applies here too).
- `src/workflow_compiler/kg/ingest.py` — `extract_zip(bytes, dest)` with **zip-slip protection**
  (reject absolute paths / `..` / links; size cap; file-count cap), strip a single top-level
  folder if present (`Existing_KG/…` → `corpus/…`).
- `src/workflow_compiler/kg/service.py` — `KgService(store, provider_factory)`:
  `create_from_zip(name, bytes, *, owner_id, enrich: bool, provider, model) -> KnowledgeBase`
  (runs `init_repo(corpus, out_dir=…/.contexthub, llm_config=None|bridge)` in a thread —
  `asyncio.to_thread`, ingest is CPU/IO), `reindex(kb_id, …)`, `retrieve(kb_id, prompt, budget,
  max_hops) -> KgPacket` (wraps `build_context` with an mtime-keyed graph cache like
  `hub/graphs.py`), `impact(kb_id, seeds: list[str] | terms, max_hops) -> list[KgImpactRow]`
  (BFS over `IMPACT_EDGE_TYPES` + `DEPENDS_ON`/`IMPORTS`/`RELATES_TO`, deterministic),
  `catalog(kb_id)` (ids of Epic/UserStory/TestCase/Requirement nodes → used later for numbering
  EPIC-002 / US-008 / TC-18), `search(kb_id, query, k)` (BM25 anchors, for the UI debug box).
- API (`api/app.py` + `api/schemas.py`): `POST /knowledge-bases` (multipart `file` zip, `name`,
  `enrich`, `provider?`, `model?`) → creates + kicks a background **job** (`JobKind += "kb_ingest"`;
  jobs are keyed by project today — generalise `JobManager` to a `scope_id` string so KB jobs
  coexist), `GET /knowledge-bases`, `GET /knowledge-bases/{id}`, `DELETE`, `POST …/reindex`,
  `POST …/retrieve {prompt,budget}`, `GET …/impact?seed=…`, `GET …/files?path=` (read a corpus
  file — needed by later phases and the UI), `GET …/graph/summary` (counts by type, top nodes).
  Auth: same `get_current_user`; `owner_id` recorded; shared like projects.
- CLI: `workflow-compiler kb init <zip-or-folder> [--name] [--enrich/--no-enrich] [--provider]`,
  `kb list`, `kb ask <kb-id> "<prompt>"` (prints the packet), `kb impact <kb-id> <seed>`.
- Config (`config.py`): `kg_enrich_default: bool = True`, `kg_retrieve_budget: int = 4000`,
  `kg_max_upload_mb: int = 50`.
- Frontend: `app/knowledge/page.tsx` (list + upload form with provider picker + enrich toggle,
  job progress via the existing `runs.tsx` poller), `app/knowledge/[id]/page.tsx` (stats by
  node type, catalog ids, corpus file tree, an "Ask the graph" box showing `rendered` + files +
  coverage — the debug/demo surface). `lib/api.ts` + `lib/types.ts` additions; nav link.
- Examples: `examples/knowledge_bases/order-lifecycle/` = a verbatim copy of the manager's
  `Existing_KG` (docs + code + tests + README) and
  `examples/change_requests/BCR-001-partial-shipment-support.docx`. Add a
  `scripts/make_kb_zip.py` (or documented `Compress-Archive`) for the demo.

**Design notes**

- Static ingest is instant; LLM enrichment is one call per Document/Module (~30 for this corpus)
  + one clustering call → minutes on cloud, so it is a job with progress events.
- The graph store stays contexthub's JSON; we do not invent a new format. Node ids from the
  corpus are relative to `corpus/` so they read like `mod:existing_Codebase/workflows/order_workflow.py`.
- Add a small `domains/order-lifecycle.domain.yaml` under the example so the Gaussian bands
  have a real business domain (KG digest §7 gotcha) — optional, do it if retrieval looks flat.

**Tests** (`tests/test_kg_*.py`): zip extraction incl. zip-slip rejection; ingest of a tiny
fixture corpus (`tests/fixtures/kb_mini/` — 2 md docs, 1 py, 1 mmd, 1 docx generated in-test with
python-docx) → node counts by type, id normalisation; retrieve returns sections with real
line spans; impact BFS; store round-trip; API tests via TestClient (upload → job → ready →
retrieve; ownership); CLI smoke; `ProviderJsonClient` against `MockProvider` for enrichment.

**Live verification:** upload the zipped `Existing_KG` through the UI with `enrich=true` on
Nemotron; confirm node counts (expect Document ≈ 15, Module ≈ 8, Function/Class, Chunk,
UserStory US-001..005(+006/007 minted), TestCase TC-01..17, Epic EPIC-001, Requirement BR-xx);
ask "how does dispatch compensate provisioning" and check the packet dereferences
`order_workflow.py` lines. Record timings in `docs/kg-plan/RUNBOOK.md`.

**Exit criteria:** pytest/ruff green; mypy strict on `kg/*.py` (non-vendored); live KB ready;
`docs/kg-plan/HANDOFF.md` written (what exists, ids, gotchas).

---

### Phase 1 — Change request + guided wizard (conversation → Impact → EPIC/Stories → TDD)

**Goal:** from a KB + an uploaded BCR, a guided conversation produces three markdown artifacts,
each editable, each versioned, each grounded in KG retrievals and a deterministic impact table.

**Deliverables**

- `models/change.py`: `ChangeRequest{cr_id, kb_id, owner_id, title, document_text, source_filename,
  bcr_meta: {doc_id, status, requested_by, date_raised, target_workflow} (parsed
  deterministically from the docx text when present), requirements: [{id, text}] (regex
  `BCR-\d+-\d+`), impact_seed_terms: [str] (from BCR §4 mentions + requirement nouns),
  wizard: WizardSession, artifacts: {impact: Artifact, epic: Artifact, stories: Artifact,
  tdd: Artifact}, project_ids: [str] (projects created from this CR), stage, timestamps}`;
  `Artifact{kind, markdown, version, history: [ArtifactVersion{version, markdown, source:
  llm_draft|llm_revision|human_edit, note, at}], status: empty|drafted|approved}`;
  `WizardSession{steps: [WizardStep{kind: impact|epic|stories|tdd, status: pending|asking|drafting|
  drafted|approved, questions: [DialogueQuestion-like{id, text, options, answer, status}], notes:
  [str] (answers folded into the drafting brief), turns: [ChatTurn]}], cursor, provider, model}`.
- `agents/change_analyst.py::ChangeAnalystAgent` (plain class `(llm, prompt_manager)`), methods
  returning pydantic plans:
  - `draft_questions(step, brief) -> DraftedQuestions` — 2–5 clarifying questions with
    suggested options, grounded (prompt gets: BCR text, KG packet(s), the deterministic impact
    table, prior approved artifacts). Reuse `SuggestedOption` from `models/dialogue.py`.
  - `interpret_answer(step, question, answer) -> AnswerNote{note, resolved, followup?}` —
    turns prose into a brief line (one follow-up max, like the dialogue engine).
  - `draft_impact(brief) -> ImpactDraft{markdown, affected: [AffectedItem{kind, id_or_path,
    change_type: modify|add|remove|verify, rationale, kg_ref}], open_decisions:[str]}`
  - `draft_epic_and_stories(brief) -> EpicDraft{epic: EpicDoc{id, title, statement, value[],
    capabilities[], dod[], story_map[], nfrs[], dependencies[], risks[]}, stories:
    [StoryDoc{id, title, points, as_a, i_want, so_that, acceptance[], notes, implements[]}]}`
  - `draft_tdd(brief) -> TddDraft{sections: TddDoc (1..8 mirroring TDD-ORD-001's headings, each
    with `existing` and `changed` text + tables), diagrams_needed[]}` — this is the "existing vs.
    to-be-changed" design (D9 seed).
  - `revise(step, artifact_markdown, instruction) -> Revision{markdown, summary}` — chat turn
    that edits the current draft (used after drafting; the artifact stays markdown).
  Prompts: `prompts/templates/change_{questions,answer,impact,epic_stories,tdd,revise}.md`. IDs
  come from `KgService.catalog` — the engine, not the LLM, assigns EPIC-002 / US-008.. / TDD-ORD-002
  (the model receives them in the brief).
- `change/engine.py::ChangeWizardEngine` (deterministic): `start`, `answer`, `skip`, `draft(step)`
  (assemble brief = BCR + answers + KG retrievals per requirement + `impact()` table + previous
  approved artifacts → call agent → render markdown via `change/render.py` (Jinja md templates
  matching the manager's heading structure) → new `ArtifactVersion`), `revise(step, msg)`,
  `edit(step, markdown)` (human edit = new version, `human_edit`), `approve(step)` (advances the
  cursor). Retrieval strategy: one `retrieve` per BCR requirement + one per §4 component mention,
  deduplicated by node id, capped by budget; the packet's `files` become the "Sources" footer of
  each artifact so grounding is visible.
- `change/render.py` — markdown renderers for Impact / EPIC / US (one section per story) / TDD
  that reproduce the reference headings exactly (see reference digest §5) — the same
  structures feed the docx export in Phase 2. Markdown must **parse back** for the fields we
  need later (story ids/titles/AC, TDD activity table) — write `change/parse.py` with a
  round-trip test (project rule).
- `ProjectCompiler`-style facade `change/service.py::ChangeRequestService(store, kg_service,
  provider_factory)`; `storage/change_store.py` (`<state-root>/change_requests/<cr_id>.json`).
- API: `POST /change-requests` (multipart: `kb_id`, `file` docx/md/txt, `title?`, `provider?`,
  `model?`), `GET /change-requests`, `GET/DELETE /change-requests/{id}`,
  `GET /change-requests/{id}/wizard`, `POST …/wizard/start`, `POST …/wizard/answer {answer,
  option?}`, `POST …/wizard/skip`, `POST …/wizard/draft {step}` → **job** (`JobKind +=
  "cr_draft"`), `POST …/wizard/revise {step, message}` → job, `PUT …/artifacts/{kind}
  {markdown}`, `POST …/artifacts/{kind}/approve`, `GET …/artifacts/{kind}?version=`.
- Frontend: `app/changes/page.tsx` (list + "New change request": pick KB, upload BCR),
  `app/changes/[id]/page.tsx`: left = stepper (Impact → EPIC & Stories → TDD) + chat column
  (questions with `SuggestedAnswers` chips, answer box, "Draft now" when questions are done,
  revise messages after drafting); right = artifact editor/preview (markdown editor reusing
  `SpecEditor` styling, version dropdown, Approve). Sources footer with links to
  `GET /knowledge-bases/{id}/files?path=`.
- CLI: `workflow-compiler cr create <kb-id> <bcr.docx>`, `cr draft <cr-id> <step> [--auto]`
  (`--auto` answers questions with the first suggested option — used for scripted E2E).

**Tests:** engine state machine (start/answer/skip/draft/approve ordering, one follow-up max,
versions append), render→parse round trip for all four artifacts, id assignment from catalog,
API flow with `MockProvider` queued plans, job kind wiring, human edit creates a version.

**Live verification:** create CR from BCR-001 on the Phase-0 KB (Nemotron); run all three
steps in the browser; check the impact table names `order_workflow.py`, `types.py`,
`complete_order`, TC-05/06/09/10, US-003/004/005, TP §3.2, EPIC-001 DoD; EPIC-002 has a story
map; stories have Given/When ACs; the TDD has "Existing" vs "Proposed" per section incl. the
new PARTIALLY_* states, list[ProvisioningResult]/[DispatchResult], group saga. Record in RUNBOOK.

**Exit criteria:** as Phase 0 + the three artifacts for BCR-001 saved as fixtures under
`tests/fixtures/change_artifacts/` (they are Phase 2/3 inputs).

---

### Phase 2 — Document export (.docx / .xlsx in the manager's template style)

**Goal:** every artifact exports to Word/Excel that looks like the reference documents; the
TDD export is what gets "uploaded to the workflow GUI".

**Deliverables**

- `docs_export/docx_writer.py` — a small styled writer over python-docx: 22 pt bold doc-type
  title, 14 pt subtitle, bold `Label: value` metadata block, Heading 1/2, "List Paragraph"
  bullets, tables with `2F5496` header shading + white bold text, `☑  ` / `☐  ` checklists,
  Consolas runs for inline code, en/em dashes preserved. Numbered "N. Title" headings for
  BRD/TDD/TP/BCR-style docs, unnumbered for EPIC, H2-only for stories.
- `docs_export/markdown_to_docx.py` — deterministic converter for our own artifact markdown
  (headings, paragraphs, bullets, pipe tables, `- [ ]`/`- [x]` → ☐/☑, backticks → Consolas).
- `docs_export/xlsx_writer.py` — TC matrix: sheet "Test Cases" (columns `TC ID | Title |
  Preconditions | Steps | Expected Result | Type | Automated | Linked Story/Req | Notes`, header
  styling) + sheet "Summary" (title, Linked TDD/Epic/Automation rows, Totals by Automation
  Status, Totals by Type, Notes). Used by Phase 4 too; in Phase 2 it exports the impact
  analysis' "affected test cases" table as a preview.
- Bundling: `docs_export/bundle.py::export_change_request(cr) -> zip` = `Impact-Analysis-BCR-001.docx`,
  `EPIC-002-<slug>.docx`, `US-00N-<slug>.docx` (one per story), `TDD-ORD-002-<slug>.docx`, plus
  the markdown sources.
- API: `GET /change-requests/{id}/artifacts/{kind}/export?format=docx|md`,
  `GET /change-requests/{id}/export.zip`. Frontend: Export buttons on the wizard page.
- Add `openpyxl` to dependencies (python-docx already present).

**Tests:** golden-structure tests that open the produced docx with python-docx and assert
title/subtitle sizes, heading texts in order, table headers + shading, checklist glyphs; xlsx
sheet names/columns/summary totals; zip manifest. Compare heading sequences against the
reference digest §5 tables (encode them as fixtures).

**Live verification:** export BCR-001's four artifacts, open in Word/Excel side by side with
the originals; screenshot into RUNBOOK.

**Exit criteria:** as before; the exported `TDD-ORD-002-*.docx` saved as
`tests/fixtures/change_artifacts/TDD-ORD-002.docx` and copied to
`examples/change_requests/` for Phase 3.

---

### Phase 3 — KG-grounded workflow project + change spec (the "upload TDD to the GUI" half)

**Goal:** the TDD (docx or md) becomes a workflow project whose spec markdown references the
real modules/activities/tests, plus a `changes.md` change spec (existing vs. proposed per
component) that goes through the same edit ⇄ validate gate.

**Deliverables**

- `CompilationProject += kb_id: str | None, change_request_id: str | None, change_spec:
  ChangeSpec | None`. `models/change_spec.py::ChangeSpec{components: [ComponentChange{name,
  kind: module|activity|workflow|type|signal|query|test|diagram|doc, path (KG node id / file),
  existing: str, proposed: str, change_type: modify|add|remove|verify, requirement_ids: [str],
  provenance}], assumptions, open_questions}` (SpecItem-style, with `Provenance`).
- Grounding: `kg/grounding.py::KgGrounder(kg_service, kb_id)` with `context_for(text, budget)`;
  segmentation / discovery / fact-extraction / temporal-design prompts get an optional
  `{{kg_context}}` block ("Knowledge-graph context — prefer these real names/paths"). Wire via
  `ProjectCompiler.compile_document(..., grounder=None)` and `WorkflowCompiler` agent kwargs
  (no behaviour change when `None`; the existing tests stay untouched).
- Change-spec extraction: `agents/change_spec.py::ChangeSpecAgent.extract(tdd_text, kg_context,
  impact_table) -> ChangeSpec` (prompt `extract_change_spec.md`); rendered to `changes.md` by
  `spec/change_renderer.py`, parsed back by `spec/change_ingest.py` (round-trip identity test),
  validated by `spec/change_validator.py` (findings: component path not found in KB → WARNING
  with suggestions from `KgService.search`; requirement id not in CR → WARNING; empty
  proposed → BLOCKING). Findings flow into `validation_findings["__changes__"]` so the
  Resolve dialogue can ask about them (agenda already reads findings per slug).
- Ingress: `POST /projects/compile-upload` + `/projects/compile` gain `kb_id?`,
  `change_request_id?`; `POST /change-requests/{id}/send-to-workflow {provider?, model?}` = one
  click that compiles the approved TDD markdown with both ids set and links `project_ids`.
  Home page: optional "Ground with knowledge base" selector next to the provider picker.
- Spec tab: `changes.md` shown as another file in `SpecEditor` (with highlighting for the
  existing/proposed grammar), `PUT /projects/{id}/spec` accepts it, findings panel shows its
  findings; project header shows "Grounded by <KB name> · from <CR title>".
- CLI: `compile … --kb <id> --change-request <id>`; spec dir gets `changes.md`.

**Design notes:** the TDD is a design doc, not a process narrative — expect segmentation to
yield one workflow (`OrderWorkflow`) with per-group sub-steps; add a `discover_workflows`
prompt hint that a TDD's §4 state machine / activities table define the steps. If the existing
spec pipeline struggles on the TDD, do **not** fork it — improve the grounding block and the
prompt hint, and record what happened.

**Tests:** grounder no-op when unset; prompts render with/without `kg_context`; change spec
render/parse identity; validator findings; API upload with `kb_id`; send-to-workflow links ids;
existing 583 tests untouched.

**Live verification:** upload the Phase-2 `TDD-ORD-002.docx` via the home page with the KB
selected (and once via "Send to workflow GUI"); check the spec names `capture_order`,
`validate_order`, `provision_order`, `dispatch_order`, `complete_order`, `cancel_order`,
`delivery_confirmed`, `get_status`, states incl. PARTIALLY_*; `changes.md` lists
`shared/types.py`, `workflows/order_workflow.py`, `activities/order_activities.py`,
`tests/test_order_workflow.py`, the three diagrams; validate → resolve → approve completes.

---

### Phase 4 — Post-approval change outputs (diagrams, modified codebase + diff, test docs)

**Goal:** after `approve-spec`, the project produces the three deliverables the manager named,
each grounded in the KB's actual files.

**Deliverables**

- `change_outputs/models.py`: `ChangeOutputs{diagrams: [UpdatedDiagram{name, kind:
  state|sequence|architecture|state-partial, original: str|None, updated: str, notes}],
  code: CodeChangeBundle{files: [ChangedFile{path, status: modified|added|removed|unchanged,
  original, updated, unified_diff, checks: {ast_ok, ruff_ok?}}]}, tests_doc:
  TestDocUpdate{test_cases: [TestCaseRow (xlsx columns)], changed_ids, new_ids, test_plan_addendum_md},
  provenance, timings}` stored on `CompilationProject.change_outputs`.
- Agents (`agents/change_outputs.py`) + prompts:
  - `update_diagrams.md` → `DiagramUpdatePlan` given the original `.mmd` (from KB corpus), the
    approved spec + design + change spec → updated `order-state-machine.mmd`,
    `order-sequence.mmd`, `system-architecture.mmd`, new `order-state-machine-partial-shipment.mmd`.
    Deterministic checks: mermaid header present, every state named in the spec appears,
    balanced `subgraph/end`. Also assemble `system-flow-diagram.md` (numbered H2s like the
    original) and include the per-workflow spec mermaid (D10) as section 4.
  - `rewrite_source_file.md` → per file: given the file's current content, the approved TDD /
    design / change spec, sibling files' new signatures (types first, then activities, then
    workflow, then worker/starter, then tests — ordered so later files see earlier outputs), emit
    the **full updated file**. Post-check with `ast.parse`; on syntax error one repair round.
    Files outside the change spec are copied `unchanged`. `difflib.unified_diff` for the diff.
  - `update_test_cases.md` → new/updated TC rows (TC-18…, ids from catalog) + `test_plan_addendum`
    (TP §3.2 removal of the out-of-scope line, new §4.2 types, new deliverables) — the xlsx and
    updated TP docx are rendered by Phase 2's writers; the updated `tests/test_order_workflow.py`
    comes from the code stage.
- Pipeline: `ProjectCompiler.approve_spec` → when `kb_id` is set, chain a `change_outputs` step
  (job kind `change_outputs`, resumable per sub-stage; each sub-stage persists on completion so
  a timeout keeps earlier outputs). CLI `approve-spec … --change-outputs`.
- API: `GET /projects/{id}/change-outputs`, `GET …/change-outputs/export.zip` (updated
  `docs/diagrams/*`, `src/*`, `tests/*`, `TC-order-workflow.xlsx`, `TP-*.docx`, plus a
  `CHANGES.md` index), `POST …/change-outputs/regenerate {stage}`.
- Frontend (Results tab): a "Change outputs" section — Diagrams (MermaidView per diagram,
  original/updated toggle), Code (file list with status badges, side-by-side or unified diff
  viewer — use `diff` npm package + simple renderer, no heavy editor), Test cases (table with
  new/updated highlighting + download xlsx), Download all.

**Tests:** ordered file rewrite with `MockProvider`; ast/repair loop; diff correctness;
diagram checks; TC id allocation; xlsx round-trip; API + job resumability; export zip contents.

**Live verification (the demo path):** KB → CR wizard → export TDD → upload with KB → gate →
approve → outputs. Check: `types.py` gains `ShipmentGroup`, `PARTIALLY_PROVISIONED/DISPATCHED`,
list results; `order_workflow.py` fans out per group (`asyncio.gather`), per-group compensation,
group cancel signal, `get_status` per group; `test_order_workflow.py` gains split/independent
failure/mixed-cancel tests; TC matrix has new rows + updated TC-05/06/09/10 notes; the
partial-shipment state machine renders. **Run the generated tests** in a scratch venv with
`temporalio` (`WorkflowEnvironment` time-skipping) and record pass/fail honestly.

---

### Phase 5 — Hardening, docs, demo runbook

- Fix the two P0s from the 2026-08-14 audit that this feature widens (id/slug sanitisation at
  every store boundary; zip-slip already covered) and the CAS-on-save for the new stores.
- `docs/HOW_IT_WORKS.md` (new §8c Knowledge bases & change requests, route table additions),
  `docs/architecture.md` (component + sequence diagrams for the new flow), `README.md`
  ("Use — Business change pipeline"), `CLAUDE.md` architecture essentials paragraph, frontend
  `SPEC_GUIDE.md` for `changes.md` grammar.
- `docs/kg-plan/RUNBOOK.md` becomes the end-to-end demo script (bring-up, timings, gotchas), and
  `docs/kg-plan/HANDOFF.md` the final state.
- Optional stretch (only if everything above is green): merge `feat/live-diagram` (clean
  fast-forward) so run highlighting works on the demo branch.

---

## 3. Cross-cutting rules for every phase

- **Provider selection**: every long LLM operation takes `provider`/`model` like `/projects/compile`
  and defaults to `nemotron` for KB/CR work (D6). Never run wave-2 enrichment or file rewrites
  through the local gateway by default.
- **Jobs**: long work is a `JobKind` with progress; cancel persists nothing; sub-stages persist
  on completion (Phase 4).
- **Grounding is visible**: every artifact/spec/output carries a "Sources" list of KB files +
  line spans it was grounded on; low `coverage` from retrieval is surfaced as a warning, not hidden.
- **Deterministic where possible**: id numbering, impact traversal, markdown↔model round trips,
  docx/xlsx rendering, diff generation, ast checks. The LLM drafts; code decides.
- **Testing**: offline `MockProvider` for everything; fixtures under `tests/fixtures/{kb_mini,
  change_artifacts}`; live runs are recorded, not asserted.
- **Handoff discipline**: end each phase by updating `docs/kg-plan/HANDOFF.md` (what exists,
  ids/paths, open issues, exact commands) and committing on `feat/kg-change-pipeline`.
- **Memory**: save non-obvious lessons to Claude memory (provider quirks, timings, prompt fixes).

## 4. Known risks and how the plan absorbs them

| Risk | Mitigation |
|---|---|
| BM25 keyword retrieval misses paraphrases | multi-seed retrieval per requirement + component names; `coverage` warning; KG search box in UI to inspect |
| Nemotron truncates long full-file rewrites | file-by-file generation with sibling signatures, ast check + one repair round, `--timeout ≥ 400`; cloud default |
| The spec pipeline is tuned for process narratives, not TDDs | KG grounding block + discovery hint; change spec carries the code-level deltas the WorkflowSpec cannot |
| docx fidelity vs. the manager's templates | golden-structure tests encoded from the reference digest §5; visual check in RUNBOOK |
| Vendored code drifts / mypy strict | pinned SHA + VENDORED.md; strict excluded only for the vendored subpackage |
| Path traversal / zip-slip via new uploads | id regex at store boundaries; safe extraction with caps |
| Windows path separators in node ids | normalised to POSIX in the vendored ingest |
| Reference corpus mismatch (`src.*` imports vs `existing_Codebase/`) | keep the corpus verbatim; the code rewrite stage preserves the corpus's own import style; document the mismatch in the impact analysis |
