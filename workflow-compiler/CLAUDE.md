# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`workflow-compiler` compiles free-form business workflow documents (`.docx/.pdf/.md/.html/.txt`)
into canonical artifacts — metadata, facts, a deterministic graph, a Mermaid diagram, a structural
review report, a CVPA classification, a Temporal design, and runnable Temporal Python code — through
a staged pipeline with a human approval gate in the middle.

`README.md` is a lean overview + install/quickstart guide. `docs/HOW_IT_WORKS.md` is the
authoritative reference for CLI flags (§9.2), the HTTP API (§9.3), and the full design;
`docs/architecture.md` holds the component/sequence diagrams. Keep all three in sync when
behavior changes (the working tree shows they are updated alongside code).

## Commands

```bash
pip install -e ".[dev]"        # contributor install: editable + test/lint tooling
pip install .                  # user install (README §Install) — no -e, no extras
workflow-compiler init --provider mock --yes   # write .env without prompting

pytest                          # full suite (unit + integration), no network needed
pytest tests/test_compiler.py   # single file
pytest -k review_pipeline       # single test / pattern
pytest tests/test_integration.py  # full pipeline against the deterministic mock provider

ruff check src tests            # lint (line-length 100, py312)
mypy src                        # strict type-check (pydantic plugin enabled)

python -m uvicorn workflow_compiler.api.app:app --reload   # run the HTTP API (/docs for interactive)
workflow-compiler compile examples/order_workflow.md --spec-dir ./specs --provider mock   # run CLI offline, no API key
```

Tests run fully offline via a `MockProvider`; no `NVIDIA_API_KEY` is required for `pytest` or any
`--provider mock` invocation. LLM-backed CLI commands (`compile`, `validate`, `approve-spec`,
`approve`) need either `NVIDIA_API_KEY` in `.env` or `--provider mock`.

## Architecture essentials

These are the load-bearing facts that span multiple files — read `docs/architecture.md` for the full
picture before changing pipeline behavior.

- **`WorkflowState` (`models/state.py`) is the single aggregate** threaded through every stage. Each
  stage populates exactly one field and advances `state.stage`. `WorkflowCompiler` (`compiler.py`)
  orchestrates the whole sequence and is the only place that knows the stage order.

- **Everything is swappable behind an abstract interface** (`interfaces/`): `BaseLLMProvider`,
  `StateStore`, `ReviewManager`, `BaseParser`, `BaseAgent`. Agents depend only on `BaseLLMProvider`
  — **no vendor SDK is ever imported** into agent or compiler code. Construct the wired-up compiler
  with `WorkflowCompiler.from_settings()`, or inject mocks (`MockProvider` + `InMemoryStateStore`)
  directly for tests.

- **The LLM specifies; deterministic code emits.** LLM-backed stages: discovery, fact extraction,
  CVPA, Temporal *design*. Deterministic (no LLM, pure functions of their input — reproducible and
  testable without a model): graph building, Mermaid rendering, structural review, and **Temporal
  code generation** (`codegen/temporal`, Jinja2). The Temporal *design* model is specification-only
  (names/params/policies, never code); runnable code is a separate deterministic render of the
  approved design. Preserve this split — do not make a "deterministic" stage call the LLM, and do
  not make the design model carry code.

- **Relational fact extraction guards against hallucination.** `FactExtractionAgent` emits flat
  `WorkflowFacts` plus an optional id-linked `WorkflowStructure`. `WorkflowStructure.validated()`
  enforces referential integrity (relations pointing at undeclared ids are dropped) — when a
  structure is present `GraphBuilderAgent` wires the graph *semantically* (`build_from_structure`)
  rather than positionally. This is what stops decisions/events/compensations from being
  mis-attributed. Any new patch/merge logic must re-run `validated()` afterward.

