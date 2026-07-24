# workflow-compiler

Compile free-form **business workflow documents** into structured, canonical artifacts through a
deterministic, reviewable pipeline.

Given a `.docx`, `.pdf`, `.md`, `.html`, or `.txt` description of a business process (one workflow
or many), `workflow-compiler` produces:

- **Editable workflow specifications** — one human-reviewed spec Markdown file per workflow.
- **Canonical workflow graph** — a normalized directed graph, built deterministically from the
  approved spec (no LLM).
- **Mermaid diagram** and a **structural review report** with a health score.
- **CVPA classification** — every node mapped to a **Capture / Validate / Process / Activate** phase.
- **Temporal design & runnable Temporal Python code** — a standalone bundle per workflow, rendered
  deterministically from the approved design.

The human-in-the-loop gate is the **spec**: you edit the spec files and validate them as many
times as you like; code is only generated from what you approved.

## How it works

```
Document ─▶ Segmentation (every workflow + its sections) ─▶ per-workflow Fact Extraction
         ─▶ one editable spec .md file per workflow      [HUMAN GATE: edit ⇄ validate]
         ─▶ approve-spec ─▶ per workflow: Graph (auto-review ≥ health threshold)
                            ─▶ CVPA ─▶ Temporal Design ─▶ Temporal Code
                 ▲
                 └── edit (edit-request document) — change compiled workflows later;
                     the project re-enters the gate and everything regenerates
```

The structured spec model is the source of truth; the Markdown spec files are a deterministic
projection of it. Your edits are parsed back deterministically (no re-extraction), recorded with
provenance, and re-checked for referential integrity. LLM stages (segmentation, fact extraction,
CVPA, Temporal design) are provider-agnostic; graph building and code generation are fully
deterministic.

**Stack:** Python 3.12+ · Pydantic v2 · FastAPI · Typer · NetworkX · Jinja2 · Next.js (frontend)

Detailed design, CLI flag tables, and the full HTTP API reference live in the docs:

- [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) — full ground-up walkthrough, CLI reference (§9.2),
  HTTP API reference (§9.3)
