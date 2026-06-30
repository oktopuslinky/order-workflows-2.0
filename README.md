# workflow-compiler

Compile free-form **business workflow documents** into structured, canonical artifacts through a
deterministic, reviewable pipeline.

Given a `.docx`, `.pdf`, `.md`, `.html`, or `.txt` description of a business process,
`workflow-compiler` produces:

- **Workflow metadata** — name, purpose, actors, systems, triggers, start/end states.
- **Workflow facts** — atomic, categorized statements extracted from the source (13 categories:
  inputs, outputs, activities, decisions, rules, events, APIs, systems, exceptions, state
  transitions, timers, retries, compensation candidates).
- **Canonical workflow graph** — a normalized directed graph (NetworkX-backed), built
  **deterministically** from the facts (no LLM).
- **Mermaid diagram** — a renderable diagram of the graph.
- **Review report** — structural health check (orphans, dead-ends, unreachable nodes, missing
  branches, unintended cycles, …) with a health score.
- **CVPA classification** — every node mapped to exactly one **Capture / Validate / Process /
  Activate** phase, with rationale and confidence.
- **Temporal design** — an architecture-only Temporal blueprint (workflow definition, activities,
  signals, queries, child workflows, timers, retries, compensation activities). *No executable
  code is generated.*
- **Confidence scores** — per-stage and overall.

A human-in-the-loop **review / approval gate** sits between graph generation and downstream
artifact production: CVPA and Temporal artifacts are only produced once a graph is approved.

## Pipeline

```
Document ─▶ Parser ─▶ Workflow Discovery ─▶ Fact Extraction ─▶ Graph Builder ─▶ Review
                                                                                   │
                                                                          ┌────────┴────────┐
                                                                       approve            reject
                                                                          │                  │
                                                          CVPA Classification          (pipeline halts)
                                                                          │
                                                                  Temporal Design ─▶ COMPLETED
```

By default the **Workflow Discovery** and **Fact Extraction** stages each generate one canonical
output and then run three sequential **review passes** (completeness → grounding → consistency) that
patch it in place; this is on by default and toggled with `--review` / `--no-review` (see below).

See [`docs/architecture.md`](docs/architecture.md) for component and sequence diagrams.

## Stack

Python 3.12+ · Pydantic v2 · FastAPI · Typer · NetworkX · Loguru · Rich · Pytest

The LLM layer is **provider-agnostic**. The default provider talks to NVIDIA-hosted Nemotron
models over an OpenAI-compatible REST API; any provider can be registered without touching agent
or compiler code. A `mock` provider ships for offline/testing use.

## Install

```bash
pip install -e ".[dev]"
```

This installs the package and the `workflow-compiler` console script.

## Configure

Copy `.env.example` to `.env` and set your NVIDIA API key (only needed for the LLM-backed stages —
discovery, fact extraction, CVPA, Temporal):

```dotenv
NVIDIA_API_KEY=nvapi-xxxxxxxx
WORKFLOW_COMPILER_LLM_PROVIDER=nemotron
WORKFLOW_COMPILER_LLM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
WORKFLOW_COMPILER_STATE_STORE_PATH=.workflow_state
```

State is persisted as JSON under `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`).

## Use — CLI

Five commands. `compile`, `approve`, and `inspect` use the LLM (set `NVIDIA_API_KEY`, or pass
`--provider mock`); `reject` and `show` need no LLM. `--version` prints the version, and
`workflow-compiler <command> --help` is always the authoritative reference.

### `compile <document>` — run discovery → facts → graph → review, stop at the gate

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` | from `.env` | Override the LLM provider (e.g. `mock`). |
| `--model ID` | from `.env` | Override the model id. |
| `--timeout SECONDS` | `120` | Per-request timeout. |
| `--auto-approve` | off | Skip the human gate and run the **whole** pipeline (CVPA → Temporal design → Temporal code) in one call. |
| `--persist` / `--no-persist` | persist | Whether to save the resulting state to the store. |
| `--out PATH` | — | Write the Mermaid diagram to a file (CVPA-colored when `--auto-approve`). |
| `--out-dir DIR` | — | Write the generated Temporal code bundle (only produced with `--auto-approve`). |
| `--ensemble` | off | Run discovery + fact extraction N times and consensus-merge the candidates (see below). |
| `--ensemble-n N` | `0` | Number of ensemble candidates (`0` = configured default of 3). |
| `--review` / `--no-review` | review | Sequential review passes (completeness → grounding → consistency) over discovery + facts (see below). On any stage where `--ensemble` is active, the ensemble takes precedence. |

```bash
workflow-compiler compile examples/order_workflow.md                       # → prints a workflow_id, stops at gate
workflow-compiler compile examples/order_workflow.md --provider mock       # → offline, no API key
workflow-compiler compile examples/order_workflow.md --auto-approve \
    --out workflow.mmd --out-dir ./generated                               # → full pipeline + colored diagram + code
