# workflow-compiler

Compile free-form **business workflow documents** into structured, canonical artifacts through a
deterministic, reviewable pipeline.

Given a `.docx`, `.pdf`, `.md`, `.html`, or `.txt` description of a business process (one workflow
or many), `workflow-compiler` produces:

- **Editable workflow specifications** — one human-reviewed spec Markdown file per workflow,
  holding metadata, facts (activities, decisions, exceptions, compensations, events, …),
  assumptions, ambiguities, open questions, cross-workflow dependencies, and triggers.
- **Canonical workflow graph** — a normalized directed graph (NetworkX-backed), built
  **deterministically** from the approved spec (no LLM).
- **Mermaid diagram** — a renderable diagram of the graph (CVPA-colored after classification).
- **Review report** — structural health check (orphans, dead-ends, unreachable nodes, missing
  branches, unintended cycles, …) with a health score.
- **CVPA classification** — every node mapped to exactly one **Capture / Validate / Process /
  Activate** phase, with rationale and confidence.
- **Temporal design** — an architecture-only Temporal blueprint (workflow definition, activities,
  signals, queries, child workflows, timers, retries, compensation activities).
- **Runnable Temporal Python code** — a standalone bundle per workflow, rendered
  deterministically from the approved design.
- **Confidence scores** — per-stage and overall.

The human-in-the-loop gate is the **spec**: you edit the spec files and validate them as many
times as you like; code is only generated from what you approved.

## Pipeline

```
Document ─▶ Segmentation (every workflow + its sections) ─▶ per-workflow Fact Extraction
         ─▶ one editable spec .md file per workflow      [HUMAN GATE: edit ⇄ validate]
         ─▶ approve-spec ─▶ per workflow: Graph (auto-review ≥ health threshold)
                            ─▶ CVPA ─▶ Temporal Design ─▶ Temporal Code
```

A document that describes a **single** workflow yields one segment holding the full document
text, so single-workflow documents flow through the same pipeline unchanged.

The structured spec model is the source of truth; the Markdown files are a deterministic
projection of it. Your edits are parsed back deterministically (no re-extraction), recorded with
provenance (`document-grounded` / `inferred` / `human-provided`), and re-checked for referential
integrity. The graph gate is automatic: a workflow whose graph review health score meets
`WORKFLOW_COMPILER_GRAPH_HEALTH_THRESHOLD` (default `0.9`) proceeds straight to code; below it,
the workflow halts for manual review (`approve` / `reject` are the manual override).

The readiness checklist (single explicit trigger, declared inputs, both branches on every
decision, bound compensations, …) is applied during fact extraction and surfaced as each spec's
**Open Questions** section — answer the questions in the spec file itself. Unanswered *required*
questions block `approve-spec` (override with `--accept-incomplete`).

