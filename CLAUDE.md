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
workflow-compiler compile examples/order_workflow.md --provider mock   # run CLI offline, no API key
```

Tests run fully offline via a `MockProvider`; no `NVIDIA_API_KEY` is required for `pytest` or any
`--provider mock` invocation. LLM-backed CLI commands (`compile`, `approve`, `inspect`) need either
`NVIDIA_API_KEY` in `.env` or `--provider mock`.

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

- **Two optional quality levers wrap the discovery + facts stages**, selected per-stage by the
  compiler with precedence **ensemble → review → plain**:
  - *Sequential review pipeline* (default ON, `--review`): one canonical output, then three
    sequential passes (completeness → grounding → consistency) emitting **minimal deterministic
    patches or `no_change`**, never a rewrite. A pure `PatchApplier` folds them in and drops
    ungrounded/duplicate additions, making passes idempotent. Engine in `agents/review_pipeline.py`;
    patch vocabulary in `models/patch.py`; prompts in `prompts/templates/review_*.md`.
  - *Consensus-merge ensemble* (opt-in OFF, `--ensemble`): N temperature-diversified candidates run
    concurrently and merged by reference-free signals (votes + referential integrity + grounding).
    Lives in `agents/ensemble.py`, `agents/ensemble_merge.py`, `llm/ensemble_provider.py`.

  Both are adapter-shaped (`ReviewSpec` / `StageSpec`) so adding a stage means adding a spec, not
  engine code. Neither certifies truth — the **human approval gate stays the oracle**, and
  provenance is recorded in `confidence_scores.notes`.

- **Human-in-the-loop gate.** CVPA and Temporal artifacts are produced only after a graph is
  approved (`approve_graph`); `reject` halts the pipeline. Graph edits go through `GraphEditor`
  (`review/editor.py`), which returns **new validated immutable `WorkflowGraph` instances** and
  raises on invalid edits rather than corrupting state.

- **Spec-centric front-end (`ProjectCompiler`, `project_compiler.py`)** layers on top of the
  unchanged per-workflow pipeline for multi-workflow documents: segmentation
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

## Conventions

- Pydantic v2 models everywhere; Python 3.12+; `mypy --strict` must pass (the pydantic mypy plugin
  is enabled). Prompts are Markdown templates under `prompts/templates/` loaded via `PromptManager`
  — change prompt text there, not inline in agents.
- Config is via `pydantic-settings` (`config.py`) reading `WORKFLOW_COMPILER_*` env vars / `.env`.
  State persists as JSON under `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`).
- `generated/` holds example output bundles; `examples/` holds sample input documents.
