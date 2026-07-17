# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`workflow-compiler` compiles free-form business workflow documents (`.docx/.pdf/.md/.html/.txt`)
into canonical artifacts — metadata, facts, a deterministic graph, a Mermaid diagram, a structural
review report, a CVPA classification, a Temporal design, and runnable Temporal Python code — through
a staged pipeline with a human approval gate in the middle.

`README.md` is the authoritative reference for CLI flags and the HTTP API. `docs/architecture.md`
and `docs/HOW_IT_WORKS.md` are the authoritative references for design; keep all three in sync when
behavior changes (the working tree shows they are updated alongside code).

## Commands

```bash
pip install -e ".[dev]"        # install package + dev tooling, exposes `workflow-compiler` script

pytest                          # full suite (unit + integration), no network needed
pytest tests/test_compiler.py   # single file
pytest -k review_pipeline       # single test / pattern
pytest tests/test_integration.py  # full pipeline against the deterministic mock provider

ruff check src tests            # lint (line-length 100, py312)
mypy src                        # strict type-check (pydantic plugin enabled)

uvicorn workflow_compiler.api.app:app --reload   # run the HTTP API (/docs for interactive)
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

- **HTTP auth + time-saved metric.** The API uses local accounts (`api/auth.py`: scrypt +
  HMAC-signed session cookie, users under `<state-root>/users/`); project routes require
  `get_current_user`, projects carry `owner_id` (recorded for attribution). By default
  (`projects_shared`) every signed-in user sees and opens every project; set
  `WORKFLOW_COMPILER_PROJECTS_SHARED=false` to restore per-owner isolation (other accounts'
  projects 404; `None` = legacy, always visible). `author`/`reviewer` default to the signed-in
  user. The CLI intentionally
  bypasses auth. `ProjectCompiler` records per-step wall-clock seconds into
  `project.stage_timings`; `metrics.py::compute_time_saved` (pure, no LLM) compares them to the
  `baseline_hours` config **estimates** for `ProjectResponse.time_saved` and
  `GET /metrics/summary` — never claim savings for unmeasured projects.

## Conventions

- Pydantic v2 models everywhere; Python 3.12+; `mypy --strict` must pass (the pydantic mypy plugin
  is enabled). Prompts are Markdown templates under `prompts/templates/` loaded via `PromptManager`
  — change prompt text there, not inline in agents.
- Config is via `pydantic-settings` (`config.py`) reading `WORKFLOW_COMPILER_*` env vars / `.env`.
  State persists as JSON under `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`).
- `generated/` holds example output bundles; `examples/` holds sample input documents.