- **The sequential review pipeline wraps the discovery + facts stages** (and segmentation),
  selected per-stage by the compiler with precedence **review → plain**. Default ON (`--review`):
  one canonical output, then three sequential passes (completeness → grounding → consistency)
  emitting **minimal deterministic patches or `no_change`**, never a rewrite. A pure `PatchApplier`
  folds them in and drops ungrounded/duplicate additions, making passes idempotent. Engine in
  `agents/review_pipeline.py`; patch vocabulary in `models/patch.py`; prompts in
  `prompts/templates/review_*.md`. It is adapter-shaped (`ReviewSpec`) so adding a stage means
  adding a spec, not engine code. It never certifies truth — the **human spec gate stays the
  oracle**, and provenance is recorded in `confidence_scores.notes`.

- **Human-in-the-loop gate.** CVPA and Temporal artifacts are produced only after a graph is
  approved (`approve_graph`); `reject` halts the pipeline. Graph edits go through `GraphEditor`
  (`review/editor.py`), which returns **new validated immutable `WorkflowGraph` instances** and
  raises on invalid edits rather than corrupting state.

- **The spec-centric front-end (`ProjectCompiler`, `project_compiler.py`) is the user-facing
  pipeline** (a single-workflow document yields one segment holding the full text, so it covers
  that case too), layered on top of the per-workflow engine: segmentation
  (`agents/segmentation.py`) discovers every workflow + output→input cross-references, facts are
  extracted per segment, and the human gate moves to **editable spec Markdown files**
  (`compile --spec-dir` → edit → `validate` → `approve-spec`). The structured `WorkflowSpec`
  (`models/spec.py`) is the source of truth — `spec/renderer.py` projects it to Markdown and
  `spec/ingest.py` parses edits back **deterministically** (round-trip identity is tested; never
  re-extract a spec with an LLM). Provenance (`document_grounded`/`llm_inferred`/`human_provided`)
  governs the spec validator (`spec/validator.py`): human-provided elements are flagged, never
  removed. At approval the graph gate is automatic (`compile_prepared` with
  `graph_health_threshold`, default 0.9); the classic `approve` stays as the manual override, and
  the readiness checklist is absorbed into the spec's Open Questions section.

- **Edit requests change compiled workflows through the same gate.** `edit_specs`
  (`project_compiler.py`) applies a structured edit-request document (format:
  `docs/EDIT_FORMAT_GUIDE.md`): `spec/edit_ingest.py` parses the skeleton deterministically and
  fails fast before any LLM call; `agents/edit_interpreter.py` translates the NL entries into an
  `EditPlan` (`models/edit.py` — `Patch`es + typed trigger/xref ops); `spec/edit_applier.py`
  applies them via `SpecPatchApplier(human_authority=True)` (adds skip grounding and become
  `human_provided`; removals are honored, dangling refs pruned by `validated()`). Edits are
  **atomic** (deep copy, all-or-nothing; a fatal dropped patch aborts with the dropped ops named,
  while an add whose value already exists is skipped as satisfied with a summary line), append an
  `EditRecord` to `project.edit_log`, bump the
  spec version, and reset the project to `SPEC_DRAFTED` — validate/approve must re-run. Never
  weaken the default (review-mode) applier to serve the edit path; the two modes are deliberate.
  Split/merge syntax is reserved (parser rejects it) for a future phase. Generated code defaults
  under `./generated/<project-id>/<slug>/`.
  **Preview → confirm:** `preview_edit` dry-runs the pipeline (persists nothing) and returns a
  `ResolvedEdit` blob (plans + drafted specs + timings + a fingerprint over project state +
  document); `edit_specs(resolved=...)` replays it with **zero LLM calls** — a stale fingerprint
  raises `EditPreviewStaleError` (HTTP 409). Confirm must never re-interpret; the whole point is
  that what applies is exactly what was previewed. CLI: `edit --dry-run`.