workflow-compiler compile examples/order_workflow.md --ensemble --ensemble-n 3   # → 3-way consensus on discovery+facts
workflow-compiler compile examples/order_workflow.md --no-review                 # → skip the default review passes
```

### `approve <workflow_id>` — clear the gate, produce CVPA + Temporal design + Temporal code

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | Reviewer identity recorded on the approval. |
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | Same LLM overrides as `compile`. |
| `--out PATH` | — | Write the CVPA-colored Mermaid diagram to a file. |
| `--out-dir DIR` | — | Write the generated Temporal Python code bundle to a directory. |

```bash
workflow-compiler approve <workflow_id> --reviewer alice
workflow-compiler approve <workflow_id> --out workflow.mmd --out-dir ./generated
```

### `reject <workflow_id>` — halt the pipeline (no LLM)

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

### `inspect <document>` — preview discovery → facts → graph without saving

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | Same LLM overrides as `compile`. |
| `--out PATH` | — | Write the generated Mermaid diagram to a file. |

```bash
workflow-compiler inspect examples/order_workflow.md --out workflow.mmd
```

### Sequential review pipeline (default-on)

The **default** quality lever on the **discovery** and **fact-extraction** stages. Rather than
trusting a single sample, it follows a compiler discipline: **generate one canonical output, then
improve it with three sequential review passes** — *completeness* (add elements explicitly in the
document but missing), *grounding* (remove/flag elements not supported by the document), and
*consistency* (merge duplicates, rename to a canonical label, fix relations). Each pass emits
**minimal deterministic patches or `no_change`** (never a rewrite), and a pure applier folds them in
— dropping any addition that duplicates an existing element or isn't grounded in the document, which
makes the passes **idempotent**. It raises grounding/consistency, not certified truth (the human gate
stays the oracle). See [§7.11 of `docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md). On by default; toggle
with `--review` / `--no-review` or via `.env`:

```dotenv
WORKFLOW_COMPILER_REVIEW_ENABLED=true                  # default; --no-review overrides to off
WORKFLOW_COMPILER_REVIEW_STAGES=["discovery","facts"]  # which stages get the review pipeline
```

> Precedence per stage is **ensemble → review → plain**: if `--ensemble` is enabled for a stage the
> ensemble runs there; otherwise the review pipeline runs; otherwise the plain agent runs.

### Consensus-merge ensemble (`--ensemble`)

Opt-in accuracy mode: runs the **discovery** and **fact-extraction** stages N times at varied
temperatures and **merges the candidates' parts** instead of trusting one sample — a part that
appears in most candidates is kept, a single-candidate part is kept only if it grounds in the
document (and is flagged low-confidence), and conflicts are resolved by vote. It suppresses
hallucinations but never certifies truth (the human gate stays the oracle). See
[§7.10 of `docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md). Defaults are configurable via `.env`:

```dotenv
WORKFLOW_COMPILER_ENSEMBLE_ENABLED=true            # same as passing --ensemble
WORKFLOW_COMPILER_ENSEMBLE_N=3                      # candidates per stage
WORKFLOW_COMPILER_ENSEMBLE_TEMPERATURES=[0.2,0.5,0.8]
WORKFLOW_COMPILER_ENSEMBLE_STAGES=["discovery","facts"]
WORKFLOW_COMPILER_ENSEMBLE_PER_CANDIDATE_TIMEOUT=300
WORKFLOW_COMPILER_ENSEMBLE_OVERALL_TIMEOUT=480
```

> Cost note: the ensemble multiplies the discovery + facts LLM calls by N (run in parallel), which
> is why it is opt-in and off by default.

## Use — HTTP API

```bash
uvicorn workflow_compiler.api.app:app --reload
```

| Method | Path                | Body / Params                              | Purpose                                   |
|--------|---------------------|--------------------------------------------|-------------------------------------------|
| POST   | `/compile`          | `{document_text, persist?, auto_approve?}` | Compile to a review-ready state.          |
| POST   | `/approve`          | `{workflow_id, reviewer?}`                 | Approve → run CVPA + Temporal.            |
| POST   | `/reject`           | `{workflow_id, reviewer?, reason?}`        | Reject a graph.                           |
| GET    | `/workflow/{id}`    | —                                          | Load a stored workflow state.             |
| GET    | `/workflows`        | —                                          | List stored workflow ids.                 |
| GET    | `/health`           | —                                          | Liveness probe.                           |

Interactive docs are served at `/docs`. Example:

```bash
curl -s localhost:8000/compile \
  -H 'content-type: application/json' \
  -d '{"document_text": "When a customer submits an order, validate payment, then ship it."}'
```

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
  models/        Pydantic v2 domain models (WorkflowState + every artifact)
  interfaces/    Abstract contracts (BaseParser, BaseAgent, BaseLLMProvider, StateStore, ReviewManager)
  ingestion/     Document parsers (DOCX/PDF/TXT/Markdown/HTML) + DocumentParserFactory
  llm/           Provider-agnostic LLM layer (ProviderFactory, Nemotron, mock)
  prompts/       Markdown prompt templates + PromptManager
  agents/        Discovery, FactExtraction, GraphBuilder, Review, CVPAClassifier, TemporalGenerator
                 (+ review_pipeline: default-on sequential review; ensemble: opt-in consensus merge)
  graph/         Deterministic NetworkX graph builder, Mermaid renderer, structural reviewer
  review/        DefaultReviewManager (approval gate) + GraphEditor (validated edits)
  storage/       FileStateStore (JSON on disk) + InMemoryStateStore
  compiler.py    WorkflowCompiler — end-to-end orchestration
  api/           FastAPI application
  cli/           Typer command-line interface
examples/        Sample business workflow documents
docs/            Architecture diagrams
tests/           Pytest suite (unit + integration)
```

## Test

```bash
pytest                 # full suite (unit + integration), no network access required
ruff check src tests   # lint
```

The integration tests in `tests/test_integration.py` run the complete pipeline
(Document → … → Temporal) against a deterministic mock provider.