- [`docs/architecture.md`](docs/architecture.md) — component and sequence diagrams
- [`docs/EDIT_FORMAT_GUIDE.md`](docs/EDIT_FORMAT_GUIDE.md) — the edit-request document format

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| [Python](https://www.python.org/downloads/) | **3.12+** | everything (`requires-python >= 3.12`) |
| [Git](https://git-scm.com/downloads) | any recent | cloning the repo |
| [Node.js](https://nodejs.org/) | **20.9+** | the web frontend only (Next.js 16) |
| [Temporal CLI](https://docs.temporal.io/cli#install) | any recent | *running* generated workflow bundles only |

Check your Python version with `python --version` (Windows: `py -3.12 --version`) — a 3.11 or
older default Python will fail to install the package.

## Install

```bash
git clone https://github.com/oktopuslinky/order-workflows-2.0.git
cd order-workflows-2.0
```

Create and activate a virtual environment with Python 3.12+:

```bash
# macOS / Linux
python3.12 -m venv .venv
source .venv/bin/activate
```

```powershell
# Windows (PowerShell)
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

Then install the package with dev tooling:

```bash
pip install -e ".[dev]"
```

This installs the package, its dependencies, and the `workflow-compiler` console script.
Verify with:

```bash
workflow-compiler --version
```

## Configure

Copy `.env.example` to `.env` (`cp .env.example .env`; PowerShell: `copy .env.example .env`) and
configure the LLM — only needed for the LLM-backed stages; `--provider mock` runs fully offline
with no key:

```dotenv
# NVIDIA-hosted Nemotron (the default provider). Get a key at build.nvidia.com.
NVIDIA_API_KEY=nvapi-xxxxxxxx
WORKFLOW_COMPILER_LLM_PROVIDER=nemotron
WORKFLOW_COMPILER_LLM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1

# Optional: local eGPU gateway (session auth — register at the gateway's /ui/).
# Set WORKFLOW_COMPILER_LLM_PROVIDER=local (or local-fallback for eGPU-primary
# with automatic Nemotron fallback).
LLM_API_BASE=http://192.168.1.184:8080/v1
LLM_GATEWAY_EMAIL=you@example.com
LLM_GATEWAY_PASSWORD=your-password
```

State is persisted as JSON under `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`).
See `.env.example` for every setting.

## Use — CLI

```bash
# Fully offline smoke test (mock provider, no API key needed):
workflow-compiler compile examples/order_workflow.md --provider mock --spec-dir ./specs

# The real pipeline:
workflow-compiler compile your_doc.docx --spec-dir ./specs   # → one editable spec file per workflow
# ... edit the spec files in any editor ...
workflow-compiler validate <project-id> --spec-dir ./specs   # fold edits back in, re-check
workflow-compiler approve-spec <project-id> --spec-dir ./specs   # compile through to Temporal code
```

Generated bundles land under `./generated/<project-id>/<slug>/`. Other commands: `edit` (apply an
edit-request document to a compiled project), `approve` / `reject` (manual override for a
below-threshold graph), `show`, `models`. `workflow-compiler <command> --help` is the
authoritative flag reference; the full command guide is in
[`docs/HOW_IT_WORKS.md` §9.2](docs/HOW_IT_WORKS.md).

### Running a generated bundle

Each generated bundle is standalone — it needs the Temporal SDK and a local Temporal dev server
(see its own `README.md`):

```bash
pip install temporalio
temporal server start-dev      # terminal 1, leave running
python worker.py               # terminal 2, from the bundle directory
python starter.py              # terminal 3
```

## Use — HTTP API

```bash
uvicorn workflow_compiler.api.app:app --reload
```

Interactive docs at http://localhost:8000/docs. The API uses local accounts (register once via
`POST /auth/register`; a session cookie rides every call). Full endpoint reference:
[`docs/HOW_IT_WORKS.md` §9.3](docs/HOW_IT_WORKS.md).

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

Open http://localhost:3000. The frontend talks to the backend at `http://localhost:8000`;
override with `NEXT_PUBLIC_API_BASE` in `frontend/.env.local`.

## Use — Library

```python
import asyncio
from workflow_compiler import WorkflowCompiler

async def main():
    compiler = WorkflowCompiler.from_settings()           # provider + store from .env
    state = await compiler.compile_document(open("examples/order_workflow.md").read())
    print(state.workflow_id, state.stage, state.review_report.health_score)
    final = await compiler.approve_graph(state.workflow_id, reviewer="alice")
    print(final.temporal_design.workflow_name)

asyncio.run(main())
```

For the spec-centric project flow, use `ProjectCompiler` (`workflow_compiler.project_compiler`).
For tests / offline work, inject a `MockProvider` and an `InMemoryStateStore` — see
[`docs/HOW_IT_WORKS.md` §9.1](docs/HOW_IT_WORKS.md).

## Test

```bash
pytest                 # full suite (unit + integration), no network access required
ruff check src tests   # lint
mypy src               # strict type-check
```

The test suite runs fully offline against a deterministic mock provider — no API key needed.

## Troubleshooting

- **`UnicodeEncodeError` on Windows** — the progress output contains Unicode (e.g. `→`); on a
  legacy `cp1252` console run with UTF-8 mode: `set PYTHONUTF8=1` (PowerShell:
  `$env:PYTHONUTF8=1`). Console-rendering only; generated code is unaffected.
- **`ProviderTimeoutError`** — Nemotron's reasoning models can be slow; bump `--timeout`
  (e.g. `300`).
- **`pip install` fails resolving the package** — check you are on Python 3.12+ inside the
  activated venv (`python --version`).

## Layout

```
src/workflow_compiler/   the package: models, agents, spec layer, graph, codegen, api, cli
frontend/                Next.js web UI
examples/                sample business workflow documents
docs/                    architecture + design docs (start with HOW_IT_WORKS.md)
tests/                   pytest suite (unit + integration)
generated/               example output bundles
```
