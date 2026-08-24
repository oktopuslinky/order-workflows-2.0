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

## Quick start

Clean machine to generated Temporal code, fully offline, no API key. Requires **Python 3.12+**
and Git ([details below](#prerequisites)).

```bash
git clone https://github.com/SoumyajitPodder/Intelligent_Workflow_Builder.git
cd Intelligent_Workflow_Builder/workflow-compiler
```

The Python package lives in the **`workflow-compiler/` subdirectory** of the clone — that is where
`pyproject.toml` is, and every command in this README runs from there.

```powershell
# Windows (PowerShell)
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3.12 -m venv .venv
source .venv/bin/activate
```

```bash
pip install .
workflow-compiler init --provider mock --yes
workflow-compiler compile examples/order_workflow.md --provider mock --spec-dir ./specs-out
```

That last command prints a `project_id` **and the exact two commands that finish the run** —
`validate`, then `approve-spec`. Copy them from the output; the generated Temporal bundle lands in
`./generated/<project-id>/<slug>/`.

From here: [Install](#install) to point it at a real LLM provider, [Use — CLI](#use--cli) for the
full command set, or [Use — Frontend](#use--frontend) for the web UI.

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

- [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) — full ground-up walkthrough, plus the
  [CLI reference](docs/HOW_IT_WORKS.md#152-cli-climainpy-typer--rich) (§15.2) and the
  [HTTP API reference](docs/HOW_IT_WORKS.md#153-http-api-apiapppy-fastapi) (§15.3)
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

Everything below runs from the **`workflow-compiler/` directory inside the clone**, not from the
repository root: that is where `pyproject.toml`, `examples/` and `frontend/` live.

## Install

Installing and configuring are two separate steps. `pip` cannot do the second one for you — a
wheel never runs code at install time — so configuration is a command you type.

**1. Get the code, in a Python 3.12+ virtual environment.**

```bash
git clone https://github.com/SoumyajitPodder/Intelligent_Workflow_Builder.git
cd Intelligent_Workflow_Builder/workflow-compiler
```

The same code is mirrored to
[`oktopuslinky/order-workflows-2.0`](https://github.com/oktopuslinky/order-workflows-2.0) on the
`feat/kg-change-pipeline` branch — clone that one with
`git clone -b feat/kg-change-pipeline <url>` if you prefer the mirror.

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

**2. Install the package.**

```bash
pip install .
```

This installs the dependencies and the `workflow-compiler` console script. Verify with:

```bash
workflow-compiler --version
```

**3. Configure it.**

```bash
workflow-compiler init
```

`init` asks which LLM provider to use, asks for the credentials that provider needs, and writes
a `.env` file. Pick `mock` to run fully offline with no API key.

| Provider | Needs | Use it for |
|---|---|---|
| `nemotron` | an NVIDIA API key ([build.nvidia.com](https://build.nvidia.com)) | the default — NVIDIA-hosted models |
| `local` | a reachable eGPU gateway + login | your own gateway only |
| `local-fallback` | both of the above | gateway first, Nemotron when it is unreachable |
| `mock` | nothing | offline smoke tests and demos |

For scripts and containers, `init` also runs without questions:

```bash
workflow-compiler init --provider mock --yes
workflow-compiler init --provider nemotron --nvidia-api-key "$NVIDIA_API_KEY" --yes
```

`--force` replaces an existing `.env`; `--env-file` writes somewhere other than `./.env`.
Everything `init` writes is plain text you can edit afterwards, and `.env.example` documents the
full setting list — including `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`),
where compiled state is persisted as JSON.

## Use — CLI

```bash
# Fully offline smoke test (mock provider, no API key needed):
workflow-compiler compile examples/order_workflow.md --provider mock --spec-dir ./specs-out

# The real pipeline:
workflow-compiler compile your_doc.docx --spec-dir ./specs-out   # → one editable spec file per workflow
# ... edit the spec files in any editor ...
workflow-compiler validate <project-id> --spec-dir ./specs-out   # fold edits back in, re-check
workflow-compiler approve-spec <project-id> --spec-dir ./specs-out   # compile through to Temporal code
```

You never have to note the `project_id` down: `compile` (and `validate`) print it along with the
exact next command to run. `--spec-dir` is any directory you choose — the repo already ships an
example `specs/` from an earlier run, and `specs-*/` is git-ignored, so `./specs-out` keeps your
working tree clean.

Generated bundles land under `./generated/<project-id>/<slug>/`. Other commands: `init` (write the
`.env` configuration — see Install), `edit` (apply an edit-request document to a compiled project),
`approve` / `reject` (manual override for a below-threshold graph), `show`, `models`, and
`kb init|list|show|ask|impact|search|delete` (knowledge bases) and `cr create|list|show|draft|approve|export [--format md|docx|xlsx|zip]|delete` (change requests — see below). `workflow-compiler <command> --help` is the
authoritative flag reference; the full command guide is in
[`docs/HOW_IT_WORKS.md` §15.2](docs/HOW_IT_WORKS.md#152-cli-climainpy-typer--rich).

### Business change pipeline — end to end (phases 0–5)

The five subsections below are one flow; this is the short version (the full demo script with
ids, timings and screenshots is `docs/kg-plan/RUNBOOK.md`):

1. **Knowledge base** — *Knowledge → Upload and index* the zipped `Existing_KG`
   (`examples/knowledge_bases/order-lifecycle.zip`; enrichment on cloud Nemotron ≈ 6 min cached /
   27 min cold, static ingest ≈ 5 s). CLI: `workflow-compiler kb init … --enrich`.
2. **Change request** — *Changes → New change request*: pick the KB, upload
   `examples/change_requests/BCR-001-partial-shipment-support.docx`, **Start wizard**, then per
   step (Impact → EPIC → Stories → TDD) answer the questions, **Draft now**, revise/edit, **Approve**
   (≈ 20 min of model time). CLI: `cr create`, `cr draft <id> <step> --auto`, `cr approve`.
3. **Export** — `.docx` / `.md` (/ `.xlsx`) per artifact or **Export all (.zip)** — deterministic,
   byte-stable, in the manager's template look. CLI: `cr export`.
4. **Send to workflow GUI** — one click on the approved TDD compiles a **grounded** project
   (`specs/*.md` + `changes.md`, ≈ 4 min); Spec tab: edit ⇄ **Validate** ⇄ **Resolve** ⇄
   **Approve** (saves are compare-and-swap — a 409 means reload first). CLI: `compile … --kb --change-request`.
5. **Change outputs** — the approve job chains a `change_outputs` job (≈ 25 min): updated
   diagrams, the modified code base with diffs (per-file checks, up to 2 repair rounds, keep-style,
   a bundle **smoke test**), the TC matrix + TP addendum; Results → **Change outputs** →
   **Download all (.zip)**. CLI: `approve-spec … --change-outputs`, `change-outputs <project-id>`.

Reset for a fresh demo: `python scripts/reset_demo_state.py` (dry run) → `--yes` (backup zip
first, `--keep <id>` to spare the reference KB/CR).

### Knowledge bases (business-change pipeline, phase 0)

A knowledge base is a zipped corpus — business docs, diagrams, code, tests — indexed into a graph
that later grounds change requests and specs in the *real* modules, stories and test cases of an
existing system. Upload one on the **Knowledge** page (provider picker + LLM-enrichment toggle,
indexing runs as a background job), or from the CLI:

```bash
python scripts/make_kb_zip.py                       # → examples/knowledge_bases/order-lifecycle.zip
workflow-compiler kb init examples/knowledge_bases/order-lifecycle --no-enrich --id order-lifecycle
workflow-compiler kb ask order-lifecycle "how does dispatch compensate provisioning"
workflow-compiler kb impact order-lifecycle complete_order
```

`--enrich` (the UI default) adds per-file summaries/topics/entities and process clusters through
the selected LLM provider (one call per document/module; cached). Design and routes:
[`docs/HOW_IT_WORKS.md` §10](docs/HOW_IT_WORKS.md#10-knowledge-bases-kg) / [§15.3](docs/HOW_IT_WORKS.md#153-http-api-apiapppy-fastapi); the multi-phase plan lives in
`docs/kg-plan/`.

### Change requests (business-change pipeline, phase 1)

Upload a business change request (the sample `examples/change_requests/BCR-001-partial-shipment-support.docx`)
against a knowledge base on the **Changes** page and walk the guided wizard — **Impact → EPIC →
Stories → TDD**. Each step asks a few grounded clarifying questions (answer, pick a suggested
option, skip, or just "Draft now"), drafts a markdown artifact grounded in knowledge-graph
retrievals and a deterministic impact traversal (a "Sources" footer lists the KB files and line
spans used), and lets you revise it in chat, edit it by hand (every change is a version) and
approve it. Ids (`EPIC-002`, `US-008…`, `TDD-ORD-002`) are assigned from the KB's catalog by the
engine, not the model. From the CLI:

```bash
workflow-compiler cr create order-lifecycle examples/change_requests/BCR-001-partial-shipment-support.docx --provider nemotron
workflow-compiler cr draft <cr-id> impact --auto --out impact.md    # questions answered with the first option
workflow-compiler cr approve <cr-id> impact && workflow-compiler cr draft <cr-id> epic --auto
```

Design and routes: [`docs/HOW_IT_WORKS.md` §11](docs/HOW_IT_WORKS.md#11-change-requests-change) / [§15.3](docs/HOW_IT_WORKS.md#153-http-api-apiapppy-fastapi).

### Word / Excel export (business-change pipeline, phase 2)

Every artifact exports as a Word document in the manager's template style (22 pt document-type
title, metadata block, Heading 1/2, shaded tables, ☑/☐ checklists, Consolas code) — one file per
user story — plus the impact analysis' affected test cases as a `TC-…xlsx` preview and the whole
change request as a zip with the markdown sources. Exports are deterministic (no model call) and
say what they are: `Approved vN` or `DRAFT vN — not approved`. Use the `.docx` / `.md` / `.xlsx`
buttons on the wizard page, **Export all (.zip)**, or the CLI:

```bash
workflow-compiler cr export <cr-id> tdd --format docx --out TDD-ORD-002.docx   # the Phase 3 input
workflow-compiler cr export <cr-id> impact --format xlsx                         # TC preview
workflow-compiler cr export <cr-id> --format zip --out change-request.zip
```

The sample output for BCR-001 is `examples/change_requests/TDD-ORD-002.docx`.

### KG-grounded projects + change spec (business-change pipeline, phase 3)

Compile the TDD **with the knowledge base** and every extraction prompt sees the graph's real
module / activity / state / test names, and the project gets a second editable file,
`changes.md` — the change spec, one *existing vs. proposed* block per component — that goes
through the same Save ⇄ Validate ⇄ Resolve ⇄ Approve gate as the workflow specs (empty
*Proposed* blocks approval; unknown paths / requirement ids warn with suggestions):

```bash
workflow-compiler compile examples/change_requests/TDD-ORD-002.docx --spec-dir ./specs-out \
    --kb <kb-id> --change-request <cr-id>        # writes <slug>.md + changes.md + overview.md
workflow-compiler validate <project-id> --spec-dir ./specs-out   # folds changes.md back in too
```

In the UI: pick *Ground with knowledge base* next to the provider on the home page, or press
**Send to workflow GUI** on an approved TDD in the change-request wizard (`POST
/change-requests/{id}/send-to-workflow`); the project header then reads *Grounded by ‹KB› · from
‹change request›* and `changes.md` sits under *Change spec* in the Spec tab. Grammar:
`frontend/SPEC_GUIDE.md`.

### Post-approval change outputs (business-change pipeline, phase 4)

Approving a knowledge-base-grounded project also produces the three deliverables the change asked
for, built from the knowledge base's real files: the **updated Mermaid diagrams** (every original
`.mmd` regenerated + the companion diagram the change spec adds + `system-flow-diagram.md`), the
**modified code base with a diff per file** (types → activities → workflow → worker/starter →
tests, each rewritten in order and checked with `ast.parse` / ruff; untouched files copied), and
the **updated test-case matrix + test-plan addendum** (`TC-18…` numbered from the knowledge base,
updated rows keep their original notes; `.xlsx` and `.docx` in the reference style). In the API
this runs as a `change_outputs` job chained after approve; the Results tab gets a
**Change outputs** view (diagrams with an original ⇄ updated toggle, a diff viewer, the test-case
table, Regenerate per stage, Download all). CLI:

```bash
workflow-compiler approve-spec <project-id> --spec-dir ./specs-out --change-outputs   # chain it
workflow-compiler change-outputs <project-id> --stage code                        # re-run one stage
# → ./generated/<project-id>/change-outputs/{src,tests,docs,changes.patch,CHANGES.md}
```

`GET /projects/{id}/change-outputs/export.zip` is the same bundle (README layout, so the generated
tests run as-is with `temporalio` installed).

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

Activate the virtual environment you installed into first, then:

```bash
python -m uvicorn workflow_compiler.api.app:app --reload
```

Interactive docs at http://localhost:8000/docs.

> `python -m uvicorn` (not bare `uvicorn`) on purpose: it runs the server with *this* interpreter,
> so it always sees the `workflow_compiler` you installed. A bare `uvicorn` resolves through `PATH`
> and may belong to a different environment — the symptom is
> `ModuleNotFoundError: No module named 'workflow_compiler'` from the reloader subprocess.
> Check which one you would get with `where uvicorn` (Windows) / `which uvicorn` (macOS/Linux).

The API uses local accounts: register once, and a session cookie rides every later call.

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

Full endpoint reference: [`docs/HOW_IT_WORKS.md` §15.3](docs/HOW_IT_WORKS.md#153-http-api-apiapppy-fastapi).

## Use — Frontend

A Next.js frontend lives in [`frontend/`](frontend/). Run the backend API and the frontend dev
server side by side (two terminals, both starting from the `workflow-compiler/` directory):

```bash
# Terminal 1 — backend API (http://localhost:8000), venv activated
python -m uvicorn workflow_compiler.api.app:app --reload

# Terminal 2 — frontend dev server (http://localhost:3000)
cd frontend
npm install          # first time only
npm run dev          # or a custom port: npm run dev -- -p 3001
```

Open http://localhost:3000. The frontend talks to the backend at `http://localhost:8000`;
override with `NEXT_PUBLIC_API_BASE` in `frontend/.env.local`.

## Use — Resolve findings by conversation

Editing spec Markdown by hand is not the only way through the human gate. Open a
project's **Resolve** tab and the compiler asks about what it could not settle from the
document — one plain-language question at a time — and you answer in ordinary prose:

> ⛔ **order-fulfillment › Outputs**
> "Payment Confirmed" is produced but never consumed. Which workflow picks it up?
>
> *— it goes to the shipping workflow, that one kicks off once payment clears*

Each answer is translated into deterministic spec operations and applied **immediately**
(the workflow's patch version bumps per answer), so stopping half way keeps everything you
already answered. Questions are drawn from the validator's blocking and warning findings
plus each spec's unresolved open questions — so run `validate` first.

Three behaviors worth knowing:

- Related findings are **grouped** into one question rather than asked mechanically.
- A vague answer earns **one** clarifying follow-up, never an interrogation.
- An answer that cannot become a spec change — "ops owns that, not decided yet" — is
  **recorded as a new open question** instead of being discarded.

Because the specs change, validation must run again before approval. The same flow is
available over HTTP (`POST /projects/{id}/dialogue`, then `/dialogue/answer`); see
[`docs/HOW_IT_WORKS.md` §15.3](docs/HOW_IT_WORKS.md#153-http-api-apiapppy-fastapi).

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
[`docs/HOW_IT_WORKS.md` §15.1](docs/HOW_IT_WORKS.md#151-library).

## Develop

Working on the compiler itself needs two things the install above deliberately leaves out:

- `-e` (editable) points the install at your working tree, so a source edit takes effect without
  reinstalling.
- `[dev]` adds the tooling that is not part of the package — `pytest`, `ruff`, `mypy`, and the
  fixtures used by the test suite.

```bash
pip install -e ".[dev]"   # the quotes are required on zsh
```

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
- **`ERROR: Directory '.' is not installable. Neither 'setup.py' nor 'pyproject.toml' found.`** —
  you are one level too high. The package is in the clone's `workflow-compiler/` subdirectory:
  `cd workflow-compiler`, then `pip install .`.
- **`.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled`** — allow
  scripts for this shell only: `Set-ExecutionPolicy -Scope Process RemoteSigned`. Alternatives:
  `.venv\Scripts\activate.bat` from `cmd`, or skip activation entirely and call
  `.venv\Scripts\python.exe -m pip install .`.
- **`Filename too long` while cloning on Windows** — clone into a short path (paths in this repo
  reach ~140 characters, and Windows caps at 260), or clone with
  `git clone -c core.longpaths=true <url>`.

## Layout

```
src/workflow_compiler/   the package: models, agents, spec layer, graph, codegen, api, cli
frontend/                Next.js web UI
examples/                sample business workflow documents
docs/                    architecture + design docs (start with HOW_IT_WORKS.md)
tests/                   pytest suite (unit + integration)
generated/               example output bundles
```
