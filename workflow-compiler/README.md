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

There are two ways to drive it: the **web UI in your browser** (the primary experience — start
here) and the **terminal CLI** (same pipeline, scriptable). Both are covered below.

---

## Run it in your browser

The web UI is the recommended way to use workflow-compiler: upload a document, watch it compile,
edit the specs, resolve open findings in a chat, approve, and download the generated Temporal code
— plus the whole knowledge-base / change-request pipeline — without leaving the browser.

It runs as **two local processes**: the backend **API** (FastAPI, port 8000) and the **frontend**
(Next.js, port 3000). You start each in its own terminal, then open the frontend.

### 1. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| [Python](https://www.python.org/downloads/) | **3.12+** | the backend API (`requires-python >= 3.12`) |
| [Node.js](https://nodejs.org/) | **20.9+** | the Next.js frontend (Next.js 16) |
| [Git](https://git-scm.com/downloads) | any recent | cloning the repo |
| [Temporal CLI](https://docs.temporal.io/cli#install) | any recent | *running* a generated bundle only |

Check your Python with `python --version` (Windows: `py -3.12 --version`) — a 3.11-or-older default
will fail to install the package.

### 2. Get the code

```bash
git clone https://github.com/SoumyajitPodder/Intelligent_Workflow_Builder.git
cd Intelligent_Workflow_Builder/workflow-compiler
```

The Python package and the `frontend/` both live in the **`workflow-compiler/` subdirectory** of
the clone — that is where `pyproject.toml` is, and every command below runs from there. (The same
code is mirrored to [`oktopuslinky/order-workflows-2.0`](https://github.com/oktopuslinky/order-workflows-2.0);
clone that with `git clone -b master <url>` if you prefer the mirror.)

### 3. Install and configure the backend

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

```bash
pip install .                 # installs deps + the `workflow-compiler` console script
workflow-compiler init        # writes .env: pick a provider, enter its credentials
```

`init` asks which LLM provider to use and writes a `.env`. Pick **`mock`** to run fully offline
with no API key, or **`nemotron`** for real output (needs an NVIDIA API key from
[build.nvidia.com](https://build.nvidia.com)). See [Providers](#providers) for the full table;
non-interactive form: `workflow-compiler init --provider mock --yes`.

### 4. Start the backend API (terminal 1)

With the virtual environment activated:

```bash
python -m uvicorn workflow_compiler.api.app:app        # serves http://localhost:8000
```

Leave it running. Interactive API docs are at http://localhost:8000/docs.

> **Do not add `--reload`** unless you are editing the backend source. The reloader watches every
> `*.py` under the working directory — including the corpus a knowledge base extracts under
> `.workflow_state/` — so indexing a knowledge base restarts the server mid-job and leaves it stuck
> at "Indexing…". (Contributors with an editable install can scope it: `--reload --reload-dir src`.)
>
> Use `python -m uvicorn` (not bare `uvicorn`) so the server runs under *this* interpreter and sees
> the `workflow_compiler` you installed. A bare `uvicorn` resolves through `PATH` and may belong to
> another environment — the symptom is `ModuleNotFoundError: No module named 'workflow_compiler'`.

### 5. Start the frontend (terminal 2)

In a second terminal, from the same `workflow-compiler/` directory:

```bash
cd frontend
npm install          # first time only
npm run dev          # serves http://localhost:3000  (custom port: npm run dev -- -p 3001)
```

### 6. Open the app

Open **http://localhost:3000**, register an account (the first thing the UI asks for), and you are
in. From there you can:

- **Compile a document** — upload a workflow doc on the home page, pick a provider, and watch the
  stages run; then edit the spec files, **Validate**, and **Approve** to generate Temporal code.
- **Resolve** — answer the compiler's open questions in plain language on a project's *Resolve* tab
  (see [Resolve findings by conversation](#resolve-findings-by-conversation)).
- **Knowledge / Changes** — run the full business-change pipeline: index a knowledge base, walk a
  change request through the wizard, export Word/Excel, and generate updated code
  (see [Business change pipeline](#business-change-pipeline--end-to-end)).

The frontend talks to the backend at `http://localhost:8000`; override with `NEXT_PUBLIC_API_BASE`
in `frontend/.env.local` if you moved it.

---

## Run it from the terminal

The CLI runs the same pipeline without the browser — good for scripting, CI, and offline smoke
tests. Everything runs from the **`workflow-compiler/` directory** with the venv activated (steps
2–3 above).

### Quick start (fully offline, no API key)

```bash
workflow-compiler init --provider mock --yes
workflow-compiler compile examples/order_workflow.md --provider mock --spec-dir ./specs-out
```

That prints a `project_id` **and the exact two commands that finish the run** — `validate`, then
`approve-spec`. Copy them from the output; the generated Temporal bundle lands in
`./generated/<project-id>/<slug>/`.

### The real pipeline

```bash
workflow-compiler compile your_doc.docx --spec-dir ./specs-out   # → one editable spec file per workflow
# ... edit the spec files in any editor ...
workflow-compiler validate <project-id> --spec-dir ./specs-out       # fold edits back in, re-check
workflow-compiler approve-spec <project-id> --spec-dir ./specs-out   # compile through to Temporal code
```

You never have to note the `project_id` down: `compile` (and `validate`) print it along with the
exact next command. `--spec-dir` is any directory you choose — the repo already ships an example
`specs/` from an earlier run, and `specs-*/` is git-ignored, so `./specs-out` keeps your working
tree clean. Generated bundles land under `./generated/<project-id>/<slug>/`.

Other commands: `init` (write `.env`), `edit` (apply an edit-request document to a compiled
project), `approve` / `reject` (manual override for a below-threshold graph), `show`, `models`, and
the `kb …` (knowledge bases) and `cr …` (change requests) families. `workflow-compiler <command>
--help` is the authoritative flag reference; the full command guide is in
[`docs/HOW_IT_WORKS.md` §15.2](docs/HOW_IT_WORKS.md#152-cli-climainpy-typer--rich).

### Providers

`workflow-compiler init` (browser or CLI) writes the provider into `.env`. You can also override
per run with `--provider` / `--model`.

| Provider | Needs | Use it for |
|---|---|---|
| `nemotron` | an NVIDIA API key ([build.nvidia.com](https://build.nvidia.com)) | the default — NVIDIA-hosted models |
| `local` | a reachable eGPU gateway + login | your own gateway only |
| `local-fallback` | both of the above | gateway first, Nemotron when it is unreachable |
| `mock` | nothing | offline smoke tests and demos |

`--force` replaces an existing `.env`; `--env-file` writes somewhere other than `./.env`.
`.env.example` documents every setting — including `WORKFLOW_COMPILER_LLM_MODEL` (the model id
requested from the Nemotron / fallback provider) and `WORKFLOW_COMPILER_STATE_STORE_PATH` (default
`.workflow_state/`, where compiled state is persisted as JSON).

---

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

---

## Business change pipeline — end to end

The knowledge-base → change-request → grounded-code pipeline (phases 0–5) runs from the **Knowledge**
and **Changes** pages in the browser, or the `kb …` / `cr …` CLI families. This is the short
version; the full demo script with ids, timings and screenshots is `docs/kg-plan/RUNBOOK.md`.

1. **Knowledge base** — *Knowledge → Upload and index* the zipped `Existing_KG`
   (`examples/knowledge_bases/order-lifecycle.zip`). With LLM enrichment on (the default) this is
   **one cloud call per file, 22 files, run one after another — expect 25–65 min the first time
   on cloud Nemotron** (measured: 27 min on 2026-08-19, 64 min on 2026-08-25 when one call stalled
   for 28 min before the retry); the page shows `n/22` progress, and a re-index reuses cached
   answers (≈ 5 min). Untick enrichment for a static index in ≈ 5 s. Run the API **without**
   `--reload`. CLI: `workflow-compiler kb init … --enrich`.
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
first, `--keep <id>` to spare the reference KB/CR). Per-phase CLI detail and API routes are in
[`docs/HOW_IT_WORKS.md` §10–§14](docs/HOW_IT_WORKS.md#10-knowledge-bases-kg); the multi-phase plan
lives in `docs/kg-plan/`.

<details>
<summary><b>Per-phase CLI cookbook</b> (knowledge bases, change requests, export, grounded projects, change outputs)</summary>

**Knowledge bases (phase 0)** — a zipped corpus indexed into a graph that later grounds change
requests and specs in the *real* modules, stories and test cases of an existing system:

```bash
python scripts/make_kb_zip.py                       # → examples/knowledge_bases/order-lifecycle.zip
workflow-compiler kb init examples/knowledge_bases/order-lifecycle --no-enrich --id order-lifecycle
workflow-compiler kb ask order-lifecycle "how does dispatch compensate provisioning"
workflow-compiler kb impact order-lifecycle complete_order
```

`--enrich` (the UI default) adds per-file summaries/topics/entities and process clusters through
the selected LLM provider (one call per document/module; cached).

**Change requests (phase 1)** — walk the guided wizard (**Impact → EPIC → Stories → TDD**); each
step asks a few grounded clarifying questions, drafts a markdown artifact grounded in KG retrievals
and a deterministic impact traversal (a "Sources" footer lists the KB files and line spans used),
and lets you revise it in chat, edit it by hand and approve it. Ids (`EPIC-002`, `US-008…`,
`TDD-ORD-002`) come from the KB catalog, assigned by the engine, not the model:

```bash
workflow-compiler cr create order-lifecycle examples/change_requests/BCR-001-partial-shipment-support.docx --provider nemotron
workflow-compiler cr draft <cr-id> impact --auto --out impact.md    # questions answered with the first option
workflow-compiler cr approve <cr-id> impact && workflow-compiler cr draft <cr-id> epic --auto
```

**Word / Excel export (phase 2)** — every artifact as a Word document in the manager's template
style (one file per user story), the impact analysis' affected test cases as a `TC-…xlsx` preview,
and the whole change request as a zip. Deterministic (no model call); exports say `Approved vN` or
`DRAFT vN — not approved`:

```bash
workflow-compiler cr export <cr-id> tdd --format docx --out TDD-ORD-002.docx   # the phase-3 input
workflow-compiler cr export <cr-id> impact --format xlsx                         # TC preview
workflow-compiler cr export <cr-id> --format zip --out change-request.zip
```

The sample output for BCR-001 is `examples/change_requests/TDD-ORD-002.docx`.

**KG-grounded projects + change spec (phase 3)** — compile the TDD **with the knowledge base** and
every extraction prompt sees the graph's real module / activity / state / test names, and the
project gets a second editable file, `changes.md` (the change spec), through the same Save ⇄
Validate ⇄ Resolve ⇄ Approve gate:

```bash
workflow-compiler compile examples/change_requests/TDD-ORD-002.docx --spec-dir ./specs-out \
    --kb <kb-id> --change-request <cr-id>        # writes <slug>.md + changes.md + overview.md
workflow-compiler validate <project-id> --spec-dir ./specs-out   # folds changes.md back in too
```

In the UI: pick *Ground with knowledge base* next to the provider on the home page, or press
**Send to workflow GUI** on an approved TDD in the change-request wizard.

**Post-approval change outputs (phase 4)** — approving a KB-grounded project also produces the
three deliverables the change asked for, built from the knowledge base's real files: updated
Mermaid diagrams, the modified code base with a diff per file (checked with `ast.parse` / ruff),
and the updated test-case matrix + test-plan addendum:

```bash
workflow-compiler approve-spec <project-id> --spec-dir ./specs-out --change-outputs   # chain it
workflow-compiler change-outputs <project-id> --stage code                        # re-run one stage
# → ./generated/<project-id>/change-outputs/{src,tests,docs,changes.patch,CHANGES.md}
```

`GET /projects/{id}/change-outputs/export.zip` is the same bundle (README layout, so the generated
tests run as-is with `temporalio` installed).

</details>

---

## HTTP API

The backend is a FastAPI app; the browser frontend is just one client of it. Start it as in
[Run it in your browser](#4-start-the-backend-api-terminal-1), then reach it directly:

```bash
python -m uvicorn workflow_compiler.api.app:app     # http://localhost:8000 ; docs at /docs
```

It uses local accounts: register once, and a session cookie rides every later call.

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

Full endpoint reference: [`docs/HOW_IT_WORKS.md` §15.3](docs/HOW_IT_WORKS.md#153-http-api-apiapppy-fastapi).

---

## Resolve findings by conversation

Editing spec Markdown by hand is not the only way through the human gate. Open a project's
**Resolve** tab and the compiler asks about what it could not settle from the document — one
plain-language question at a time — and you answer in ordinary prose:

> ⛔ **order-fulfillment › Outputs**
> "Payment Confirmed" is produced but never consumed. Which workflow picks it up?
>
> *— it goes to the shipping workflow, that one kicks off once payment clears*

Each answer is translated into deterministic spec operations and applied **immediately** (the
workflow's patch version bumps per answer), so stopping half way keeps everything you already
answered. Questions are drawn from the validator's blocking and warning findings plus each spec's
unresolved open questions — so run **Validate** first.

Three behaviors worth knowing:

- Related findings are **grouped** into one question rather than asked mechanically.
- A vague answer earns **one** clarifying follow-up, never an interrogation.
- An answer that cannot become a spec change — "ops owns that, not decided yet" — is **recorded as
  a new open question** instead of being discarded.

Because the specs change, validation must run again before approval. The same flow is available
over HTTP (`POST /projects/{id}/dialogue`, then `/dialogue/answer`).

---

## Running a generated bundle

Each generated Temporal bundle is standalone — it needs the Temporal SDK and a local Temporal dev
server (see its own `README.md`):

```bash
pip install temporalio
temporal server start-dev      # terminal 1, leave running
python worker.py               # terminal 2, from the bundle directory
python starter.py              # terminal 3
```

---

## Use as a library

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

---

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

---

## Troubleshooting

- **`pip install` fails resolving the package** — check you are on Python 3.12+ inside the
  activated venv (`python --version`).
- **`ERROR: Directory '.' is not installable. Neither 'setup.py' nor 'pyproject.toml' found.`** —
  you are one level too high. The package is in the clone's `workflow-compiler/` subdirectory:
  `cd workflow-compiler`, then `pip install .`.
- **Backend stuck at "Indexing…" / server keeps restarting** — you ran uvicorn with `--reload`; the
  reloader is watching the extracted corpus. Restart without it (see
  [step 4](#4-start-the-backend-api-terminal-1)).
- **`ModuleNotFoundError: No module named 'workflow_compiler'` from uvicorn** — a bare `uvicorn`
  from another environment. Use `python -m uvicorn …`; check with `where uvicorn` (Windows) /
  `which uvicorn` (macOS/Linux).
- **Frontend can't reach the backend** — the API must be running on port 8000; if you moved it, set
  `NEXT_PUBLIC_API_BASE` in `frontend/.env.local`.
- **`UnicodeEncodeError` on Windows** — the progress output contains Unicode (e.g. `→`); on a
  legacy `cp1252` console run with UTF-8 mode: `set PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8=1`).
  Console-rendering only; generated code is unaffected.
- **`ProviderTimeoutError`** — Nemotron's reasoning models can be slow; bump `--timeout` (e.g. `300`).
- **`.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled`** — allow
  scripts for this shell only: `Set-ExecutionPolicy -Scope Process RemoteSigned`. Alternatives:
  `.venv\Scripts\activate.bat` from `cmd`, or skip activation entirely and call
  `.venv\Scripts\python.exe -m pip install .`.
- **`Filename too long` while cloning on Windows** — clone into a short path (paths in this repo
  reach ~140 characters, and Windows caps at 260), or clone with
  `git clone -c core.longpaths=true <url>`.

---

## Layout

```
src/workflow_compiler/   the package: models, agents, spec layer, graph, codegen, api, cli
frontend/                Next.js web UI
examples/                sample business workflow documents
docs/                    architecture + design docs (start with HOW_IT_WORKS.md)
tests/                   pytest suite (unit + integration)
generated/               example output bundles
```