See [`docs/architecture.md`](docs/architecture.md) for component and sequence diagrams and
[`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) for the full design.

## Stack

Python 3.12+ · Pydantic v2 · FastAPI · Typer · NetworkX · Loguru · Rich · Pytest

The LLM layer is **provider-agnostic**. The default provider (`local-fallback`) uses a **local
eGPU gateway** as the primary LLM and transparently falls back to **NVIDIA-hosted Nemotron** when
the box is unreachable or errors; both speak an OpenAI-compatible REST API. Any provider can be
registered without touching agent or compiler code. A `mock` provider ships for offline/testing use.

The local box is an "LLM API Gateway" that uses **email+password session auth** (not a static API
key) and serves several models; `workflow-compiler models` lists them and the frontend offers a
model picker.

## Install

```bash
pip install -e ".[dev]"
```

This installs the package and the `workflow-compiler` console script.

## Configure

Copy `.env.example` to `.env` and configure the LLM (only needed for the LLM-backed stages —
segmentation, discovery, fact extraction, spec validation, CVPA, Temporal design):

```dotenv
# Local eGPU gateway (primary). Session auth — register at the gateway's /ui/.
LLM_API_BASE=http://192.168.1.184:8080/v1
LLM_GATEWAY_EMAIL=you@example.com
LLM_GATEWAY_PASSWORD=your-password
# LLM_MODEL=gpt-oss-120b            # optional; else the gateway's default / UI pick

# NVIDIA-hosted Nemotron (automatic fallback when the eGPU is unreachable).
NVIDIA_API_KEY=nvapi-xxxxxxxx

WORKFLOW_COMPILER_LLM_PROVIDER=local-fallback
WORKFLOW_COMPILER_LLM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
WORKFLOW_COMPILER_STATE_STORE_PATH=.workflow_state
WORKFLOW_COMPILER_GRAPH_HEALTH_THRESHOLD=0.9
```

Set `WORKFLOW_COMPILER_LLM_PROVIDER=nemotron` (or pass `--provider nemotron`) to skip the eGPU
entirely, or `--provider mock` to run fully offline.

State is persisted as JSON under `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`).

## Use — CLI

`compile`, `validate`, `approve-spec`, and `approve` use the LLM (set the local gateway or
`NVIDIA_API_KEY`, or pass `--provider mock` — the mock answers every stage with a scripted demo
workflow, so every command runs offline); `reject` and `show` need no LLM. `models` lists the
models the local eGPU gateway exposes (`workflow-compiler models`). `--version` prints the
version, and `workflow-compiler <command> --help` is always the authoritative reference.

For the local gateway, `--model ID` selects the **local** model (discover ids with
`workflow-compiler models`); `--provider nemotron` bypasses the eGPU and uses the hosted API.

### `compile <document>` — segment into editable specs, stop at the spec gate

Discovers **every** workflow in the document, extracts facts per workflow (with the sequential
review pipeline), and writes one editable spec file per workflow plus an `overview.md` to
`--spec-dir`:

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` | from `.env` | Override the LLM provider (e.g. `mock`). |
| `--model ID` | from `.env` | Override the model id. |
| `--timeout SECONDS` | `120` | Per-request timeout. |
| `--persist` / `--no-persist` | persist | Whether to save the resulting project to the store. |
| `--review` / `--no-review` | review | Sequential review passes (completeness → grounding → consistency) over the LLM stages. |
| `--spec-dir DIR` | `./specs` | Where to write the spec files. |

```bash
workflow-compiler compile big_business_doc.docx --spec-dir ./specs
# → specs/overview.md, specs/customer-onboarding.md, specs/account-provisioning.md, ...
workflow-compiler compile examples/order_workflow.md --provider mock   # offline, no API key
```

Each spec file contains the workflow's metadata, activities/decisions/exceptions/compensations
(with stable `[ids]`), plus **Assumptions**, **Ambiguities**, **Open Questions** (the readiness
checklist rendered as fill-in questions), **Cross-Workflow Dependencies** (output→input links
you confirm by ticking their checkbox), and **Triggers** (executable cross-workflow starts).
Edit the files in any editor — keep the `[id]` markers on lines you modify; new lines you add
are recorded as *human-provided*.

A **Triggers** entry says this workflow *starts* another (always standalone) workflow:

```markdown
## Triggers
- [x] triggers `account-provisioning` (blocking) when `application approved`
  result: provisioning_result
  input customer_record_id: step output `a2` (str)
```

The mode is `blocking` (the caller awaits the target's result, bound to the `result:` name) or
`fire-and-forget`; the optional ``when `…` `` predicate makes the trigger conditional (LLM-drafted
— review it and tick the checkbox to confirm); each indented `input` line maps one field of the
target's typed input from your workflow's input, an earlier step's output, or a constant.

### `validate <project-id>` — fold edits back in and re-check the specs

```bash
workflow-compiler validate <project-id> --spec-dir ./specs
```

Deterministically parses your edits back onto the structured spec, then runs three LLM review
passes against the original document (completeness / grounding / consistency) plus a
**deterministic cross-workflow integrity pass** over every trigger and dependency. Machine-
extracted statements without support are removed; **your** additions are only ever *flagged* for
confirmation, never deleted. The files are re-written with the fixes and findings. Iterate
edit ⇄ validate until you are satisfied.

Findings are two-tier and printed with precise refs (`TAG slug Section > field: message`):

- `BLOCK` (red) — structural breakage that prevents generation: a trigger targeting a workflow
  not in the project, an input map naming a field the target does not declare, an unisolated
  document segment, unmet required checklist items. **`validate` exits non-zero while any
  blocking finding remains**, and `approve-spec` refuses (override with `--accept-incomplete`).
- `WARN` (yellow) — should be confirmed but doesn't block: type mismatches on a hand-off,
  unconfirmed trigger predicates, a blocking trigger with no result binding.

### `approve-spec <project-id>` — compile every workflow through to code

```bash
workflow-compiler approve-spec <project-id> --spec-dir ./specs --out-dir ./generated
```

Approves the specs and runs each workflow **independently** through graph building, structural
review, CVPA, Temporal design, and code generation. The graph gate is automatic: health ≥ the
configured threshold continues; below it the workflow is left pending (`approve <workflow-id>`
remains the manual override). Unanswered required questions block a workflow unless you pass
`--accept-incomplete`; unconfirmed dependencies block approval unless you pass
`--allow-unconfirmed`. Each completed workflow's runnable Temporal bundle is written under
`--out-dir`.

**Every workflow generates as a standalone Temporal workflow** — its own `workflow.py`,
`activities.py`, `shared.py`, `worker.py`, `starter.py`, and a `test_stepthrough.py` local
harness. Confirmed triggers additionally generate a `triggers.py` in the *source* workflow's
bundle: activities that start the target by workflow-type name on the target's own task queue
(`id_conflict_policy=USE_EXISTING` keeps retries idempotent; blocking triggers await
`handle.result()`). The target's bundle is untouched — it always runs independently. Multi-
workflow projects also get a top-level `contracts.py` (every workflow's typed input) and a
project `README.md` documenting the trigger topology and task queues.

Every generated workflow exposes **read-only debug queries** (`current_step`,
`decisions_taken`, `triggers_fired`) — safe in production. Opt into interactive step-through
with `WORKFLOW_COMPILER_STEPWISE=1`: each top-level step then waits for an `advance` signal.
The generated `test_stepthrough.py` runs the bundle under a time-skipping test environment
with the stub activities (triggers mocked) and prints those queries — the quickest way to see
which branch a conditional actually takes.

### `approve <workflow_id>` — manual override for a below-threshold graph

When a workflow's graph health lands below the auto-approve threshold at `approve-spec`, it is
left pending. Inspect it (`show`), then approve it manually to produce CVPA + Temporal design +
code:

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | Reviewer identity recorded on the approval. |
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | Same LLM overrides as `compile`. |
| `--out PATH` | — | Write the CVPA-colored Mermaid diagram to a file. |
| `--out-dir DIR` | — | Write the generated Temporal Python code bundle to a directory. |

```bash
workflow-compiler approve <workflow_id> --reviewer alice --out workflow.mmd --out-dir ./generated
```

### `reject <workflow_id>` — halt a pending workflow (no LLM)

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | Reviewer identity. |
| `--reason TEXT` | — | Why the graph was rejected (recorded in the report). |

```bash
workflow-compiler reject <workflow_id> --reason "missing cancellation branch"
```

### `show <workflow_id>` — display a stored workflow (no LLM, no flags)

```bash
workflow-compiler show <workflow_id>
```

### Sequential review pipeline (default-on)

The **default** quality lever on the LLM stages (segmentation, discovery, fact extraction).
Rather than trusting a single sample, it follows a compiler discipline: **generate one canonical
output, then improve it with three sequential review passes** — *completeness* (add elements
explicitly in the document but missing), *grounding* (remove/flag elements not supported by the
document), and *consistency* (merge duplicates, rename to a canonical label, fix relations). Each
pass emits **minimal deterministic patches or `no_change`** (never a rewrite), and a pure applier
folds them in — dropping any addition that duplicates an existing element or isn't grounded in
the document, which makes the passes **idempotent**. It raises grounding/consistency, not
certified truth (the spec gate stays the oracle). See
[§7.10 of `docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md). On by default; toggle with `--review` /
`--no-review` or via `.env`:

```dotenv
WORKFLOW_COMPILER_REVIEW_ENABLED=true                  # default; --no-review overrides to off
WORKFLOW_COMPILER_REVIEW_STAGES=["discovery","facts"]  # which per-workflow stages get the review pipeline
```

### Windows console note

The progress/table output contains Unicode (e.g. `→`). On a legacy `cp1252` console this raises
`UnicodeEncodeError`. Run with UTF-8 mode: `set PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8=1`).
This is a console-rendering issue only — it does not affect the generated code. Nemotron's
reasoning models can also be slow; bump `--timeout` (e.g. `300.0`) to avoid
`ProviderTimeoutError` on a slow request.

## Use — HTTP API

```bash
uvicorn workflow_compiler.api.app:app --reload
```

Project endpoints (the compile → validate → approve pipeline; spec files travel as
`spec_markdown: {slug: markdown}`):

| Method | Path                        | Body                                        | Purpose                                        |
|--------|-----------------------------|---------------------------------------------|------------------------------------------------|
| POST   | `/projects/compile`         | `{document_text, persist?, model?}`         | Segment into per-workflow specs (spec gate). `model` picks a local gateway model. |
| GET    | `/projects`                 | —                                           | List stored project ids.                        |
| GET    | `/projects/{id}`            | —                                           | Load a project + rendered spec files.           |
| PUT    | `/projects/{id}/spec`       | `{spec_markdown}`                           | Fold edited spec Markdown back in (no LLM).     |
| POST   | `/projects/{id}/validate`   | `{spec_markdown?}`                          | Ingest edits + run the spec validator passes.   |
| POST   | `/projects/{id}/approve`    | `{workflows?, reviewer?, spec_markdown?, accept_incomplete?, allow_unconfirmed_references?}` | Approve specs, compile every workflow. |

Per-workflow endpoints (viewing plus the manual override for below-threshold graphs):

| Method | Path                | Body / Params                              | Purpose                                   |
|--------|---------------------|--------------------------------------------|-------------------------------------------|
| POST   | `/approve`          | `{workflow_id, reviewer?}`                 | Approve → run CVPA + Temporal.            |
| POST   | `/reject`           | `{workflow_id, reviewer?, reason?}`        | Reject a graph.                           |
| GET    | `/workflow/{id}`    | —                                          | Load a stored workflow state.             |
| GET    | `/workflows`        | —                                          | List stored workflow ids.                 |
| GET    | `/providers/local/models` | —                                    | List models the local eGPU gateway exposes (for the picker). |
| GET    | `/health`           | —                                          | Liveness probe.                           |

Interactive docs are served at `/docs`. Example:

```bash
curl -s localhost:8000/projects/compile \
  -H 'content-type: application/json' \
  -d '{"document_text": "When a customer submits an order, validate payment, then ship it."}'
```

## Use — Frontend

A Next.js frontend lives in [`frontend/`](frontend/). Run the backend API and the frontend dev
server side by side (two terminals, both from the repo root):

```bash
# Terminal 1 — backend API (http://localhost:8000)
uvicorn workflow_compiler.api.app:app --reload

# Terminal 2 — frontend dev server (http://localhost:3000)
cd frontend
npm install          # first time only
npm run dev          # or a custom port: npm run dev -- -p 3001
```

Open http://localhost:3000 in your browser. The frontend talks to the backend at
`http://localhost:8000`; override that with `NEXT_PUBLIC_API_BASE` in `frontend/.env.local`.

## Use — Library

```python
import asyncio
from workflow_compiler import WorkflowCompiler

async def main():
    compiler = WorkflowCompiler.from_settings()           # provider + store from .env
    state = await compiler.compile_document(open("examples/order_workflow.md").read())
    print(state.workflow_id, state.stage, state.review_report.health_score)
    final = await compiler.approve_graph(state.workflow_id, reviewer="alice")
    print(final.temporal_design.workflow_name, len(final.cvpa_classification.assignments))

asyncio.run(main())
```

For the spec-centric project flow, use `ProjectCompiler` (`workflow_compiler.project_compiler`)
— it wraps a `WorkflowCompiler` and exposes `compile_document`, `update_specs`, `validate_specs`,
and `approve_spec`.

For tests / offline work, inject a `MockProvider` and an `InMemoryStateStore`:

```python
from workflow_compiler import WorkflowCompiler, InMemoryStateStore
from workflow_compiler.llm.providers.mock import MockProvider

compiler = WorkflowCompiler(llm_provider=MockProvider(structured=[...]),
                            state_store=InMemoryStateStore())
```

## Layout

```
src/workflow_compiler/
  models/        Pydantic v2 domain models (WorkflowState, CompilationProject + every artifact)
  interfaces/    Abstract contracts (BaseParser, BaseAgent, BaseLLMProvider, StateStore, ReviewManager)
  ingestion/     Document parsers (DOCX/PDF/TXT/Markdown/HTML) + DocumentParserFactory
  llm/           Provider-agnostic LLM layer (ProviderFactory, Nemotron, mock)
  prompts/       Markdown prompt templates + PromptManager
  agents/        Discovery, FactExtraction, GraphBuilder, Review, CVPAClassifier, TemporalGenerator
                 (+ review_pipeline: default-on sequential review;
                  segmentation: multi-workflow discovery for the spec-centric front-end)
  spec/          Spec projection layer: deterministic Markdown renderer, parse-back ingestion,
                 provenance-aware spec validator
  checklist/     Readiness rules (validator) + deterministic answer fold-back (amend),
                 surfaced as the spec's Open Questions
  graph/         Deterministic NetworkX graph builder, Mermaid renderer, structural reviewer
  review/        DefaultReviewManager (approval gate) + GraphEditor (validated edits)
  storage/       FileStateStore (JSON on disk) + InMemoryStateStore (+ project stores)
  compiler.py    WorkflowCompiler — per-workflow pipeline engine
  project_compiler.py  ProjectCompiler — the pipeline front-end (segment → specs → gate → compile)
  codegen/       Deterministic Temporal Python code generation (Jinja2)
  api/           FastAPI application
  cli/           Typer command-line interface
examples/        Sample business workflow documents
docs/            Architecture + design docs
tests/           Pytest suite (unit + integration)
```

## Test

```bash
pytest                 # full suite (unit + integration), no network access required
ruff check src tests   # lint
```

The integration tests in `tests/test_integration.py` run the complete pipeline
(Document → … → Temporal) against a deterministic mock provider.