- **Conversational spec resolution is a second door to the same gate.** `dialogue/engine.py`
  turns the validator's **blocking + warning** findings (never INFO) plus each spec's unresolved
  `open_questions` into plain-language questions (`agents/dialogue.py` may **group** related ones
  and ask **one** clarifying follow-up), and translates prose answers into `Patch`es applied
  through the same `EditPatchApplier` the edit path uses — so answers inherit human authority and
  `HUMAN_PROVIDED` provenance. Three rules are load-bearing: answers apply **incrementally** (one
  patch set + one patch-version bump per answered question, so abandoning a session keeps what was
  already answered); the agenda is a **snapshot** taken at `start`, so parking a question cannot
  grow it and sessions always terminate; and an answer that cannot be mapped is **parked** as a new
  open question, never discarded and never fatal (contrast the edit path, which is atomic and
  aborts). `validation_findings` is deliberately kept during a session — it is the agenda's source —
  and cleared by `finish()` only for the specs that actually changed, which is what forces a
  re-validate. Session state lives on `CompilationProject.dialogue_session`; the API is
  `GET/POST/DELETE /projects/{id}/dialogue` plus `/dialogue/answer`, `/dialogue/skip` and
  `/dialogue/prepare`, and the UI is the project page's **Resolve** tab.
  Two refinements sit on top, both about the *drafting* half. **Suggested answers**: a question
  may carry 2–4 candidate answers grounded in the spec; picking one *fills the answer box rather
  than sending it*, and its text is then interpreted through the same path as typed prose —
  there is deliberately **no** stored patch per option, so there is one apply path and nothing
  that can go stale. `chosen_option` records what the user accepted rather than authored, since
  the suggestions come from the model while the result is `HUMAN_PROVIDED` either way.
  **Pre-drafting**: `DialogueEngine.prepare()` runs the same per-spec drafting without opening a
  session, chained off a successful `validate` job as a `predraft` job (a *speculative* job kind
  — exempt from one-run-per-project and auto-cancelled by real work, so it can never 409 a
  user's click); `start()` then consumes the result when `dialogue/agenda.py::agenda_fingerprint`
  still matches, and drafts live when it does not. Two more load-bearing rules: only a
  **completed** draft is persisted (an interrupted one leaves nothing and simply re-runs — that
  is the whole crash-recovery story), and `ProjectCompiler.prepare_dialogue` **re-loads the
  project and re-checks the fingerprint before saving**, because drafting takes minutes and the
  chat or a hand edit can move the specs underneath it. Gated by `predraft_questions`
  (`off`/`cloud`/`always`, default `cloud`), which excludes the local gateway on purpose —
  it is one GPU with no queueing.
  Answers also carry `xref_ops`, because a **cross-workflow dependency belongs to the project
  rather than to a spec** and so cannot be a `Patch`. An unconfirmed dependency is a hard stop
  at approval (`approve_spec` raises), so `_validate_triggers_and_dependencies` raises a
  WARNING for one — attributed to `source_workflow`, hence asked once — and the answer
  confirms/corrects/removes it through `spec/wiring.py::apply_xref_op`, shared with the edit
  path. A dependency op that cannot be applied is reported and skipped, never raised; if an
  answer's every op is dropped it parks rather than reporting a change it did not make.

- **Knowledge bases ground the change pipeline (`kg/`).** A zipped corpus becomes a Context Hub
  graph via the vendored subset `kg/contexthub/` (pinned SHA + local edits in its `VENDORED.md`;
  excluded from `mypy --strict`; never imported outside `workflow_compiler.kg`). Everything goes
  through `kg/service.py::KgService`: `create_from_zip` (safe extraction, `kg/ingest.py`) →
  `index` (static ingest, optional LLM enrichment through the app's `BaseLLMProvider` via
  `kg/llm_bridge.py`, run in a worker thread; stats + business-id `catalog` recorded) →
  `retrieve` (BM25 → traversal → file spans, a `KgPacket` with `coverage`), `impact`
  (deterministic BFS), `search`, `read_file`. Node ids are corpus-relative POSIX
  (`mod:existing_Codebase/workflows/order_workflow.py`); store ids are validated at the boundary.
  Indexing is a `kb_ingest` job — `JobManager` is keyed by `scope_id`+`scope_kind`
  (`project` | `knowledge_base`), `project_id` remains an alias. KB routes take `provider`/`model`
  per request with a **cloud default** (enrichment must never hit the single-GPU gateway unasked).
  Phase plan + handoff: `docs/kg-plan/`.

- **Change requests ride on knowledge bases (`change/`).** `ChangeRequestService` (façade like
  `ProjectCompiler`) + `ChangeWizardEngine` (deterministic state machine: Impact → EPIC → Stories
  → TDD; per step questions → answers → draft → revise/edit → approve) + `ChangeAnalystAgent`
  (`prompts/templates/change_*.md`, permissive plans). Three rules are load-bearing: the
  **engine assigns ids** (`change/ids.py` from `KgService.catalog`, incl. `catalog.documents`),
  never the model; every artifact is markdown that **renders and parses back**
  (`change/render.py` ⇄ `change/parse.py`, round-trip tested — human edits/revisions that lose the
  title heading are rejected); grounding is visible (each draft's brief = BCR + answers + KG
  retrievals + `impact()` table + prior artifacts, and the KB files/spans it used become the
  artifact's `## Sources` footer). Long calls are `cr_questions`/`cr_draft`/`cr_revise` jobs
  (scope kind `change_request`); `answer` is synchronous. Store: `storage/change_store.py`.

- **Document export is a deterministic projection (`docs_export/`).** Word/Excel files are
  rendered from the *parsed* artifacts (`change/parse.py` docs — never re-parse markdown ad hoc)
  by `docx_writer.py` / `xlsx_writer.py` / `artifacts.py` / `bundle.py` in the manager's
  reference style (research digest §5; golden-structure tests encode it in
  `tests/fixtures/change_artifacts/reference_headings.json`). No model call, and identical input
  → identical bytes (`package.py` pins OOXML timestamps). Exports always state what they are
  (`Approved vN` / `DRAFT vN — not approved`, `-DRAFT` filename suffix); the stories docx export is
  a zip with one document per story; the TC preview merges the KB's original matrix rows when
  present (`KgService.read_bytes`) and degrades to impact-only rows otherwise. Routes
  `GET …/artifacts/{kind}/export?format=docx|md|xlsx`, `GET …/export.zip`; CLI `cr export`.

- **HTTP auth + time-saved metric.** The API uses local accounts (`api/auth.py`: scrypt +
  HMAC-signed session cookie, users under `<state-root>/users/`); project routes require
  `get_current_user`, projects carry `owner_id` (recorded for attribution). By default
  (`projects_shared`) every signed-in user sees and opens every project; set
  `WORKFLOW_COMPILER_PROJECTS_SHARED=false` to restore per-owner isolation (other accounts'
  projects 404; `None` = legacy, always visible). `author`/`reviewer` default to the signed-in
  user. The CLI intentionally
  bypasses auth. `ProjectCompiler` records per-step wall-clock seconds into
  `project.stage_timings`; `metrics.py::compute_time_saved` (pure, no LLM) compares them to the
  `baseline_hours` **estimates** for `ProjectResponse.time_saved` and
  `GET /metrics/summary` — never claim savings for unmeasured projects. Each user can override
  those baselines for their own view via `User.preferences.baseline_hours` (edited on the
  Settings page / `PUT /auth/me`); the two call sites merge the user's overrides over the config
  default (`app.py::_effective_baselines`), so `compute_time_saved` itself is untouched — it still
  just takes a baseline dict. `User.preferences` (a `UserPreferences` submodel, default-valued so
  legacy user JSON keeps loading) also carries `projects_page_size`. Projects have an optional
  `nickname`; `GET /projects` returns lightweight summaries (nickname/stage/count/updated) and
  `PATCH /projects/{id}` renames without recompiling.

## Conventions

- Pydantic v2 models everywhere; Python 3.12+; `mypy --strict` must pass (the pydantic mypy plugin
  is enabled). Prompts are Markdown templates under `prompts/templates/` loaded via `PromptManager`
  — change prompt text there, not inline in agents.
- Config is via `pydantic-settings` (`config.py`) reading `WORKFLOW_COMPILER_*` env vars / `.env`.
  State persists as JSON under `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`).
- `generated/` holds example output bundles; `examples/` holds sample input documents.
