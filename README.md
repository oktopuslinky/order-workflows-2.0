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

```bash
# Compile a document up to the review gate; prints a workflow_id.
workflow-compiler compile examples/order_workflow.md

# Inspect the review, then approve to produce CVPA + Temporal artifacts.
workflow-compiler approve <workflow_id> --reviewer alice

# Usage to regenerate a colored file for an existing workflow:
workflow-compiler approve <workflow_id> --out workflow.mmd

# Or reject (halts the pipeline; no LLM required).
workflow-compiler reject <workflow_id> --reason "missing cancellation branch"

# Display any stored workflow (no LLM required).
workflow-compiler show <workflow_id>

# Run the whole pipeline in one shot (skips the human gate).
workflow-compiler compile examples/order_workflow.md --auto-approve

# Preview discovery → facts → graph and dump the Mermaid diagram, no persistence.
workflow-compiler inspect examples/order_workflow.md --out workflow.mmd
```

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
