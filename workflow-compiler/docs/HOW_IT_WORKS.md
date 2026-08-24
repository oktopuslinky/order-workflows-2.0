# How workflow-compiler Works

This document explains the full system from start to end. You do not need to know the project
before you read it. When you finish, you will know *what* the system does, *why* each part
exists, *how* the parts connect, and *where* each part lives in the code. Read the sections in
order. Each section uses the sections before it.

> If you only want to run the tool, read the [README](../README.md). This document explains the
> "how" and the "why".

## Table of contents

1. [What problem does this solve?](#1-what-problem-does-this-solve)
2. [Glossary](#2-glossary)
3. [The one object that holds everything: `WorkflowState`](#3-the-one-object-that-holds-everything-workflowstate)
4. [The pipeline at a glance](#4-the-pipeline-at-a-glance)
5. [Installation and configuration](#5-installation-and-configuration)
6. [The stages, one by one](#6-the-stages-one-by-one)
   - [Stage 0 — Document ingestion](#stage-0--document-ingestion-parser-no-llm)
   - [Stage 1 — Workflow discovery](#stage-1--workflow-discovery-llm)
   - [Stage 2 — Fact extraction](#stage-2--fact-extraction-llm)
   - [Stage 3 — Graph building](#stage-3--graph-building-deterministic-no-llm)
   - [Stage 3b — Mermaid rendering](#stage-3b--mermaid-rendering-deterministic)
   - [Stage 4 — Review](#stage-4--review-deterministic-no-llm)
   - [The approval gate](#the-approval-gate)
   - [Stage 5 — CVPA classification](#stage-5--cvpa-classification-llm-after-approval)
   - [Stage 6 — Temporal design](#stage-6--temporal-design-llm-after-approval)
   - [Stage 7 — Temporal code generation](#stage-7--temporal-code-generation-deterministic-no-llm-after-approval)
7. [Shared machinery](#7-shared-machinery)
   - [7.1 The LLM layer](#71-the-llm-layer)
   - [7.2 Prompts](#72-prompts)
   - [7.3 State storage](#73-state-storage)
   - [7.4 Editing the graph](#74-editing-the-graph-grapheditor)
   - [7.5 Confidence scores](#75-confidence-scores)
   - [7.6 Errors](#76-errors)
   - [7.7 Configuration and logging](#77-configuration-and-logging)
   - [7.8 The Temporal code-generation layer](#78-the-temporal-code-generation-layer-codegentemporal)
   - [7.9 Progress and observability](#79-progress-and-observability)
   - [7.10 The sequential review pipeline](#710-the-sequential-review-pipeline)
8. [The engine: `WorkflowCompiler`](#8-the-engine-workflowcompiler)
9. [The front-end: `ProjectCompiler`](#9-the-front-end-projectcompiler)
   - [9.1 The parts](#91-the-parts)
   - [9.2 Edit requests](#92-edit-requests)
   - [9.3 Time saved](#93-time-saved)
   - [9.4 Cross-workflow triggers](#94-cross-workflow-triggers)
   - [9.5 Debug surface](#95-debug-surface)
10. [Knowledge bases (`kg/`)](#10-knowledge-bases-kg)
11. [Change requests (`change/`)](#11-change-requests-change)
12. [Document export (`docs_export/`)](#12-document-export-docs_export)
13. [Grounded projects and the change spec](#13-grounded-projects-and-the-change-spec)
14. [Post-approval change outputs (`change_outputs/`)](#14-post-approval-change-outputs-change_outputs)
15. [The three entry points](#15-the-three-entry-points)
    - [15.1 Library](#151-library)
    - [15.2 CLI](#152-cli-climainpy-typer--rich)
    - [15.3 HTTP API](#153-http-api-apiapppy-fastapi)
16. [A worked example](#16-a-worked-example)
17. [Testing strategy](#17-testing-strategy)
18. [How to extend the system](#18-how-to-extend-the-system)
19. [File map](#19-file-map)
20. [Gotchas and "why is it like that?"](#20-gotchas-and-why-is-it-like-that)

---

## 1. What problem does this solve?

Businesses describe their processes in prose. The prose lives in Word documents, PDF files and
wiki pages. For example: *"When a customer submits an order, validate the payment. If it is
valid, the warehouse ships it. If not, cancel the order and notify the customer."*

Prose has no structure. You cannot run it. You cannot draw a reliable diagram from it. You cannot
give it to engineers without a lot of manual translation. **workflow-compiler** does that
translation for you. It reads a business document and produces a chain of artifacts. Each
artifact in the chain has more structure than the one before it, and a machine can use each one.

| Artifact | What it is, in plain words |
|---|---|
| **Workflow metadata** | The title card. It holds the name, the purpose, the people involved, the systems involved, the events that start the workflow, and where the workflow starts and ends. |
| **Workflow facts** | Every single statement pulled out of the prose, sorted into 13 groups (activities, decisions, exceptions, retries, and so on). When the document supports it, the facts also include an **id-linked relational structure**. The structure says *how* the facts connect: which exception each activity raises, which compensation reverses which activity, and which steps run in parallel. |
| **Workflow graph** | A flowchart stored as data. It has nodes (steps) and edges (arrows). The graph is normalized and has no duplicates. |
| **Mermaid diagram** | The graph written as text. You can paste the text into a diagram tool to *see* the graph. |
| **Review report** | An automatic quality check. Examples: "this node cannot be reached", "this decision has no 'no' branch". It also gives a health score. |
| **CVPA classification** | Every step gets one label: **C**apture, **V**alidate, **P**rocess or **A**ctivate. This is a standard way to think about business processes. |
| **Temporal design** | A blueprint for running the workflow on [Temporal](https://temporal.io). It lists activities, signals, retries and compensations. It is a *specification only, not code*. It includes a typed **plan IR** that puts the "categories of action" in order and connects each step's inputs to the workflow input or to the outputs of earlier steps. |
| **Temporal code bundle** | Runnable Temporal Python SDK source files (`shared.py`, `activities.py`, `workflow.py`, `worker.py`, `starter.py`, `README.md`). A deterministic renderer makes them from the design. The LLM never writes this code. |
| **Confidence scores** | How sure the system is about each stage. |

A **human approval gate** sits in the middle of the chain. The system builds and reviews the
structured graph. Then a person approves or rejects the graph. Only after approval does the
system produce the final design artifacts. This rule keeps the expensive outputs (CVPA, Temporal
design, Temporal code) tied to a graph that a person signed off.

---

## 2. Glossary

These terms appear through the whole document. Read them now. Come back to them when you need to.

- **LLM (Large Language Model)** — an AI text model. Here it is NVIDIA-hosted *Nemotron*. The
  system uses the LLM for the "understanding" stages: reading prose and classifying. The system
  **never** uses the LLM where the result must be exact, such as building the graph.
- **Deterministic** — a deterministic step gives the same output every time you give it the same
  input. No model is involved. You can test it without a network.
- **Agent** — a small class that does *one* stage of the pipeline (for example, "extract facts").
  Each agent takes the current state, does its job, and returns the updated state.
- **Pydantic** — a Python library for data models that check their own data. Every artifact is a
  Pydantic model, so the system rejects malformed data early.
- **NetworkX** — a graph library. The graph builder uses it to find unreachable nodes, cycles and
  similar problems.
- **Mermaid** — a text format for diagrams (`flowchart TD ...`). Paste it into
  <https://mermaid.live> to render it.
- **CVPA** — *Capture / Validate / Process / Activate*. A four-phase view of a business process:
  intake → checks → core work → downstream effects.
- **Temporal** — a platform that runs long-lived workflows reliably. The LLM writes a *design*
  (a specification) for it. A deterministic renderer then turns that design into runnable Temporal
  Python code.
- **Plan IR** — the typed intermediate representation inside a Temporal design. It is an ordered
  list of `TemporalStep` "categories of action" (activity, child workflow, signal gate, timer,
  parallel, branch). Each step's inputs are explicitly *bound* to the workflow input or to an
  earlier step's output. The code generator walks this list. This is what makes the generated code
  correct about data flow instead of a guess.
- **Code generator** — a *deterministic* (no-LLM) renderer. It turns the approved Temporal design
  and plan IR into Temporal Python SDK source files through Jinja templates (`codegen/temporal/`).
- **Jinja** — a template language. A template is a file with holes in it. The renderer fills the
  holes with data.
- **WorkflowState** — the single object that moves through the whole pipeline and collects the
  artifacts. **This is the heart of the system.**
- **Provider** — an implementation of the LLM interface. The real provider calls NVIDIA. The
  `mock` provider returns fixed answers for tests.
- **Progress callback** — an optional observer (`ProgressCallback`). The compiler calls it with a
  timed `ProgressEvent` when each step starts and finishes. Callers can show a live "what happens
  now" view without knowing the compiler's internals.
- **Sequential review pipeline** — the *default* quality lever on the LLM stages. The system
  generates **one** canonical output, then improves it with **three review passes in sequence**
  (completeness → grounding → consistency). Each pass emits **minimal patches or `no_change`**,
  never a rewrite. Running it twice gives the same result (it is idempotent). It is on by default.
  See [§7.10](#710-the-sequential-review-pipeline).
- **Patch** — one deterministic edit (`add` / `remove` / `modify` / `merge` / `flag` /
  `no_change`) that a review pass requests. A patch carries its **evidence** from the document. A
  pure *applier* applies the patch; the model never does.
- **Knowledge base (KB)** — a zipped set of documents, diagrams, code and tests from an existing
  system, indexed into a graph. Later stages use it to ground their output in real names and
  files. See [§10](#10-knowledge-bases-kg).
- **Change request (CR)** — a business-change document (a BCR) paired with a knowledge base, and
  walked through a four-step wizard. See [§11](#11-change-requests-change).
- **BCR** — Business Change Request. The document that asks for a change to an existing system.
- **TDD** — Technical Design Document. The last artifact the change wizard produces.
- **EPIC / user story / test case (TC)** — the standard agile units of work: a large goal, the
  small pieces of that goal, and the checks that prove a piece works.
- **Job** — a piece of work that runs in the background on the server. The caller starts it, gets
  an id back at once, and polls for the result.
- **CAS (compare-and-swap)** — a save rule. A writer says "I loaded version N". The store refuses
  the save when the stored version is no longer N. This prevents one writer from silently
  overwriting another writer's work.

---

## 3. The one object that holds everything: `WorkflowState`

Everything turns around one object: `WorkflowState`
(`src/workflow_compiler/models/state.py`). Think of it as **a folder that moves along an
assembly line**. At the start it holds almost nothing (only the document text). Each station on
the line fills in one more field.

The class, with one comment per field that says which stage fills it:

```python
class WorkflowState:
    workflow_id: str            # stable unique id (uuid) — how you look it up later
    document_text: str          # the raw input prose

    workflow_metadata: ...|None # filled by Discovery
    workflow_facts: ...|None    # filled by Fact Extraction
    workflow_graph: ...|None    # filled by Graph Builder
    mermaid_diagram: ...|None   # filled by Graph Builder (re-colored after CVPA)
    review_report: ...|None     # filled by Review
    approval_status: ...         # PENDING → APPROVED / REJECTED  (the human gate)
    cvpa_classification: ...|None  # filled by CVPA (after approval)
    temporal_design: ...|None      # filled by Temporal design (after approval)
    temporal_code: ...|None         # filled by Temporal code generation (after approval)
    confidence_scores: ...|None    # accumulated every stage

    stage: CompilationStage     # where we are: INGESTED → ... → COMPLETED
    created_at / updated_at     # timestamps; touch() bumps updated_at
```

Every field except `document_text` is `None` until its stage runs. The `stage` value records the
progress. The whole object is one Pydantic model. So the system can **write it to JSON, save it
to disk, and load it again later** to continue. This is exactly how the approval gate works
across separate CLI commands or HTTP requests.

The stages, in order (`models/enums.py` → `CompilationStage`):

```
INGESTED → METADATA_EXTRACTED → FACTS_EXTRACTED → GRAPH_BUILT → REVIEWED
         → CLASSIFIED → TEMPORAL_DESIGNED → CODE_GENERATED → COMPLETED   (FAILED on error)
```

The enum also declares a `DIAGRAMMED` value. It is reserved for a future diagram-export stage.
The current pipeline goes from `CODE_GENERATED` to `COMPLETED` directly.

**The readiness checklist.** The system computes this checklist between fact extraction and
graph building. A deterministic `ChecklistValidator` (`checklist/validator.py`) scores the
document against the requirements that `examples/ideal_temporal_workflow.md` satisfies: a
trigger, named inputs, decisions with both branches, bound compensations, and so on. It attaches
the result to `state.checklist`. The spec layer ([§9](#9-the-front-end-projectcompiler)) shows
every item that is not cleared as an **Open Question** in the workflow's spec file. At spec
approval, the user's answers go back in as **deterministic local amendments**
(`checklist/amend.py`). No LLM runs again. A *required* item that is still unmet becomes a
blocking finding.

---

## 4. The pipeline at a glance

The flow, with the LLM stages marked:

```
            ┌─────────── LLM stages ───────────┐
Document ─▶ Parser ─▶ Discovery ─▶ Fact Extract ─▶ Graph Builder ─▶ Review ─▶ [GATE]
 (file)   (no LLM)    (LLM)         (LLM)          (no LLM)        (no LLM)      │
                                                                                │
                                                                  approve ──────┴────── reject
                                                                     │                    │
                                                          CVPA Classify (LLM)       pipeline halts
                                                          + recolor diagram        (status=REJECTED)
                                                                     │
                                                          Temporal Design (LLM)
                                                                     │
                                                          Temporal Code Gen (no LLM)
                                                                     │
                                                                 COMPLETED
```

Three design rules govern the pipeline:

1. **The LLM works where judgment is needed. Deterministic code works where correctness is
   needed.** Reading prose and classifying are LLM jobs. *Building the graph, reviewing it, and
   generating Temporal code are pure functions.* The same input gives the same output, every
   time, with no model.
2. **The gate splits the pipeline.** `compile_document` runs every stage up to and including
   Review, then stops. `approve_graph` runs the rest (CVPA → Temporal design → Temporal code).
   This is what makes the human-in-the-loop real.
3. **The LLM specifies. The generator emits code.** The Temporal *design* stage (LLM) produces a
   specification: names, parameters, policies and a typed plan IR. It never produces source code.
   A separate *deterministic* generator renders the approved design into runnable Temporal Python.

Every stage is observable. The compiler emits timed `start` / `done` `ProgressEvent`s to an
optional `ProgressCallback`. The CLI renders them as a live step log with timestamps.

`WorkflowCompiler` (`src/workflow_compiler/compiler.py`) runs all of this. It is the **engine**.
The user-facing entry point is the spec-centric `ProjectCompiler` front-end
([§9](#9-the-front-end-projectcompiler)). There, the human gate is a set of editable spec files,
and the graph gate above becomes an automatic health-score threshold. `approve` and `reject`
remain as the manual override.

---

## 5. Installation and configuration

Installation and configuration are two steps. A Python wheel cannot run code at install time, so
`pip` cannot write the configuration for you. `init` is a command the user types.

Install the package and create the configuration file:

```bash
# Requires Python 3.12+ (use a virtual environment — see README.md for full steps)
pip install .                    # installs the package + the `workflow-compiler` CLI
workflow-compiler init           # asks for provider + credentials, writes .env
```

Contributors install with `pip install -e ".[dev]"` instead. The `-e` flag keeps the install
pointed at the working tree. The `[dev]` extra adds `pytest`, `ruff` and `mypy` (README §Develop).

`init` asks no questions when you pass `--yes`. CI systems and containers use this form:

```bash
workflow-compiler init --provider mock --yes                       # offline, no key
workflow-compiler init --provider nemotron --nvidia-api-key "$K" --yes
```

`init` accepts these flags: `--provider` (`nemotron` | `local` | `local-fallback` | `mock`),
`--nvidia-api-key`, `--env-file` (default `./.env`), `--force` (replace an existing file), and
`--yes`. The rendering lives in `cli/init_env.py::render_env`. It is a pure function of its
arguments, so the tests check the generated file without a terminal (`tests/test_cli_init.py`).
`init` never checks the credentials against a live provider. It writes the file and names anything
that is still missing.

The result is a `.env` file. `config.py` reads it through `python-dotenv`:

```dotenv
NVIDIA_API_KEY=nvapi-xxxx                 # only needed for the LLM stages
WORKFLOW_COMPILER_LLM_PROVIDER=nemotron   # which provider to use
WORKFLOW_COMPILER_LLM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
WORKFLOW_COMPILER_STATE_STORE_PATH=.workflow_state   # where states are saved as JSON
```

- The system loads `NVIDIA_API_KEY` into the process environment and uses it as a bearer token.
  The system **never logs or prints** the key.
- `Settings` (pydantic-settings, in `config.py`) reads the `WORKFLOW_COMPILER_*` values.
- For offline use and tests, the `mock` provider needs no key.

`get_settings()` is cached (`functools.lru_cache`), so the process reads `.env` once.

---

## 6. The stages, one by one

For each stage, this section gives: **what goes in, what the stage does, how it does it, what
comes out, and where the code is.**

### Stage 0 — Document ingestion (Parser, no LLM)

- **In:** a file path, or raw bytes or a string (`.docx`, `.pdf`, `.txt`, `.md`, `.html`).
- **Out:** a `DocumentContent` object. It holds the normalized plain `text`, the detected
  `document_format`, `metadata` (character and word counts), and `sections`.
- **Code:** `src/workflow_compiler/ingestion/`. `DocumentParserFactory.parse(source)` picks the
  correct parser by file extension, MIME type, or an explicit format. That parser (`DocxParser`,
  `PdfParser`, `MarkdownParser`, `HtmlParser`, `TextParser`) extracts the text.
- **Details worth knowing:**
  - The system detects the text encoding (`encoding.py`, with `charset-normalizer`).
  - Empty or oversized files raise typed errors (`EmptyDocumentError`, `FileValidationError`).
  - Markdown parsing produces readable plain text that **keeps the `#` heading markers**.
    Multi-workflow segmentation slices the document by those markers.
  - Markdown parsing **keeps snake_case identifiers exactly as written**. The parser strips
    emphasis marks only at word boundaries, so `order_id` can never become `orderid`. This
    matters because workflow inputs, outputs and cross-references bind by those field names.

The CLI and the compiler take `content.text` from the parser and put it into a new
`WorkflowState`.

**Why a factory?** The rest of the system never needs to know about file types. It only receives
`text`.

### Stage 1 — Workflow discovery (LLM)

- **In:** `state.document_text`.
- **Out:** `state.workflow_metadata` (name, purpose, actors, systems, trigger events, start and
  end states). Stage → `METADATA_EXTRACTED`.
- **Code:** `agents/discovery.py` → `WorkflowDiscoveryAgent`.
- **How:**
  1. Render the prompt template `prompts/templates/discover_workflow.md` with the document text.
  2. Call `llm.structured(prompt, WorkflowDiscovery, system=...)`. The provider returns JSON. The
     system validates the JSON into the `WorkflowDiscovery` Pydantic schema. The schema is
     permissive: it ignores extra keys, so a slightly wrong model response still parses.
  3. Clean the result into a `WorkflowMetadata`. `_clean_list` strips, de-duplicates and
     lower-cases each list. A missing name raises `CompilationError`.
  4. **Confidence:** the agent blends the model's own confidence with *completeness* (how many of
     the 7 scored fields have a value). The result goes to `confidence_scores.metadata`.
- **Quality lever:** by default the **sequential review pipeline** wraps this agent. The pipeline
  generates the metadata once, then runs three review passes over it (completeness, grounding,
  consistency). The passes fill gaps, drop items with no support in the document, and merge labels
  that mean the same thing. See [§7.10](#710-the-sequential-review-pipeline). This codebase
  discovers one workflow per document, so the "workflow review" passes work on the lists inside
  the metadata.

### Stage 2 — Fact extraction (LLM)

- **In:** `state.document_text`.
- **Out:** `state.workflow_facts`. This is a flat list of `WorkflowFact` objects (each with a
  `statement`, a `category` and a `confidence`), **plus an optional `structure`**
  (`WorkflowStructure`) that holds the relational layer. Stage → `FACTS_EXTRACTED`.
- **Code:** `agents/fact_extraction.py` → `FactExtractionAgent`. The structure models are in
  `models/structure.py`.
- **How:** render `extract_facts.md`, then call `llm.structured(..., FactExtraction)`. The model
  returns **two layers** in one call:
  1. **Flat scalar facts** — `inputs, outputs, rules, apis, systems, timers, retries`. These are
     short statements with no relations between entities.
  2. **Relational structure** — entities that each carry a short **id**, plus relations that
     *refer to those ids*: `activity_nodes {id, name, parallel_group}`,
     `decision_nodes {id, question, after, yes_target, no_target}`,
     `exception_nodes {id, reason, raised_by}`,
     `compensation_nodes {id, name, compensates}`, `event_nodes {id, name, emitted_by}`,
     `transition_edges {source, target, trigger}`.
- **Referential-integrity validation (the guard against hallucination):**
  `WorkflowStructure.validated()` drops every relation that points at an id the model never
  declared. The entity stays, the dangling link becomes null, and the system records a warning.
  The model cannot wire an edge to a node that does not exist. If it tries, the bad link is
  discarded. The validation also drops **state transitions whose endpoints are entity ids**
  (for example `a1 -> a2`). This is a common failure: the model leaks the *step flow* into the
  *state graph*, which would build a junk subgraph that duplicates the real flow. Real
  state-name transitions (`active -> upgrade_in_progress`) are kept. The count of dropped
  references appears in the confidence note.
- **Backward compatibility:** when the relational layer is empty (an old or minimal extraction),
  the agent uses the old flat-list path, and `structure` stays `None`. In both cases the system
  derives the flat `WorkflowFacts.facts` (from the structure when one is present). So every
  downstream consumer (CVPA, Temporal, the CLI summary) keeps working without change.
- **Cleaning:** `_normalize` collapses whitespace. It strips quotes and trailing periods again and
  again until the text stops changing (`"Validate payment".` → `Validate payment`). It removes
  duplicates without regard to letter case.
- **Confidence:** the agent blends the model's own confidence with how many categories have
  values. The result goes to `confidence_scores.facts`. The note records the counts, the
  duplicates removed, and the dangling references dropped.
- **Quality lever:** by default the **sequential review pipeline** wraps this stage (and
  discovery). It generates once, then the completeness, grounding and consistency passes patch the
  facts in place. See [§7.10](#710-the-sequential-review-pipeline).

**Why facts before a graph?** The facts are the *typed building blocks*. The graph builder does
not read the prose again. It works only from these facts. Capturing the **relations** here (not
only the nouns) is what lets the builder wire edges *by meaning* instead of guessing by position.

### Stage 3 — Graph building (deterministic, no LLM)

This is the cleverest part of the pipeline.

- **In:** `state.workflow_facts`.
- **Out:** `state.workflow_graph` (a `WorkflowGraph` of `WorkflowNode`s and `WorkflowEdge`s)
  **and** a Mermaid diagram. Stage → `GRAPH_BUILT`.
- **Code:** `graph/builder.py` → `WorkflowGraphBuilder`. It returns the canonical `WorkflowGraph`
  and a NetworkX `MultiDiGraph` behind it (the review stage uses the second one).

This is a rules engine, not a model. There are **two wiring paths**. The agent chooses one based
on what fact extraction produced.

**Semantic path — `build_from_structure(structure)` (preferred).** When the facts carry a
relational `structure`, the builder places edges by *reading the explicit links*:

- A decision goes **after the activity that its `after` field names**, with its `yes_target` and
  `no_target` branches.
- An exception's error edge starts at the activity that **`raised_by`** names.
- A compensation hangs off the exception of the activity that it **`compensates`**. The builder
  never routes all compensations to the first exception.
- An event is emitted by the activity that **`emitted_by`** names.
- Activities that share a `parallel_group` become a real fork and join.
- An exception with no compensation goes to a terminal node (reject or fail). So it ends the flow
  instead of hanging as a dead end.

Stage 2 already validated the references, so this wiring is grounded. There is no guessing.

**Positional path — `build(facts)` (fallback).** When only flat facts exist (no structure), the
builder cannot know which decision gates which branch. So it pairs the *i-th* activity with the
*i-th* decision, exception and compensation. This is plausible, but it can attach relations to
the wrong step. That is exactly why the relational path exists. The positional path remains for
old and minimal inputs.

The positional `build()` runs these steps:

1. **Categorize** the facts into activities, decisions, events, exceptions, retries,
   compensations and transitions (`_categorize`).
2. **Create the `start` and `end` nodes** (NodeType.START / END).
3. **Turn activities into task nodes** (`activity_1`, `activity_2`, …). An activity whose text
   matches a "parallel" pattern (`in parallel`, `concurrently`, …) is set aside as a *parallel*
   branch.
4. **Build the linear spine:** `start → activity_1 → activity_2 → … → end`, as a list of
   `_EdgeSpec`s.
5. **Weave in parallelism:** when parallel activities exist, insert a `gateway_fork` and a
   `gateway_join` so the parallel tasks split and rejoin (`_weave_parallel`).
6. **Weave in decisions:** each decision becomes a `{diamond}` node. It gets a **`yes`** edge to
   the normal next step and a **`no`** edge to the matching exception (or to `end`). So both
   branches always exist (`_weave_decision`).
7. **Attach exceptions:** a dotted **error** edge goes from the related activity to an exception
   node. When a compensation exists, the route is exception → compensation → end (the saga
   rollback) (`_attach_exception`).
8. **Attach retries:** a **retry** edge goes from an exception back to the activity that it retries
   (`_attach_retry`). Retry and compensation back-edges are *intended* loops. The reviewer does not
   flag them.
9. **Attach events:** trigger-like events (`submit`, `receive`, …) connect
   `start → event → first activity`. Other events are emitted from the last activity
   (`_attach_event`).
10. **Add state transitions:** facts of the form `"A -> B"` create or reuse `state_*` nodes and
    connect them (`_attach_transition`).
11. **Emit:** remove duplicate edge specs, assign stable ids (`e1`, `e2`, …), and drop any edge
    whose endpoints do not exist (`_emit`). Node ids are stable and meaningful (`activity_3`,
    `decision_1`, `exception_1`, `gateway_fork`).

Node and edge *types* come from `enums.py`: `NodeType` (START / END / TASK / DECISION / GATEWAY /
EVENT / …) and `EdgeType` (SEQUENCE / CONDITIONAL / ERROR / RETRY / COMPENSATION / SIGNAL / …).
The `WorkflowGraph` model enforces one invariant: **node ids must be unique** (Pydantic checks
it).

- **Confidence:** based on how many structural fact categories are present. More kinds of facts
  give a higher score. The result goes to `confidence_scores.graph`.

### Stage 3b — Mermaid rendering (deterministic)

- **Code:** `graph/mermaid.py` → `to_mermaid(graph)`.
- The output is a `flowchart TD`. The *shape* of a node shows its type: `(["Start"])` for start,
  end and events; `{"Valid?"}` for decisions; `{{"Fork"}}` for gateways; `["Task"]` for tasks.
  Dotted arrows (`-.->`) show error, retry, compensation and signal edges. `-->|label|` shows
  labeled edges.
- **Two correctness rules.** Both were real bugs. Both are now permanent fixes:
  - `end` is a **reserved word in Mermaid**. `_safe_id` rewrites any node id that collides with a
    reserved word (`end` → `end_node`), so the diagram renders.
  - Edge labels use the **bare** `|label|` form, not a quoted form. Characters that break the
    parser (`"`, `|`, newlines) are neutralized.

### Stage 4 — Review (deterministic, no LLM)

- **In:** `state.workflow_graph`.
- **Out:** `state.review_report` (a `ReviewReport`). Stage → `REVIEWED`,
  `approval_status = PENDING`.
- **Code:** `graph/review.py` → `GraphReviewer.review(graph)`, wrapped by
  `DefaultReviewManager`.
- **What it checks.** Each check produces a `ReviewIssue` with a severity and an optional
  suggested fix:
  - a missing start or a missing end (errors),
  - isolated or disconnected nodes, orphan nodes (no incoming edge), dead ends (no outgoing edge),
  - unreachable subgraphs (no path from start),
  - duplicate nodes (the same normalized label),
  - decisions with a missing branch,
  - **unintended cycles**. Retry and compensation loops are intentional, so the reviewer does
    *not* flag them.
- **Scoring:** a `health_score` in `[0,1]`. Each issue lowers the score by a weight that depends
  on its severity (CRITICAL 0.5, ERROR 0.25, WARNING 0.05). A `confidence` value shows the
  fraction of the graph that is reachable. Convenience properties expose `.errors`, `.warnings`
  and `.suggested_fixes`.

### The approval gate

After Review, `compile_document` **stops** and saves the state with
`approval_status = PENDING`. Nothing downstream runs yet. A person now looks at the graph, the
diagram and the review, and decides:

- **Approve** → the system runs CVPA → Temporal design → Temporal code generation (below), and
  sets `COMPLETED`.
- **Reject** → the system sets `approval_status = REJECTED`, records the reason in the report
  summary, and **halts**.

Two separate operations implement the gate: `approve_graph` and `reject_graph`. Each one *loads
the saved state by id*, acts, and saves again. So the gate can span separate CLI commands, HTTP
requests, and even separate processes.

### Stage 5 — CVPA classification (LLM, after approval)

- **In:** `state.workflow_graph`.
- **Out:** `state.cvpa_classification`, plus a **re-colored** Mermaid diagram. Stage →
  `CLASSIFIED`.
- **Code:** `agents/cvpa.py` → `CVPAClassifierAgent`.
- **The rule that must hold:** *every node belongs to exactly one phase* — Capture, Validate,
  Process or Activate. The LLM proposes the assignments. The agent then **reconciles** them so the
  rule always holds:
  1. Serialize the graph to compact text. Ask the LLM (`classify_cvpa.md`) for
     `{node_id, phase, rationale, confidence}` for each node.
  2. Keep only valid assignments (a known node id and a phase that parses). When a node has two
     assignments, keep the one with the higher confidence.
  3. **Fill in every node the model missed** with a fallback based on node type
     (START/EVENT → Capture, DECISION/GATEWAY → Validate, TASK/SUBPROCESS/TIMER → Process,
     END/SIGNAL → Activate). These get a lower confidence and a clear "Fallback by node type"
     rationale.
  4. Build a summary for each phase.
- **Confidence:** the agent blends the mean confidence per node with the share of the coverage
  that came from the model rather than from the fallback. The result goes to
  `confidence_scores.cvpa`.
- **Re-coloring:** the agent calls `to_mermaid_with_cvpa(graph, classification)` and replaces
  `state.mermaid_diagram`. That renderer emits Mermaid `classDef` and `class` statements, so each
  node gets the color of its phase: **Capture = blue, Validate = amber, Process = green,
  Activate = purple**, Unclassified = grey. This is the "go back and color the diagram" step.

### Stage 6 — Temporal design (LLM, after approval)

- **In:** `state.workflow_graph` + `state.cvpa_classification` + `state.workflow_facts`.
- **Out:** `state.temporal_design` (a `TemporalWorkflowDesign`). Stage → `TEMPORAL_DESIGNED`.
- **Code:** `agents/temporal.py` → `TemporalGeneratorAgent`.
- **What it generates.** The output is an architecture **specification only. It is never
  executable code.** It has two layers:
  - **Declarations** — a workflow name and task queue; typed `workflow_inputs`; **activities**
    (with typed parameters, outputs, a result type, timeouts and retry policies); **signals**
    (waits for a person or an external system); **queries** (state while the workflow runs);
    **child workflows** (subprocesses); **timers** (SLAs and deadlines); **compensation
    activities** (saga rollbacks that name the activity they undo); and a default retry policy.
  - **Plan IR (`plan`)** — an ordered list of `TemporalStep` "categories of action"
    (`activity` / `child_workflow` / `signal_gate` / `timer` / `parallel` / `branch`). Each step
    carries `bindings` that take every input from the **workflow input**, an **earlier step's
    output**, or a **constant** (`BindingSource`). Each step has a `result_name` so later steps
    can use its result. `parallel` and `branch` steps nest child steps in `lanes`. This IR is the
    explicit control flow and data flow that the code generator walks. When the model omits it,
    the generator builds a linear plan from the declarations in graph order (backward
    compatibility).
- **How:** render `design_temporal.md` with the graph, the CVPA result and the **facts** text.
  The facts text is included so that retries, timeouts, compensations and inputs and outputs
  *come from the document* and are not guessed. Call `llm.structured(..., TemporalDesignOutput)`.
  Then **normalize**: names become PascalCase; empty entries and zero-duration timers are dropped;
  retry values are clamped to valid ranges; unknown step kinds and binding sources become safe
  defaults; and the workflow name falls back to the metadata name when the model omits it.
- **Confidence:** the agent blends the model's own confidence with the completeness of the design.
  The result goes to `confidence_scores.temporal`.
- **No-code guarantee:** the design models have no field that could carry source code. A test
  asserts that `code`, `body` and `implementation` fields do not exist. The system prompt also
  forbids SDK code. The *separate, deterministic* Stage 7 produces the runnable code. So the rule
  "the LLM specifies, templates emit code" holds.

### Stage 7 — Temporal code generation (deterministic, no LLM, after approval)

- **In:** `state.temporal_design` (required) + `state.workflow_graph` (used for ordering when the
  plan IR is absent).
- **Out:** `state.temporal_code` (a `TemporalCodeBundle` of `GeneratedFile`s). Stage →
  `CODE_GENERATED`. The compiler then marks the run `COMPLETED`.
- **Code:** `agents/temporal_code.py` → `TemporalCodeGeneratorAgent` (a no-LLM agent, like the
  graph builder). It delegates to `codegen/temporal/generator.py` →
  `TemporalPythonCodeGenerator`.
- **How it works.** Like the graph builder, this is a renderer, not a model. It walks the design's
  **plan IR** and emits the body of `@workflow.run` *in Python code* (where unit tests can check
  it). Jinja templates render the file skeletons around that body, plus the simple signal, query,
  timer and child declarations. For each step kind:
  - **activity / child_workflow** → `await workflow.execute_activity(...)` or
    `execute_child_workflow(...)`. The generator builds the typed input dataclass and binds each
    field from its `InputBinding` (workflow input → `arg.<field>`; step output → that step's
    result variable; constant → the dataclass default). The result is stored in `result_name`.
  - **signal_gate** → `await workflow.wait_condition(lambda: self._<signal>_received)`. When the
    design declares a timer that pairs with the signal (the step's explicit `timer` reference, or
    the one timer that shares a meaningful name token, such as `carrier.picked_up` ↔
    `CarrierPickupTimeout`), the wait is **bounded**: `wait_condition(..., timeout=<TIMER_CONST>)`.
    So a signal that never arrives raises `TimeoutError` and fires the saga compensations instead
    of blocking forever. Only a gate with no timer to pair with stays unbounded. That gate gets an
    explicit TODO.
  - **timer** → `await workflow.sleep(<TIMER_CONST>)` with the declared duration.
  - **parallel** → concurrent calls through `asyncio.gather(...)`. The workflow template imports
    `asyncio` only when a parallel step is present. The result of each lane is **captured by
    position** from the gather, so a later step can bind to it. No result is discarded, so there
    is no `NameError`.
  - **branch** → a real `if/else`. When the design bound the branch to a data dependency, the
    code branches on that expression (`if bool(<expr>):`). When the predicate is a simple
    comparison whose identifier resolves to a known step result or workflow input
    (`eligibility == 'eligible'`), the generator **emits the real condition as code**
    (`should_x = eligibility == 'eligible'`). Only when neither resolves does it emit an explicit
    placeholder flag (`should_<predicate> = True  # TODO`). The flag is named and has a comment.
    It is never a silent `if True`. It defaults to the main (then) path, so the stub bundle runs
    out of the box.
  - **Saga compensation** — every activity that has a registered compensation appends
    `(comp_fn, comp_input)` to a `compensations` list. This includes activities **inside a
    parallel group** (registered after the gather succeeds). The compensation input comes from the
    compensation's own `bindings`, so a `release` or `reverse` receives the id it must undo, not an
    empty dataclass. On any exception, the `@workflow.run` body fires the compensations **in
    reverse order** before it raises the exception again. It retries each one with the workflow's
    default retry policy and sets `self._status = "compensated"`. Compensations match their
    activity by normalized (PascalCase) name, so a difference in letter case does not break the
    link.
- **The emitted bundle** is six files, written in this order:
  1. `shared.py` — the input dataclasses.
  2. `activities.py` — `@activity.defn` stubs that log and **return a typed placeholder** with a
     `# TODO`. Because of this, `python worker.py` plus `python starter.py` run the workflow from
     start to end out of the box. Replace the placeholder with real logic.
  3. `workflow.py` — `@workflow.defn` with the generated run body, signals and queries.
  4. `worker.py` — registers the workflow and the activities on the task queue.
  5. `starter.py` — a client that starts one execution.
  6. `README.md` — run instructions.

  The files use **flat, absolute imports** (`from activities import ...`). You run each one
  directly from inside the package directory. This matches the Temporal Python docs, so you need
  no package install and no `PYTHONPATH`. See `docs/TEMPORAL_CODEGEN_FINDINGS.md` for the standard
  this satisfies, and for the earlier hallucinations that this design prevents.
- **Confidence and notes:** the agent records `"<n> files for package '<name>'"` in
  `confidence_scores.notes`.

---

## 7. Shared machinery

Every stage relies on the parts in this section.

### 7.1 The LLM layer

The single most important architecture rule: **agents depend only on the abstract
`BaseLLMProvider` interface** (`interfaces/llm.py`). They never depend on a concrete vendor. The
interface has three methods: `complete`, `structured` and `embed`.

The class hierarchy, from the abstract interface down to the concrete providers:

```
BaseLLMProvider (abstract: complete / structured / embed)
        ▲
HttpChatProvider (llm/base.py) — retries, timeouts, JSON extraction, schema validation, logging
        ▲
OpenAICompatibleProvider (llm/providers/openai_compatible.py) — OpenAI-style wire format
        ▲
NemotronProvider (llm/providers/nemotron.py) — NVIDIA base URL, model, "detailed thinking off"
GatewaySessionProvider (llm/providers/gateway.py) — local eGPU gateway; email+password session auth
                                       (login → cookie/bearer, expiry refresh, 401 re-login),
                                       model discovery via /auth/config

FallbackProvider (llm/providers/fallback.py) — composite: try the local gateway (primary), fall back
                                       to Nemotron on unreachable/timeout/HTTP-5xx; auth/4xx errors
                                       surface. Implements BaseLLMProvider directly.

MockProvider (llm/providers/mock.py) — returns queued/canned responses (no network), implements the
                                       same interface directly. Used everywhere in tests.
```

**`HttpChatProvider.structured(prompt, schema)`** is the workhorse. Every LLM agent uses it. It:

1. appends the target JSON Schema to the prompt and asks for JSON only,
2. POSTs the chat request (with retries),
3. extracts JSON from the reply (`json_utils.extract_json` tolerates stray prose and code
   fences),
4. validates the JSON into the Pydantic `schema`,
5. on failure, **asks again** up to `structured_retries` times, and gives the validation error
   back to the model. If it still fails, it raises `SchemaValidationError`.

**Reliability** lives in `chat()` plus `retry_async` (`llm/retry.py`): exponential backoff with
jitter. It retries only on timeouts, connection errors and configured HTTP statuses.

**Auth:** `_auth_headers` adds `Authorization: Bearer <key>` from a `SecretStr`, so the key
cannot print.

**Provider selection** is data-driven through `ProviderFactory` (`llm/factory.py`). Providers
register under a name: `nemotron` (default), `local`, `local-fallback`, `openai-compatible`,
`mock`. `factory.from_settings()` builds the provider that `.env` names. **Adding a new vendor
never touches agent or compiler code.** You register a builder.

**Local eGPU gateway with fallback (opt-in).** `local-fallback` makes a local gateway the primary
LLM and Nemotron the automatic safety net.

- The gateway (`GatewaySessionProvider`) speaks the OpenAI chat format, but it authenticates with
  an **email and password** (`LLM_GATEWAY_EMAIL` / `LLM_GATEWAY_PASSWORD`). It logs in when it
  first needs to, sends the session as a bearer token, refreshes before expiry, and logs in again
  once on a 401.
- `FallbackProvider` sends each call to the gateway. Only on `ProviderConnectionError`,
  `ProviderTimeoutError` or an HTTP 5xx does it retry on Nemotron. It remembers "down" for a short
  time. Auth failures and other 4xx errors surface. They are not masked.
- Model discovery reads the gateway's public `/auth/config` (no auth). It is exposed through
  `workflow-compiler models`, `GET /providers/local/models`, and the frontend picker. The
  per-compile `model` selection works by injecting a provider built with that local-model
  override.

**Why Nemotron has a "detailed thinking off" preamble.** Nemotron "super" models are reasoning
models. Left alone, they emit long chains of thought. Those chains slow the call down and pollute
the JSON output. The preamble keeps responses fast and clean.

### 7.2 Prompts

`prompts/templates/*.md` holds every prompt: `discover_workflow`, `discover_workflows`,
`extract_facts`, `classify_cvpa`, `design_temporal`, plus the review and validator pass prompts.
Only LLM stages have templates. Graph building, Mermaid rendering and code generation are
deterministic and have no prompt.

Each file has YAML front matter that declares its `variables`.
`PromptManager.render("classify_cvpa", workflow_graph=...)` loads the template (and caches it)
and fills in the variables (`prompts/loader.py`, `renderer.py`, `manager.py`). You can edit a
prompt without a code change.

### 7.3 State storage

`interfaces/state_store.py` defines `StateStore` (`save` / `load` / `exists` / `delete` /
`list_ids`). There are two implementations (`storage/`):

- **`FileStateStore`** writes each state as `<root>/<workflow_id>.json`. Writes are **atomic**
  (write a temp file, then `replace`), so a crash cannot corrupt a file. Blocking I/O runs in a
  thread through `asyncio.to_thread`. This is the default. The root comes from
  `WORKFLOW_COMPILER_STATE_STORE_PATH`.
- **`InMemoryStateStore`** is a dict. It deep-copies on save and load, so stored state cannot
  change through a shared reference. Tests use it.

A missing id raises `StateNotFoundError`. This store is *why* `compile` (request 1) and
`approve` (request 2, possibly in a different process) can work together: the state lasts between
them.

**Store-boundary guards (Phase 5 hardening, `storage/ids.py`).** Every file-backed store
validates the id or slug **before** it builds a path. This covers workflow states, projects
(`storage/project_store.py`), users, change requests (`storage/change_store.py`), knowledge bases
(`kg/store.py`), and the generated-bundle directory (`execution/bundles.py::bundle_dir`). The
allowed pattern is `[A-Za-z0-9_-]{1,128}`. Anything that looks like a path (`..`, separators,
drive letters) is refused as `StateNotFoundError`. An id that cannot exist must look the same as
an id that does not exist. The check must never reveal whether the input would have resolved.
Export filenames built from document or model text (`BCR-001`, `TP-ORD-001`, labels) go through
`docs_export/artifacts.py::safe_filename_part`. Zip uploads were already safe against zip-slip
(`kg/ingest.py`).

**Compare-and-swap on save (opt-in).** `CompilationProject`, `KnowledgeBase` and
`ChangeRequest` carry an integer `version`. The store bumps it on **every** save. Old records
read as version 0. A writer may pass `expected_version=` to `save(...)`. When the stored version
is different, the store refuses the save with `StaleWriteError` (HTTP **409** — *"changed since
it was loaded … reload and retry"*). It does not silently overwrite another job's or another
tab's write. Writers that pass nothing keep last-write-wins behavior (the CLI, background jobs,
older clients).

Over HTTP the token travels in one of two ways: as `expected_version` in the body, or as an
`If-Match: "N"` header. The header accepts `W/"N"` and a bare `N`; `*` means no check; a
non-integer is a 400. The routes that accept it are `PUT /projects/{id}/spec`,
`PATCH /projects/{id}` and `PUT /change-requests/{id}/artifacts/{kind}`. The routes
`GET /projects/{id}`, `GET /knowledge-bases/{id}` and `GET /change-requests/{id}` answer with
`ETag: "N"`, and the version is also in the body (and in the project summaries). The frontend
always sends the token. On a 409 it shows a *Reload the latest version* action.

Passwords are still scrypt-hashed. Hashing and verification now run in a worker thread
(`asyncio.to_thread`), so a login cannot stall the event loop.

### 7.4 Editing the graph (`GraphEditor`)

A reviewer may want to fix the graph before approval. `review/editor.py` → `GraphEditor` offers
six **pure, validated** operations: `add_node`, `remove_node` (also drops the edges that touch
it), `rename_node`, `modify_node_type`, `add_edge` (assigns the next `eN` id and validates the
endpoints), and `remove_edge`. Each one returns a **new** validated `WorkflowGraph`. An invalid
edit raises `GraphEditError` instead of corrupting the state. The integration tests show a
reviewer editing a graph, and the change surviving a save and reload.

### 7.5 Confidence scores

`models/confidence.py` → `ConfidenceScores` holds one float in `[0,1]` per stage (`metadata`,
`facts`, `graph`, `cvpa`, `temporal`, `overall`) plus a `notes` dict. Each agent writes its own
score through `model_copy(update=...)`, so the scores build up and do not overwrite each other.

### 7.6 Errors

`exceptions.py` is a typed hierarchy under `WorkflowCompilerError`: parsing errors
(`UnsupportedFormatError`, `EmptyDocumentError`, …), `CompilationError`, `ApprovalError`,
`GraphEditError`, `StateNotFoundError`, and LLM errors (`ProviderTimeoutError`,
`ProviderHTTPError`, `SchemaValidationError`, …). The API maps these to HTTP codes
([§15.3](#153-http-api-apiapppy-fastapi)).

### 7.7 Configuration and logging

`config.py` (pydantic-settings, `.env`) provides `Settings`. `logging.py` sets up Loguru and
Rich. Logs never include the API key.

### 7.8 The Temporal code-generation layer (`codegen/temporal/`)

This is the deterministic partner of the LLM Temporal-design agent. It follows the graph
builder's rule: no model, pure function.

- **`generator.py` → `TemporalPythonCodeGenerator`** owns the Jinja `Environment` over the
  bundled `templates/`. It uses `StrictUndefined`, so a missing template variable fails loudly.
  It also owns the `_RunBodyEmitter`, which walks the plan IR and produces the `@workflow.run`
  body in Python. Helpers: `_snake` and `_pascal` make safe identifiers; `_retry_expr` and
  `_timeout_expr` render `RetryPolicy(...)` and `timedelta(...)` expressions; `_synthesize_plan`
  builds a linear plan (in topological order over the graph's forward "backbone" edges) when the
  design has no plan IR.
- **`templates/*.jinja`** — `shared.py.jinja`, `activities.py.jinja`, `workflow.py.jinja`,
  `worker.py.jinja`, `starter.py.jinja`, `README.md.jinja`. The workflow template inserts the
  emitted `run_body`. It imports `asyncio` only when a parallel step is used. The templates emit
  *file skeletons and simple declarations*. The complex control-flow and data-flow body is emitted
  in Python (in `generator.py`), because that is the part worth unit-testing.

The agent wrapper (`agents/temporal_code.py`) plugs the generator into the pipeline. You can also
use the generator on its own: `to_temporal_python(design, graph=...)`.

**Why split the Python-emitted body from the Jinja skeletons?** The risky logic (data threading,
saga rollback, gather and branch) lives where tests can run it directly. The boilerplate lives in
templates, where it is easy to read and change.

### 7.9 Progress and observability

`compiler.py` defines a small observer protocol. Any caller can watch the pipeline run live
without reaching into its internals.

- **`ProgressEvent`** (a frozen dataclass) carries: `phase` (`"agent"` / `"review"` /
  `"approve"`), `name`, `status` (`"start"` / `"done"`), a 1-based `index` and `total` inside its
  sub-pipeline, and, on `"done"`, the elapsed `seconds` and the resulting `stage`.
- **`ProgressCallback`** is a `Callable[[ProgressEvent], None]`. You pass it to
  `compile_document` or `approve_graph`. The compiler wraps every call in `_emit`, which
  **swallows observer exceptions**. So a broken progress sink can never break a compilation.
- `_run_agents` emits a timed `start` / `done` pair around each agent. The review and approve
  steps emit their own events. The CLI's `_make_progress()` renders these as lines with
  timestamps (`12:34:58 OK 2/3 temporal-generator  1.42s -> temporal_designed`). It uses ASCII
  markers (`>>` / `OK`), so the output is safe when piped on Windows (cp1252) consoles.
- **Nested sub-steps.** Before `_run_agents` runs an agent, it gives any agent that exposes a
  `set_progress(report)` hook a **nested sub-reporter**. `ReviewPipelineAgent` uses it to emit a
  `phase="review-pass"` `start` / `done` pair around its canonical generation (`generate`) and
  each review pass (`review:completeness`, `review:grounding`, `review:consistency`). The CLI
  renders these **indented under the parent agent** with a quieter marker. So a live run shows the
  review pipeline's internal stages, for example `> 2/4 review:grounding  0.71s`, and not one
  opaque line. The agent stays decoupled from `ProgressEvent`: it calls
  `report(name, status, index, total, …)`, and the compiler's `_sub_reporter` builds the event.

### 7.10 The sequential review pipeline

This is the **default** way the LLM stages raise their accuracy. The review pipeline follows a
compiler discipline: **generate one canonical output, then improve it with three specialized
review passes.** It never regenerates the artifact. Each pass emits only **minimal patches or
`no_change`**.

**The three passes** (`agents/review_pipeline.py` → `ReviewPass`) run in order. Each one feeds
the next:

1. **completeness** — add workflow elements that are *explicitly in the document but missing*
   from the output (allowed action: `add`). No renaming. No inference.
2. **grounding** — `remove` or `flag` any element that the document does *not explicitly
   support*. Only text evidence counts. Implied business knowledge never counts.
3. **consistency** — `merge` duplicates and labels that mean the same thing; `modify` to a
   canonical label or to fix a relation. This pass invents no new elements.

**Patches, not rewrites** (`models/patch.py`). A pass returns a `ReviewResult` of `Patch`es. Each
patch is an `add` / `remove` / `modify` / `merge` / `flag` / `no_change` and carries `Evidence`
(a quote, a section, and offsets where practical). The model proposes. A **deterministic
`PatchApplier`** decides, and applies each patch as a pure function. `MetadataPatchApplier` edits
the single `WorkflowMetadata` (the "workflow discovery" artifact; this codebase extracts one
workflow per document, so the workflow-review passes work on its lists: actors, systems,
triggers, states). `FactsPatchApplier` edits the `WorkflowFacts` plus the relational
`WorkflowStructure`.

**Grounded and idempotent by construction.** The applier drops any `add` that duplicates an
existing element (without regard to letter case) or that fails a reference-free grounding check
(a quote substring, or majority token overlap against `document_text`). After it applies the
patches, `FactsPatchApplier` runs `WorkflowStructure.validated()` again, so a patched relation can
only point at a *declared* entity. The net effect: running a pass again over an artifact that was
already reviewed yields `no_change`. That is the defining property the passes guarantee.

**A generic framework.** A `ReviewSpec` binds a stage to the engine (extract / serialize /
apply-to-state, plus the three prompt names and the applier). `ReviewPipelineAgent` wraps the
inner generator agent, runs it once, then runs the three passes. It records per-pass provenance
("completeness: 1 applied, 2 dropped; …") in `confidence_scores.notes[<stage>_review]`. To add a
review pipeline for a future stage (Mermaid, Temporal), you add a new spec and three prompts. The
engine does not change.

**Prompts:** `prompts/templates/review_{workflow,facts}_{completeness,grounding,consistency}.md`.
Each one documents its pass's responsibility and allowed actions.

**Precedence and default.** The pipeline is on by default (`--review` /
`WORKFLOW_COMPILER_REVIEW_ENABLED`). For each stage the compiler chooses **review → plain**: the
review pipeline runs on any stage where it is enabled; otherwise the plain agent runs.

**The honest boundary.** The passes raise grounding and consistency. They cannot certify that the
meaning is true. A misreading that the generator and all three reviewers share survives. The
human spec gate remains the oracle. Flagged elements are what a reviewer should examine.

**Cost note.** Review adds three LLM calls in sequence per reviewed stage. It is on by default
because those calls are cheap compared to a wrong graph reaching the human gate. Disable it with
`--no-review`.

---

## 8. The engine: `WorkflowCompiler`

`compiler.py` ties everything together. The constructor wires the collaborators. Anything you do
not inject gets a default.

The constructor and the convenience builder:

```python
WorkflowCompiler(
    llm_provider=...,          # injected; agents use it via the abstract interface
    agents=[...],              # default: [Discovery, FactExtraction, GraphBuilder]
    post_approval_agents=[...], # default: [CVPAClassifier, TemporalGenerator, TemporalCodeGenerator]
    review_manager=...,        # default: DefaultReviewManager (graph reviewer + gate)
    state_store=...,           # default: FileStateStore
    review=...,                # ReviewConfig; default-on sequential review of discovery+facts (§7.10)
)
# Convenience builder used by the CLI and API:
WorkflowCompiler.from_settings()   # provider + file store straight from .env
```

Its methods:

- **`compile_document(text, *, review_mode=True, persist=True, workflow_id=None, progress=None)`**
  runs the pre-review agents in order, reviews, sets `PENDING` / `REVIEWED`, saves, and
  **returns (it stops at the gate)**. With `review_mode=False` it approves automatically and runs
  the whole pipeline in one call (useful for automation). `progress` receives the live
  `ProgressEvent`s.
- **`approve_graph(id, *, reviewer=None, persist=True, progress=None)`** loads the saved state,
  approves it, runs the post-approval agents (CVPA → Temporal design → Temporal code) through the
  shared `_finalize_approval`, marks `COMPLETED`, and saves.
- **`reject_graph(id, *, reviewer, reason)`** loads the state, marks it `REJECTED` with the
  reason, and saves. No LLM is needed.
- **`review_graph(id)`** refreshes the review report of a stored workflow.
- **`save_state` / `load_state` / `list_states`** are thin pass-throughs to the store.

One detail is worth knowing. The gated path (`approve_graph`) and the automated path
(`compile_document(review_mode=False)`) both call the same `_finalize_approval(state)` helper.
So they produce identical downstream results. The automated path only skips the reload from disk.

---

## 9. The front-end: `ProjectCompiler`

Everything above describes the classic single-document pipeline. That pipeline is unchanged. But
**large documents that describe several workflows** cause a problem: every stage reasons about
the whole document at once, and quality drops. A second orchestrator, `ProjectCompiler`
(`project_compiler.py`), adds a *spec-centric* front-end on top of the engine.

The flow, with the spec gate in the middle:

```
Document ─▶ Segmentation ─▶ per-workflow Discovery+Facts ─▶ one WorkflowSpec per workflow
         ─▶ spec .md files on disk      [SPEC GATE: the user edits ⇄ `validate`]
         ─▶ approve-spec ─▶ per workflow: Graph ─▶ auto-review ≥ threshold ─▶ CVPA
                            ─▶ Temporal design ─▶ Temporal code
```

### 9.1 The parts

**Segmentation** (`agents/segmentation.py` → `WorkflowSegmentationAgent`). One LLM call lists
*every* distinct workflow, the document sections that belong to each one, and any
**output→input dependencies** between workflows (`prompts/templates/discover_workflows.md`). The
same three-pass review discipline improves the result (completeness / grounding / consistency,
with a deterministic `SegmentationPatchApplier`). Deterministic code then slices the document per
workflow. So fact extraction sees **only the text of its own workflow**. This scope isolation is
the reason the front-end exists. A single-workflow document yields one segment that holds the
full text. This is the classic path's behavior, unchanged.

**The project aggregate** (`models/project.py` → `CompilationProject`). It holds the document
text, the segments, one `WorkflowSpec` per workflow, typed `CrossReference`s, the spec approval
status, and a `ProjectStage` (`INGESTED → WORKFLOWS_DISCOVERED → SPEC_DRAFTED → SPEC_VALIDATED →
SPEC_APPROVED → COMPILING → COMPLETED | NEEDS_ATTENTION`). `storage/project_store.py` saves it
under `<state-root>/projects/`. `WorkflowState` stays the per-workflow unit. It only gained an
optional `project_id` back-link.

**The spec is the source of truth. Markdown is a projection.** `WorkflowSpec` (`models/spec.py`)
bundles the metadata and the facts and structure with review lists: assumptions, ambiguities,
**open questions** (the readiness checklist, shown as fill-in questions), and suggested edits.
Each element carries **provenance**: `document_grounded`, `llm_inferred` or `human_provided`.
`spec/renderer.py` renders the spec to a Markdown file with a strict grammar. `spec/ingest.py`
parses edits back **deterministically** and merges them onto the existing model (ids are kept,
fields that are not rendered survive, and `WorkflowStructure.validated()` runs again). A test
asserts that the round trip is the identity. This is what keeps the compiled graph a pure function
of what the human approved, with no LLM between the gate and the graph.

**The edit ⇄ validate loop.** `validate_specs` reads the edited files and runs three review passes
over each spec *against the original document* (`spec/validator.py`,
`prompts/templates/review_spec_*.md`). The applier is **provenance-aware**: it removes
machine-extracted elements that have no support, but it converts a `remove` aimed at a
*human-provided* element into a finding ("please confirm"). The validator challenges human
additions. It never deletes them. Findings land in `project.validation_findings` and in the
re-rendered files.

**Approval → the unchanged back-end.** `approve_spec` requires the user to confirm the
cross-references (checkboxes). It folds the answered open questions in through the existing
deterministic `checklist/amend.py`. It seeds one `WorkflowState` per spec. That state's
`document_text` is the **rendered spec**, so the CVPA and Temporal prompts see the normalized
artifact instead of the raw document. Then it calls `WorkflowCompiler.compile_prepared`. The old
human graph gate becomes a **threshold gate**: when the review `health_score` is at least
`settings.graph_health_threshold` (default 0.9), the workflow is approved automatically and runs
CVPA → Temporal design → code. Below the threshold, the workflow stays `PENDING` (the classic
`approve <workflow-id>` is the manual override), and the project is marked `NEEDS_ATTENTION`.

### 9.2 Edit requests

Edit requests change compiled workflows later. `edit_specs` applies a structured **edit-request
document** (`docs/EDIT_FORMAT_GUIDE.md`):

1. `spec/edit_ingest.py` parses the skeleton deterministically. It fails fast on an unknown slug,
   an unknown block, or the reserved split/merge syntax. All of this happens before any LLM call.
2. `agents/edit_interpreter.py` translates the natural-language bullets of each section into an
   `EditPlan` (`models/edit.py`: `Patch`es plus typed `TriggerOp` / `XrefOp` wiring operations).
3. `spec/edit_applier.py` applies the plan with **human authority**
   (`SpecPatchApplier(human_authority=True)`). Adds need no grounding (they become
   `human_provided`). Removals are honored, even for human-provided or referenced elements
   (dangling references are pruned).

The edit is **atomic**. It works on a deep copy. Any unresolved entry or patch that cannot be
applied aborts the whole edit. The error names the dropped operations. One exception: an add whose
value is already present is skipped as satisfied, with a summary line. On success the system bumps
each edited spec's version, appends an `EditRecord` to `project.edit_log` (the audit trail), and
resets the stage to `SPEC_DRAFTED`. So the normal validate → approve-spec gate runs again over the
changed specs. `## Add Workflow:` bodies run through the standard discovery and facts pipeline,
and are appended to `document_text` so the grounding passes can see them. `## Remove Workflow:`
drops the spec and every trigger and dependency that touches it.

**Preview → confirm.** `preview_edit` dry-runs the same pipeline. It saves nothing. It returns the
would-be summary and diff, plus a `ResolvedEdit` blob: the interpreted plans, the drafted
add-workflow specs, the measured timings, and a fingerprint over the project state and the
document. Confirming (`edit_specs(resolved=...)`, or `POST /projects/{id}/edit` with `resolved`)
replays those plans with **no LLM call**. So what applies is exactly what was previewed. Any
project change in between makes the fingerprint stale (`EditPreviewStaleError` → HTTP 409 →
preview again). The CLI's `edit --dry-run` prints the same preview, and simply interprets again on
the real run.

### 9.3 Time saved

Each pipeline step's wall-clock seconds accumulate in `project.stage_timings`. `metrics.py`
compares them against the configurable `baseline_hours` human-team **estimates** (one per step
category: discovery / spec / validate / compile / edit). The result is `time_saved` on project
responses and the `GET /metrics/summary` aggregate that the web UI shows. No recorded timings
means no claimed savings.

**The commands.** CLI: `compile <doc> --spec-dir <dir>` → edit the files →
`validate <project-id>` → `approve-spec <project-id>` (code lands under
`./generated/<project-id>/<slug>/`). Later changes: `edit <project-id> <edit-file.md>` (add
`--dry-run` to preview) → `validate` → `approve-spec`.

HTTP: `POST /projects/compile`, `GET/PUT /projects/{id}/spec`, `POST /projects/{id}/edit` (plus
`/edit/preview`), `POST /projects/{id}/validate`, `POST /projects/{id}/approve`,
`GET /metrics/summary`. All project and workflow routes sit behind local-account cookie auth
(`/auth/register`, `/auth/login`, `/auth/me`). Projects are shared across users by default, with
`owner_id` kept for attribution. Set `WORKFLOW_COMPILER_PROJECTS_SHARED=false` to scope listings
and access to each project's `owner_id`.

### 9.4 Cross-workflow triggers

Sometimes one workflow starts another ("if the application is approved, provisioning begins").
This relationship compiles to an **explicit trigger between independent workflows**. It is never
a Temporal child workflow. The full path:

1. **Discovery.** Segmentation extracts explicit triggers (source, target, condition, mode) next
   to the data dependencies. Deterministic assembly turns both into `WorkflowTrigger` scaffolds.
   A data dependency contributes a typed `input_map` row to the trigger of its pair.
2. **Review.** Triggers render in the **Triggers** section of each source workflow's spec. A
   checkbox means confirmed; ``when `…` `` is the predicate; indented `input` lines are the typed
   hand-off. They round-trip through ingest like everything else.
3. **Validation (deterministic, no LLM).** An unknown target, or an `input_map` field that the
   target does not declare, is `BLOCKING`. A type mismatch, an unconfirmed predicate, or a blocking
   trigger with no result binding is a `WARNING`. `validate` exits with a non-zero code on
   blocking findings, and `approve-spec` refuses while they remain.
4. **Design.** Approval copies the slug's triggers to `WorkflowState.outgoing_triggers` and
   injects `TriggerNode`s into the structure (graph: `NodeType.TRIGGER`). The design agent
   deterministically appends `TemporalTriggerDesign` declarations and plan `TRIGGER` steps. A
   conditional trigger becomes a `BRANCH` whose then-lane holds the trigger step.
5. **Codegen.** The *source* bundle gains `triggers.py`: one activity per target. The activity
   connects a client (`TEMPORAL_ADDRESS`) and calls
   `client.start_workflow("<TargetType>", payload, id=<deterministic business key>,
   task_queue=<target queue>, id_conflict_policy=USE_EXISTING)`. In blocking mode the activity
   also does `await handle.result()`. The workflow body calls it through
   `workflow.execute_activity(...)`.

**The Temporal limits that this design answers:**

- Workflow code may not start another workflow (it is non-deterministic). So the start lives in
  an activity.
- `get_external_workflow_handle` can only signal or cancel a workflow that already runs. So a
  start is always done by a client.
- Activity retries could start the target twice. A deterministic workflow id plus `USE_EXISTING`
  removes the duplicate.
- A blocking trigger's activity stays open for the whole run of the target. So it gets a generous
  `start_to_close_timeout` (1 h). For targets that run longer, prefer fire-and-forget plus a
  callback signal (a documented future upgrade).

Targets stay byte-identical whether or not anything triggers them. Every workflow always starts
on its own through its own `starter.py`.

### 9.5 Debug surface

Every generated workflow tracks `self._current_step`, `self._decisions_taken`
(`{branch, predicate, taken}` per branch) and `self._triggers_fired`. Read-only queries expose
them: `current_step` / `decisions_taken` / `triggers_fired`. They do no I/O and read no clock, so
they are safe in production. The always-generated `test_stepthrough.py` runs the bundle under
`WorkflowEnvironment.start_time_skipping()` with the stub activities (trigger activities are
mocked) and prints those queries. Run it to see exactly which branch a conditional takes. To gate
each step by hand, set `WORKFLOW_COMPILER_STEPWISE=1`: every top-level plan step then waits for an
`advance` signal (`wait_condition` plus a signal, so determinism is kept).

---

## 10. Knowledge bases (`kg/`)

> **Change pipeline map:** [§10 knowledge bases](#10-knowledge-bases-kg) →
> [§11 change requests](#11-change-requests-change) →
> [§12 document export](#12-document-export-docs_export) →
> [§13 grounded projects + `changes.md`](#13-grounded-projects-and-the-change-spec) →
> [§14 change outputs](#14-post-approval-change-outputs-change_outputs).
> Hardening (store guards, compare-and-swap): [§7.3](#73-state-storage).
> Routes: [§15.3](#153-http-api-apiapppy-fastapi). CLI: [§15.2](#152-cli-climainpy-typer--rich).
> End-to-end demo script: `docs/kg-plan/RUNBOOK.md`.

A **knowledge base** is a zipped corpus (business documents, Mermaid diagrams, source code,
tests) turned into a Context Hub graph. Later phases use the graph to *ground* change requests
and specs in the real modules, activities, stories and test cases of an existing system. Phase 0
of the KG change pipeline (`docs/kg-plan/`) ships this foundation: upload → index → query.

**Engine.** `kg/contexthub/` is a vendored subset of the KG-Context / Context Hub project
(`model/`, `bootstrap/`, `retrieval/`). `kg/contexthub/VENDORED.md` lists the pinned SHA and
every local edit. It is untyped upstream code, excluded from `mypy --strict`. The app never imports
it outside `workflow_compiler.kg`.

**Façade.** `kg/service.py::KgService(store, provider_factory)` is the only surface the rest of
the app uses:

| Method | What it does |
|---|---|
| `create_from_zip(name, bytes)` / `create_from_path(name, dir)` | Safe extraction into `<state-root>/knowledge_bases/<kb_id>/corpus/` (`kg/ingest.py`: rejects zip-slip and symlinks, caps size and file count, strips one top-level folder). Saves the record with `status="ingesting"`. |
| `index(kb_id, enrich, provider, model, progress)` | Runs `init_repo(corpus, out=…/.contexthub)` in a worker thread. The static ingest is instant. With `enrich`, each Document and Module gets one LLM call (summary, topics, entities) plus a clustering pass, through the app's own `BaseLLMProvider` via `kg/llm_bridge.py::ProviderJsonClient`. Results are cached by content hash under `.contexthub/llm_cache/`. Records `stats` (nodes and edges by type), the business-id `catalog` (Epic / UserStory / TestCase / Requirement ids), and `status="ready"` — or `failed` plus `error`. |
| `retrieve(kb_id, prompt, budget, max_hops)` | BM25 anchors → bounded traversal → file spans, returned as a `KgPacket` (`rendered` text for prompts, `sections`, `files` with line spans, `coverage`, `low_confidence`). |
| `impact(kb_id, seeds, max_hops)` | Deterministic BFS over dependency-shaped edges (`DEPENDS_ON`, `CALLS`, `IMPORTS`, `IMPLEMENTS`, `RELATES_TO`, `DOCUMENTED_BY`, …; `CONTAINS` only downwards from file nodes). Seeds may be node ids or search terms. Rows are ordered by hops, then by id. |
| `search`, `catalog`, `graph_summary`, `list_files`, `read_file` | Debug and UI surfaces. `read_file` is safe against path traversal and extracts text from docx, xlsx and pdf. |

Node ids are relative to `corpus/` and use POSIX separators
(`mod:existing_Codebase/workflows/order_workflow.py`, `doc:Business_Docs/epics/EPIC-001-….docx`,
`US-003`, `TC-05`, `BR-02`). So a graph built on Windows resolves anywhere. Ids that cross the
store boundary are validated against `[A-Za-z0-9_-]+`.

**Jobs.** Indexing runs as a `kb_ingest` background job. `JobManager` is keyed by `scope_id` plus
`scope_kind` (`project` | `knowledge_base`). `project_id` stays as an alias, so existing callers
are unchanged. Jobs carry a `progress` (`message`, `done`, `total`) that the worker updates per
file.

**Config.** `kg_enrich_default` (True), `kg_retrieve_budget` (4000), `kg_max_upload_mb` (50). KB
routes take `provider` / `model` per request, like `/projects/compile`. The default is cloud
Nemotron on purpose: enrichment is one call per file, and it must not land on the single-GPU
gateway without being asked.

**Example corpus.** `examples/knowledge_bases/order-lifecycle/` is an exact copy of the manager's
`Existing_KG` (BRD, EPIC-001, US-001..005, TDD, test plan, TC matrix, three Mermaid diagrams, the
Temporal `OrderWorkflow` code and tests). `scripts/make_kb_zip.py` zips it.
`examples/change_requests/BCR-001-partial-shipment-support.docx` is the change request that the
later phases consume.

---

## 11. Change requests (`change/`)

> **Change pipeline map:** [§10](#10-knowledge-bases-kg) → **§11** →
> [§12](#12-document-export-docs_export) → [§13](#13-grounded-projects-and-the-change-spec) →
> [§14](#14-post-approval-change-outputs-change_outputs).

A **change request** pairs a business-change document (a BCR `.docx`, or Markdown or text) with
a knowledge base. A deterministic wizard walks it through four steps: **Impact → EPIC → Stories →
TDD**. Before each draft the wizard asks a few clarifying questions. Each step produces one
versioned Markdown artifact, grounded in knowledge-graph retrievals and a deterministic impact
traversal. This is Phase 1 of the KG change pipeline (`docs/kg-plan/`).

**Reading the BCR (no LLM).** `change/bcr.py` parses three things:

- the metadata block (`Document ID`, `Status`, `Requested By`, `Date Raised`, `Target Workflow`);
- the numbered requirements (`BCR-01-03 | text` rows, or `ID — text` lines);
- the *seed terms* for the impact traversal: file names such as `types.py`, identifiers such as
  `complete_order`, `TDD §4.3`-style references, `PARTIALLY_*` states, and `US-` / `TC-` /
  `EPIC-` ids.

The document itself goes through the normal `DocumentParserFactory`.

**Ids come from the catalog, never from the model.** `change/ids.py` reads
`KgService.catalog(kb_id)`, which lists the ids present in the corpus. The catalog now includes
document ids (`KbCatalog.documents`, found by regex in the ingest extracts). The module mints the
next free ids: `EPIC-002` after `EPIC-001`, `US-008…` after `US-001..007`, `TDD-ORD-002` after
`TDD-ORD-001`, and `TC-18` for Phase 4. The drafting prompts receive the ids in the brief, and
the engine overwrites whatever the model returns.

**The wizard** (`change/engine.py::ChangeWizardEngine`). For each step:

1. `start_step` — the `ChangeAnalystAgent` drafts 2–5 clarifying questions, each with grounded
   suggested options.
2. `answer` — each prose answer becomes one line in the brief. The wizard asks at most **one**
   follow-up, like the Resolve dialogue. An answer that cannot be mapped is recorded as written.
   `skip` skips the question.
3. `draft` — the engine assembles the **brief**: the BCR text, the requirements, the assigned ids,
   the requester's decisions, the deterministic `impact()` table, de-duplicated KG retrievals for
   every requirement, seed-term group and a few step-specific queries (capped at
   `change_kg_budget` tokens), and every artifact already drafted. Then: agent plan → engine
   post-processing → `change/render.py`.
4. `revise` — a chat instruction. The agent edits the Markdown. The result must still parse.
5. `edit` — a human edit of the Markdown, saved as a `human_edit` version.
6. `approve` — the cursor advances. Approving the last step completes the change request.

"Draft now" is allowed at any time after the start. Pending questions are marked skipped. A later
step cannot be drafted before the previous step is approved. An earlier step can be drafted again
(this makes a new version that needs approval again). Long TDD answers are drafted in four chunks
of sections, and stories in batches of three, because one long Nemotron JSON answer is not
reliable.

**Artifacts** (`models/change.py`, `change/render.py`, `change/parse.py`). Each artifact keeps a
full history (`llm_draft` | `llm_revision` | `human_edit`). It renders to Markdown whose headings
mirror the manager's reference documents:

| Artifact | Heading structure |
|---|---|
| Impact analysis | Numbered like a BCR: Change Summary, Requirements Assessment, Affected Components table, Impact on Existing Design, Risks & Assumptions, Open Decisions, and a deterministic knowledge-graph appendix. |
| EPIC | Unnumbered sections: `Epic Statement / Business Value / In-Scope Capabilities / Definition of Done / Story Map / Non-Functional Requirements / Dependencies / Risks`. |
| User stories | One `## US-00N: Title` section per story, each with `### Story` (As / I want / so that), `### Acceptance Criteria` (checkable Given… lines) and `### Notes`. |
| TDD | Keeps TDD-ORD-001's `## N. Title` / `### 4.x Title` sections, each with an **Existing** and a **Proposed** part. |

Every artifact ends with a `## Sources` footer (the KB files and line spans the brief was
grounded on). It carries a retrieval-coverage note when coverage is low. `parse.py` reads all
four artifact kinds back (round-trip tests). A human edit or revision that loses the title heading
is rejected with a 400.

**Façade and storage.** `change/service.py::ChangeRequestService(store, kg_service,
provider_factory)` mirrors `ProjectCompiler`: load → engine → save on every call. So a cancelled
job leaves the previous state in place. `storage/change_store.py` saves
`<state-root>/change_requests/<cr_id>.json` with the same id validation as the KB store.
Questions, drafts and revisions run as `cr_questions` / `cr_draft` / `cr_revise` jobs
(`JobManager` scope kind `change_request`). `answer` is one short synchronous call. Approving a
step starts the next step's `cr_questions` job automatically. The provider and model are chosen
per change request (cloud Nemotron by default) and stored on its wizard.

**Config and surfaces.** `change_kg_budget` (9000 tokens of KG excerpts per brief). CLI:
`cr create|list|show|draft [--auto]|approve|export|delete`. UI: the **Changes** page (list plus
new) and the wizard page (a stepper and chat on the left; the artifact editor with versions,
approve, Sources and Export on the right). Word and Excel export: [§12](#12-document-export-docs_export).

---

## 12. Document export (`docs_export/`)

> **Change pipeline map:** [§10](#10-knowledge-bases-kg) → [§11](#11-change-requests-change) →
> **§12** → [§13](#13-grounded-projects-and-the-change-spec) →
> [§14](#14-post-approval-change-outputs-change_outputs).

Markdown stays the source of truth. `docs_export/` projects the **parsed** artifacts
(`change/parse.py` → `ImpactDoc` / `EpicDoc` / `StoriesDoc` / `TddDoc`) into files that look
like the manager's reference documents. The export is fully deterministic: no model call, and
identical input yields identical bytes (`docs_export/package.py` pins the OOXML timestamps). So
exports can be cached, diffed and asserted in tests.

| Module | Role |
|---|---|
| `docx_writer.py` | `DocxWriter` over python-docx. Title: 22 pt bold `2F5496`. Subtitle: 14 pt. A bold `Label: value` block between thin rules. Word *Heading 1/2/3*. *List Paragraph* `•` bullets and real `1.` numbering. Tables with a `2F5496` header row (white bold, `tblHeader`) and `FFFFFF` body cells. `☑  ` / `☐  ` checklists. Consolas `AA3377` inline code. Boxed code blocks. A callout with a left bar. Body font Times New Roman 10 pt (this is what Word renders for the reference files, whose styles carry no font defaults). |
| `markdown_to_docx.py` | A converter for our artifact grammar: headings, paragraphs, bullets, `1.` lists, `- [ ]` / `- [x]`, pipe tables with `<br>` / `\|`, code fences, `> notes`, `**Label:** value`, inline `` `code` `` / `**bold**` / `*italic*`. Used for free-text bodies and as a whole-document fallback. |
| `xlsx_writer.py` | The test-case matrix. Sheet **Test Cases**: `TC ID \| Title \| Preconditions \| Steps \| Expected Result \| Type \| Automated \| Linked Story/Req \| Notes`, Arial 10, `2F5496` header, frozen panes and autofilter. Sheet **Summary**: title, Linked TDD / Epic / Automation, *Totals by Automation Status*, *Totals by Type* in the reference vocabulary order, Notes. Totals are literal numbers. `read_test_case_rows` reads a matrix back. |
| `artifacts.py` | The layout for each kind. **Impact**: title "Impact Analysis", `BCR-001 — title` subtitle, numbered H1s, KG appendix and Sources annexes. **EPIC**: title `EPIC-002`, unnumbered H1s, a callout statement, ☑/☐ DoD, tables. **User story**: one file per story (`US-00N: Title`, meta, Heading 2 only — Story with a bold subject / Acceptance Criteria ☐ / Notes). **TDD**: "Technical Design Document (TDD)", `N. Title` H1s, `4.x` H2s, *Existing* / *Proposed* as Heading 3. **TC preview**: the affected test cases from the impact analysis. When the knowledge base holds the original matrix, the Title / Preconditions / Steps / Expected / Type / Automated columns are merged in and the change note is appended; otherwise the Title carries the impact rationale. Entry point: `export_artifact(cr, kind, "docx"\|"md"\|"xlsx")`. |
| `bundle.py` | `export_change_request(cr) -> zip`: `Impact-Analysis-BCR-001.docx`, `EPIC-002-<slug>.docx`, one `US-00N-<slug>.docx` per story, `TDD-ORD-002-<slug>.docx`, `TC-preview-BCR-001.xlsx`, `markdown/*.md` sources, `MANIFEST.txt`. |

**Approval labels.** Every export carries an `Export:` metadata line: `Approved vN (date)` or
`DRAFT vN — not approved`. Drafts also say so in the subtitle and get a `-DRAFT` filename
suffix. The bundle skips artifacts that were not drafted and lists them in the manifest. The
`docx` export of the stories artifact is a zip with one document per story, which mirrors the
reference layout. `ChangeRequestService.export` / `export_bundle` add the KB lookup for the TC
preview (`KgService.read_bytes`). The CLI is `cr export <cr-id> <step> --format md|docx|xlsx
[--out]` and `cr export <cr-id> --format zip`. The UI shows `.docx` / `.md` (/ `.xlsx`) buttons on
the artifact panel, and **Export all (.zip)** in the wizard header.

---

## 13. Grounded projects and the change spec

> **Change pipeline map:** [§10](#10-knowledge-bases-kg) → [§11](#11-change-requests-change) →
> [§12](#12-document-export-docs_export) → **§13** →
> [§14](#14-post-approval-change-outputs-change_outputs).
> Code: `kg/grounding.py`, `spec/change_*.py`, `models/change_spec.py`.

This is the "upload the TDD to the workflow GUI" half of the change pipeline. A workflow project
compiled **with a knowledge base** (`kb_id`, and optionally the `change_request_id` whose approved
TDD the document is) differs from a plain compile in exactly two ways. When the ids are absent,
nothing differs: `grounder=None` renders every prompt byte for byte as before, and the 664
pre-Phase-3 tests are untouched.

**1. Grounded prompts.** `kg/grounding.py::KgGrounder(kg_service, kb_id)` retrieves a `KgPacket`
for the text that is about to be analysed. The `grounding_query` is the document's identifiers
(the same seed extractor the change request uses), followed by a slice of prose. The grounder
renders the packet as a self-contained block: *"KNOWLEDGE-GRAPH CONTEXT — prefer these real
names / paths"*. The `discover_workflows` (segmentation), `discover_workflow`, `extract_facts`
and `design_temporal` prompts carry it as an **optional** `{{ kg_context }}` variable
(`optional:` in the front matter; the renderer defaults it to `""`).
`ProjectCompiler.compile_document(..., grounder=)` passes the block for the whole document to
segmentation, and per segment to fact extraction (`WorkflowCompiler.extract_facts(kg_context=)` →
`WorkflowState.kg_context`). `approve_spec` grounds each seeded state again, so the
Temporal-design prompt sees the same names. Retrieval is cached per text. It never raises into the
pipeline: a broken graph degrades to an ungrounded compile. The files and spans of the packets
accumulate into `project.grounding` (`ProjectGrounding{kb_name, change_request_title, sources,
coverage, low_confidence, requirement_ids}`). This is the visible provenance behind the UI's
*Grounded by ‹KB› · from ‹CR›*. The `discover_workflows` prompt also carries a hint: a TDD's state
machine and activities table define **one** workflow with sub-steps per group, not one workflow
per design section (plan Phase 3 design note).

**2. A change spec.** `agents/change_spec.py::ChangeSpecAgent.extract(tdd_text, kg_context,
impact_table, seed_components, requirement_ids)` (prompt `extract_change_spec.md`) returns a
`models/change_spec.py::ChangeSpec`:

```
ChangeSpec{
  components: [ComponentChange{
    name,
    kind: module|activity|workflow|type|signal|query|test|diagram|doc,
    path (KG node id / file),
    existing, proposed,
    change_type: modify|add|remove|verify,
    requirement_ids, provenance
  }],
  assumptions, open_questions, sources, version
}
```

When a change request is linked, `change/spec_seed.py` seeds the components from its approved
impact analysis (the `AffectedItem` rows plus the TDD's Existing / Proposed section texts). The
request's requirement ids are the only ids the model may cite. The deterministic
`KgService.impact` table over the document's identifiers goes into the prompt too. Cleaning is
deterministic: kind and change-type coercion, de-duplication, provenance = `document_grounded`
when the name occurs in the document, and the seeds are kept when the model returns nothing.

The spec is stored on `CompilationProject.change_spec` (plus `kb_id`, `change_request_id`).
`spec/change_renderer.py` renders it to **`changes.md`**: `# Change Spec` → `## Grounding`
(read-only) → `## Components` with one `### name — kind, change [marker]` block per component,
`- path:` / `- requirements:` bullets and `#### Existing` / `#### Proposed` free text →
`## Assumptions` → `## Open Questions` → `## Sources` (read-only). `spec/change_ingest.py` folds
edits back: it matches by `kind:name`; changed text becomes `human_provided`; a new heading is a
new human component; a missing heading means removed. `render → ingest(None) → render` is the
identity, and every field, provenance included, round-trips.

`spec/change_validator.py` runs no model. **An empty Proposed section is BLOCKING.** A `path`
that `KgService.resolve_ref` cannot find (node id, file path or suffix, `fn:` symbol) is a
WARNING with `KgService.search` suggestions. A requirement id that the change request does not
declare is a WARNING. Findings land in `validation_findings["__changes__"]` (`CHANGES_SLUG`,
never a workflow slug).

**The same gate.** `changes.md` travels through every existing door:

- `ProjectCompiler.spec_markdown` lists it with the workflow files
  (`ProjectResponse.spec_markdown`, the CLI's spec dir, `write_spec_files` / `read_spec_files`).
- `PUT /projects/{id}/spec` and `validate` fold it in (`markdown_by_slug["__changes__"]`).
- `approve_spec` validates it again and **refuses on a BLOCKING change finding unless
  `accept_incomplete`** (WARNINGs never block).
- The Resolve dialogue drafts questions from its findings and open questions
  (`draft_change_questions.md`). A prose answer becomes deterministic `ComponentUpdate`s
  (`interpret_change_answer.md` → `dialogue/change_ops.py`: modify carries only the changed
  fields; add / remove; resolve open questions; one version bump). An answer that cannot be mapped
  parks as a human-provided open question, with at most one follow-up. `agenda_fingerprint` /
  `has_anything_to_ask` include the change spec, so pre-drafting stays correct.

**Ingress.** `POST /projects/compile` and `/projects/compile-upload` take `kb_id?` /
`change_request_id?`. A request implies its KB. A different explicit KB is a 422. An unindexed KB
is a 409. `POST /change-requests/{id}/send-to-workflow {provider?, model?, nickname?}` compiles the
**approved** TDD Markdown (409 otherwise) with both ids. It defaults the provider to the wizard's
(else cloud Nemotron), links the new project into `cr.project_ids`, and runs synchronously like
`/projects/compile`. CLI: `compile … --kb <id> [--change-request <id>]` writes `changes.md` into
the spec dir. UI: the home page's *Ground with knowledge base* selector; the wizard's **Send to
workflow GUI** button (approved TDD only); and, in the Spec tab, `changes.md` as a second file
with its own grammar highlighting, a change-spec summary in the right rail, findings under its
entry, and the *Grounded by …* header (grammar: `frontend/SPEC_GUIDE.md`, guide page →
*changes.md*).

---

## 14. Post-approval change outputs (`change_outputs/`)

> **Change pipeline map:** [§10](#10-knowledge-bases-kg) → [§11](#11-change-requests-change) →
> [§12](#12-document-export-docs_export) → [§13](#13-grounded-projects-and-the-change-spec) →
> **§14**.

This is the last leg of the change pipeline (plan Phase 4, decisions D3 / D10). Once a
knowledge-base-grounded project is **approved and compiled**, it produces the three deliverables
the business change asked for: updated diagrams, modified code with a diff, and test documents.
Each one is built from the knowledge base's *actual* files, not from scratch.

The record is `change_outputs/models.py::ChangeOutputs`, stored on
`CompilationProject.change_outputs`:

```
ChangeOutputs{
  diagrams: [UpdatedDiagram{name, kind: state|sequence|architecture|state-partial|workflow,
                            original, updated, notes, source_path, checks}],
  code: CodeChangeBundle{files: [ChangedFile{path, status: modified|added|removed|unchanged,
                                             original, updated, unified_diff,
                                             checks{ast_ok, ruff_ok?, repaired, truncated}, reason}],
                         order, import_root, code_root},
  tests_doc: TestDocUpdate{test_cases: [TestCaseRow], changed_ids, new_ids,
                           test_plan_addendum_md, …},
  system_flow_md, provenance, warnings, timings, stages
}
```

**Engine.** `change_outputs/engine.py::ChangeOutputsEngine(agent, kg, load_state=,
build_diagrams=, grounder=)` runs three stages in order: `diagrams → code → tests_doc`. It
**saves after every stage** (and after every rewritten file), so a timeout keeps what finished. A
failed stage is recorded as `failed`, the run continues, and at the end the engine raises
`ChangeOutputsError`. A cancellation saves nothing of the stage that was in flight. Every stage
follows the rule *the LLM drafts, code decides* (`agents/change_outputs.py::ChangeOutputsAgent`,
prompts `update_diagrams.md`, `rewrite_source_file.md` (plus `continue_source_file.md` and
`repair_source_file.md`), `update_test_cases.md`). Each prompt sees the rendered `changes.md`,
the approved Temporal design (`design_summary`), the workflow spec, a KG grounding block and the
TDD text. The change spec is **consumed, never extracted again**.

**Stage 1: Diagrams** (`change_outputs/diagrams.py`). Every `.mmd` in the corpus is regenerated
(D10), plus the companion diagrams that the change spec adds
(`order-state-machine-partial-shipment.mmd`). The model returns a `DiagramUpdatePlan`.
Deterministic checks run per diagram: the Mermaid header is present; every **required state** is
named (`expected_states` = the states of the original diagram plus the multi-segment
`UPPER_SNAKE` tokens the change spec proposes, for example `PARTIALLY_PROVISIONED`); `subgraph`
and `end` are balanced; braces and sequence blocks are balanced. There is **one repair round**:
the failures are quoted back, and the better version per diagram wins. Remaining failures are
recorded on `UpdatedDiagram.checks` and in `warnings`. A diagram the model does not return keeps
its original. `assemble_system_flow` rebuilds `system-flow-diagram.md` with the original numbered
H2 sections (updated Mermaid inside), the per-workflow spec diagram(s) from
`ProjectCompiler.build_diagrams` as the next section (D10), and the new companion diagrams after
it.

**Stage 2: Code** (`change_outputs/code.py`). `plan_rewrites(change_spec, corpus .py texts)`
decides the **rewrite set deterministically**:

- Files that a component's `path` or `name` resolves to (`fn:` / `mod:` node ids, corpus paths or
  suffixes, without regard to letter case). A *new* activity, signal or query with no path lands
  in the activities or workflow module.
- **Plus every file that imports a rewritten module.** The worker, the starter and the tests
  follow the modules they register. Imports resolve with the corpus's own package alias
  (`src.shared.types` ↔ `existing_Codebase/shared/types.py`).
- The rest is copied `unchanged`.

The order is topological over the import graph. Ties are broken by the plan order
types → activities → workflow → worker/starter → tests. So each prompt carries the **signatures
of the files already rewritten** (`signature_summary`, an `ast` outline).

Each file is requested as **one fenced code block through `llm.complete(max_tokens=8192)`**. A
whole Python file inside JSON is what long-context models truncate. An unclosed fence is continued
(at most twice, with the overlap trimmed). Then every deterministic check runs:

- `ast.parse`;
- dataclass sanity (`dataclass_problems`);
- the presence of the change spec's symbols;
- imports against the rewritten siblings (`missing_imports`, including imports nested in
  `with workflow.unsafe.imports_passed_through():` and `try:` blocks);
- names used in `@workflow.query/signal/run` and `@activity.defn` annotations that are only
  defined below the class or under `TYPE_CHECKING` (`late_annotation_names`; Temporal evaluates
  those hints at import time);
- ruff's pyflakes-class rules.

Then **up to N targeted repair rounds** run (`change_outputs_repair_rounds`, default 2; the CLI
and API pass the setting through `ProjectCompiler`). Each round gives the model *all* the
verdicts that still fail, and checks again after the round (`FileChecks.repair_rounds` /
`.problems` record what each round was asked to fix). After that, well-known undefined names are
imported automatically and deterministically (`auto_import`, including the corpus's own exports).
A **keep-style** pass (`code.py::normalise_style`) restores the original file's conventions when
the model drifted: PEP 585/604 generics (`List[...]` → `list[...]`, `Optional[X]` → `X | None`,
`from typing import` trimmed) and two blank lines between top-level blocks. It runs only when the
original followed those rules (`style_normalised` pill).

After the last file, a **bundle smoke test** (`change_outputs/smoke.py`, `change_outputs_smoke`,
default on) writes the export layout to a temp directory and runs one child interpreter
(`change_outputs_smoke_python`, default: the server's). The child `py_compile`s every file and
imports every module in bundle order. The verdict (`CodeChangeBundle.smoke`: passed / failed /
skipped, with errors per module) is saved and shown. It is a verdict about the draft, never a
gate.

Other rules: diffs are `difflib.unified_diff`. A `module` component with `change_type: remove`
marks the file `removed`. A model that returns no code leaves the file `unchanged` with a
warning. The rewrite prompt pins the Temporal Python SDK surface the model may use:
`@activity.defn` takes no `retry_policy`; `RetryPolicy` goes on `execute_activity`; no new
`str`-Enum result fields (the default converter decodes them as lists of characters, which is also
why the reference corpus's own tests fail in a fresh environment; see the RUNBOOK).

**Stage 3: Test documents** (`change_outputs/tests_doc.py`). The corpus's TC matrix (the first
`.xlsx` that `read_test_case_rows` understands), the test plan (`.docx` text), and the outline of
the rewritten test module go into `update_test_cases.md`. The model proposes **new rows without
ids** and field-level **updates** to existing rows. The engine numbers the new rows from the KB
catalog (`TC-18…`), applies the updates without dropping anything (notes are *appended*), and
renders the addendum Markdown deterministically (`render_addendum`: §3.2 out-of-scope removals,
§3.1 / §4.2 / §4.4 additions, new and updated TC tables, deliverables, exit criteria, risks). The
Phase 2 writers produce the `.xlsx` (`export_matrix_xlsx`, the full matrix plus Summary) and the
addendum `.docx` (`export_addendum_docx`, reference look).

**Export** (`change_outputs/export.py`). `export_zip` uses the corpus README layout, so the bundle
imports as the code expects and the generated tests run as they are: `src/…` (the code package),
`tests/…`, `docs/diagrams/mermaid/*.mmd` plus `docs/diagrams/system-flow-diagram.md`,
`docs/test-cases/<TC matrix>.xlsx` plus `<TP>-addendum-<BCR>.docx/.md`, `changes.patch` (the
combined diff), and a `CHANGES.md` index (stages, checks per file, new and updated TC ids,
sources, warnings). The zip is byte-stable for identical outputs.

**Pipeline, API, CLI and UI.**

- `ProjectCompiler.generate_change_outputs(project_id, stages=)` requires `kb_id` and a compiled
  workflow. `approve_spec(..., change_outputs=True)` chains it inline (CLI:
  `approve-spec … --change-outputs`; the bundle is unpacked under
  `<out-dir>/<project-id>/change-outputs/`). `workflow-compiler change-outputs <project-id>
  [--stage all|diagrams|code|tests_doc]` runs stages again.
- In the API, the approve **job** starts a separate `change_outputs` job (`JobKind`) once approval
  left the project `completed`. So the approve job reports done when compilation is done, and an
  output failure never touches the approve result.
- Routes: `GET /projects/{id}/change-outputs` (stored outputs, the running job, and `available`);
  `POST …/change-outputs/regenerate {stage, provider?, model?}` (202; one run per project; cloud
  Nemotron by default, like every KB route); `GET …/change-outputs/export.zip`;
  `GET …/change-outputs/files/{test-cases.xlsx|test-plan-addendum.docx|test-plan-addendum.md|system-flow-diagram.md|changes.patch}`.
- **Config:** `change_outputs_repair_rounds` (2), `change_outputs_smoke` (True),
  `change_outputs_smoke_python` (`""` = the server's interpreter). The run is timed under
  `stage_timings["change_outputs"]`. The time-saved metric compares it against
  `baseline_hours["change_outputs"]` (a 16 h estimate).
- **Reset recipe for demos:** `python scripts/reset_demo_state.py` (a dry run; `--yes` deletes
  after a backup zip; `--keep <id>`).
- **UI:** the Results tab of a grounded project gets a **Workflows | Change outputs** switch. The
  Change-outputs view has: Diagrams (a chip per diagram, an Original ⇄ Updated toggle, checks,
  source); Code (a file list with status badges and ast / ruff / `repaired ×N` / `style kept`
  pills, the repair verdicts per file, the bundle smoke card, a unified / side-by-side /
  updated-file viewer built on the `diff` package, `changes.patch`); Test cases (a table with new
  and updated highlighting, `.xlsx` and addendum `.docx` downloads, the rendered addendum); a
  stage selector plus **Regenerate**; **Download all (.zip)**; warnings; and the Sources list.

---

## 15. The three entry points

One engine, three faces: a Python library, a command-line tool, and an HTTP API.

### 15.1 Library

A minimal program that compiles a document, waits for a human review, then approves:

```python
import asyncio
from workflow_compiler import WorkflowCompiler

async def main():
    compiler = WorkflowCompiler.from_settings()
    state = await compiler.compile_document(open("examples/order_workflow.md").read())
    # ... a human reviews state.review_report / state.mermaid_diagram ...
    final = await compiler.approve_graph(state.workflow_id, reviewer="alice")
    print(final.temporal_design.workflow_name)
    for f in final.temporal_code.files:        # the runnable Temporal Python bundle
        print(f.path)

asyncio.run(main())
```

### 15.2 CLI (`cli/main.py`, Typer + Rich)

The commands, one per line, with what each one does:

```bash
workflow-compiler init                                        # → write .env (one-time setup, no LLM)
workflow-compiler compile doc.md --spec-dir ./specs           # → segment + specs, stops at the spec gate
workflow-compiler validate <project-id> --spec-dir ./specs    # → fold edits in, run the spec validator
workflow-compiler approve-spec <project-id> --spec-dir ./specs --out-dir gen  # → compile all to code
workflow-compiler approve <id> --reviewer alice --out wf.mmd  # → manual override for a pending graph
        # … add --out-dir ./generated to also write the runnable Temporal code bundle to disk
workflow-compiler reject  <id> --reason "missing branch"      # → halts (no LLM)
workflow-compiler show    <id>                                # → display a stored state (no LLM)
workflow-compiler compile doc.md --no-review                  # → skip the default review passes (faster/cheaper)
```

Each command builds a provider (or uses `--provider mock`), constructs a compiler with the file
store, runs the async work (with a live progress sink), closes the provider, and prints Rich
tables (metadata, facts by category, review issues, CVPA assignments, Temporal components,
generated code files). `--out` writes the Mermaid diagram. `--out-dir` writes the
`TemporalCodeBundle` as one file per `GeneratedFile` under `<out-dir>/<slug>/`. `reject` and
`show` build a compiler with **no LLM**, because they do not need one. The compiling commands
stream a step log with timestamps through the progress callback.

`compile`, `validate`, `approve-spec` and `approve` use the LLM. Set the local gateway or
`NVIDIA_API_KEY`, or pass `--provider mock`. The mock answers every stage with a scripted demo
workflow, so every command runs offline. `reject` and `show` need no LLM. `models` lists the
models that the local eGPU gateway exposes (`workflow-compiler models`). `--version` prints the
version. `workflow-compiler <command> --help` is always the authoritative reference.

For the local gateway, `--model ID` selects the **local** model (find the ids with
`workflow-compiler models`). `--provider nemotron` skips the eGPU and uses the hosted API.

#### `init` — write the `.env` configuration (one time, no LLM)

This is the configuration half of the install ([§5](#5-installation-and-configuration)). It asks
which provider to use and for the credentials that provider needs, then writes `.env`. It builds
no provider and makes no network call. It never checks the credentials against a live endpoint.
It writes the file and names anything that is still missing.

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` | asked for | `nemotron` \| `local` \| `local-fallback` \| `mock`. |
| `--nvidia-api-key KEY` | asked for | Read only for `nemotron` / `local-fallback`. |
| `--env-file PATH` | `.env` | Where to write. Parent directories are created. |
| `--force` | off | Replace an existing file. Without it, an existing file is an error (exit 1). |
| `--yes` / `-y` | off | Ask nothing. Use the given flags plus defaults (provider `mock`). |

Credentials that the chosen provider does not need are written as commented placeholders. So a
later switch of provider is an uncomment, not a trip back to `.env.example`. The rendering is
`cli/init_env.py::render_env`, a pure function of its arguments. It is tested without a terminal
in `tests/test_cli_init.py`.

#### `compile <document>` — segment into editable specs, stop at the spec gate

This command discovers **every** workflow in the document, extracts facts per workflow (with the
sequential review pipeline), and writes one editable spec file per workflow plus an `overview.md`
to `--spec-dir`.

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` | from `.env` | Override the LLM provider (for example `mock`). |
| `--model ID` | from `.env` | Override the model id. |
| `--timeout SECONDS` | `120` | Timeout per request. |
| `--persist` / `--no-persist` | persist | Whether to save the resulting project to the store. |
| `--review` / `--no-review` | review | Sequential review passes (completeness → grounding → consistency) over the LLM stages. |
| `--spec-dir DIR` | `./specs` | Where to write the spec files. |
| `--kb ID` | — | Ground the compile with a knowledge base (KG context in every prompt) and write `changes.md` next to the spec files ([§13](#13-grounded-projects-and-the-change-spec)). |
| `--change-request ID` | — | The change request whose approved TDD this document is. Seeds `changes.md`, restricts its requirement ids, and links the project into `cr.project_ids`. Implies `--kb`. |

Two example runs:

```bash
workflow-compiler compile big_business_doc.docx --spec-dir ./specs
# → specs/overview.md, specs/customer-onboarding.md, specs/account-provisioning.md, ...
workflow-compiler compile examples/order_workflow.md --provider mock   # offline, no API key
```

Each spec file contains the workflow's metadata and its activities, decisions, exceptions and
compensations (with stable `[ids]`), plus **Assumptions**, **Ambiguities**, **Open Questions**
(the readiness checklist as fill-in questions), **Cross-Workflow Dependencies** (output→input
links that you confirm by ticking their checkbox), and **Triggers** (cross-workflow starts that
can run). Edit the files in any editor. Keep the `[id]` markers on the lines you change. New lines
that you add are recorded as *human-provided*.

A **Triggers** entry says that this workflow *starts* another workflow (which is always
standalone). An example entry:

```markdown
## Triggers
- [x] triggers `account-provisioning` (blocking) when `application approved`
  result: provisioning_result
  input customer_record_id: step output `a2` (str)
```

The mode is `blocking` (the caller waits for the target's result, bound to the `result:` name)
or `fire-and-forget`. The optional ``when `…` `` predicate makes the trigger conditional. The LLM
drafts it; review it and tick the checkbox to confirm. Each indented `input` line maps one field
of the target's typed input from your workflow's input, an earlier step's output, or a constant.

#### `validate <project-id>` — fold edits back in and check the specs again

```bash
workflow-compiler validate <project-id> --spec-dir ./specs
```

This command parses your edits back onto the structured spec deterministically. Then it runs
three LLM review passes against the original document (completeness / grounding / consistency)
plus a **deterministic cross-workflow integrity pass** over every trigger and dependency.
Machine-extracted statements with no support are removed. **Your** additions are only ever
*flagged* for confirmation, never deleted. The files are written again with the fixes and
findings. Repeat edit ⇄ validate until you are satisfied.

Findings have two tiers. They print with precise references
(`TAG slug Section > field: message`):

- `BLOCK` (red) — structural breakage that prevents generation: a trigger that targets a workflow
  not in the project, an input map that names a field the target does not declare, a document
  segment that is not isolated, unmet required checklist items. **`validate` exits with a
  non-zero code while any blocking finding remains**, and `approve-spec` refuses (override with
  `--accept-incomplete`).
- `WARN` (yellow) — should be confirmed, but does not block: type mismatches on a hand-off,
  unconfirmed trigger predicates, a blocking trigger with no result binding.

#### `edit <project-id> <edit-file>` — change compiled workflows with an edit request

```bash
workflow-compiler edit <project-id> examples/order_edit_request.md --spec-dir ./specs --author alice
```

This command applies a **workflow edit-request document** (format:
[`EDIT_FORMAT_GUIDE.md`](EDIT_FORMAT_GUIDE.md)) to a compiled project. Structured sections
(`## Workflow: <slug>` with `### Add` / `### Modify` / `### Remove`, plus `### Triggers` /
`### Dependencies`, `## Add Workflow:` and `## Remove Workflow:`) hold natural-language entries.
An LLM translates them into deterministic patches against the current specs. Your changes carry
**human authority**: additions need no support in the original document (they are marked
`[human]`), and removals are honored. The edit is **atomic**: an entry that cannot be translated
or applied aborts the whole request, lists the failing entries, and changes nothing. (An addition
whose value is already in the spec is treated as satisfied and skipped with a
`skipped (already present)` summary line, instead of an abort.)

On success the versions of the edited workflows are bumped, an `EditRecord` is appended to the
project's audit log, the spec files are written again, and the project returns to the spec gate.
Run `validate` and then `approve-spec` to regenerate the graphs, designs and code.

`--dry-run` previews the edit: a full parse, interpretation and summary per workflow, without
applying or writing anything. Run the command again without the flag to apply. (The web UI goes
further: its preview hands the interpreted operations back on confirm, so the apply replays
exactly what was previewed, with no second LLM call.)

| Flag | Default | Description |
|---|---|---|
| `--workflow SLUG` | all | Only allow edits that touch these workflow slugs (repeatable). |
| `--author NAME` | — | The author recorded in the edit log. |
| `--spec-dir DIR` | `./specs` | Where the updated spec files are written again. |
| `--dry-run` | off | Preview the edit. Nothing is applied or saved. |
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | The same LLM overrides as `compile`. |

#### `approve-spec <project-id>` — compile every workflow through to code

```bash
workflow-compiler approve-spec <project-id> --spec-dir ./specs
```

This command approves the specs and runs each workflow **independently** through graph building,
structural review, CVPA, Temporal design and code generation. The graph gate is automatic: a
health score at or above the configured threshold continues; below it, the workflow stays
pending (`approve <workflow-id>` remains the manual override). Unanswered required questions
block a workflow unless you pass `--accept-incomplete`. Unconfirmed dependencies block approval
unless you pass `--allow-unconfirmed`. The runnable Temporal bundle of each completed workflow is
written under `<out-dir>/<project-id>/<slug>/`. `--out-dir` defaults to `./generated`, so
repeated runs never litter the working directory with loose bundle folders.

For a knowledge-base-grounded project, `--change-outputs` chains the post-approval change outputs
([§14](#14-post-approval-change-outputs-change_outputs)) once every workflow compiled, and unpacks
the bundle under `<out-dir>/<project-id>/change-outputs/`.
`workflow-compiler change-outputs <project-id> [--stage all|diagrams|code|tests_doc] [--out-dir]
[--provider] [--timeout 400]` runs one stage or all of them again later. The exit code is 1 when a
stage failed; the outputs of the other stages are still written.

**Every workflow generates as a standalone Temporal workflow.** It gets its own `workflow.py`,
`activities.py`, `shared.py`, `worker.py`, `starter.py`, and a `test_stepthrough.py` local
harness. Confirmed triggers also generate a `triggers.py` in the *source* workflow's bundle:
activities that start the target by workflow-type name on the target's own task queue
(`id_conflict_policy=USE_EXISTING` keeps retries idempotent; blocking triggers wait for
`handle.result()`). The target's bundle is untouched. It always runs independently.
Multi-workflow projects also get a top-level `contracts.py` (the typed input of every workflow)
and a project `README.md` that documents the trigger topology and the task queues.

Every generated workflow exposes **read-only debug queries** (`current_step`,
`decisions_taken`, `triggers_fired`). They are safe in production. Set
`WORKFLOW_COMPILER_STEPWISE=1` for interactive step-through: each top-level step then waits for an
`advance` signal. The generated `test_stepthrough.py` runs the bundle under a time-skipping test
environment with the stub activities (triggers mocked) and prints those queries. It is the
quickest way to see which branch a conditional actually takes.

#### `approve <workflow_id>` — manual override for a below-threshold graph

When a workflow's graph health lands below the auto-approve threshold at `approve-spec`, the
workflow is left pending. Inspect it (`show`), then approve it by hand to produce CVPA, the
Temporal design and the code.

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | The reviewer identity recorded on the approval. |
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | The same LLM overrides as `compile`. |
| `--out PATH` | — | Write the CVPA-colored Mermaid diagram to a file. |
| `--out-dir DIR` | `./generated` | The root for generated output. The bundle lands in `<out-dir>/<workflow-id>/`. |

```bash
workflow-compiler approve <workflow_id> --reviewer alice --out workflow.mmd
```

#### `reject <workflow_id>` — halt a pending workflow (no LLM)

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | The reviewer identity. |
| `--reason TEXT` | — | Why the graph was rejected (recorded in the report). |

#### `show <workflow_id>` — display a stored workflow (no LLM, no flags)

#### Windows console note

The progress and table output contains Unicode (for example `→`). On an old `cp1252` console
this raises `UnicodeEncodeError`. Run with UTF-8 mode: `set PYTHONUTF8=1` (PowerShell:
`$env:PYTHONUTF8=1`). This is a console-rendering problem only. It does not affect the generated
code. Nemotron's reasoning models can also be slow. Raise `--timeout` (for example `300.0`) to
avoid `ProviderTimeoutError` on a slow request.

#### `kb …` and `cr …` — knowledge bases and change requests

These commands live in `cli/kb.py`. They use the same file store as the API, with no login.

| Command | Purpose |
|---|---|
| `kb init <zip-or-folder> [--name] [--enrich/--no-enrich] [--provider] [--model] [--id]` | Create and index a knowledge base. Progress prints per file. |
| `kb list` / `kb show <kb-id>` | List knowledge bases; show stats by type, catalog ids and warnings. |
| `kb ask <kb-id> "<prompt>" [--budget] [--hops] [--json]` | Print the retrieved packet and its sources with line spans. |
| `kb impact <kb-id> <seed>… [--hops]` | Print the deterministic impact table. |
| `kb search <kb-id> "<query>"` / `kb delete <kb-id>` | Show anchor candidates; remove a knowledge base. |
| `cr create <kb-id> <bcr.docx\|.md\|.txt> [--title] [--provider] [--model]` | Register a change request against a knowledge base. Metadata, requirements and impact seeds are parsed deterministically. |
| `cr list` / `cr show <cr-id>` | List change requests; show one with its wizard and artifact state. |
| `cr draft <cr-id> <impact\|epic\|stories\|tdd> [--auto] [--out FILE]` | Draft one wizard step. `--auto` starts the wizard, drafts the questions, answers each one with its first suggested option, then drafts. |
| `cr approve <cr-id> <step>` / `cr delete <cr-id>` | Approve a step (the wizard advances); delete a change request. |
| `cr export <cr-id> <step> [--format md\|docx\|xlsx] [--version N] [--out PATH]` | Print or save one artifact: Markdown (any version), Word (stories → a zip of one document per story), or the affected-test-cases workbook (impact only). Deterministic. Unapproved artifacts are labelled DRAFT. |
| `cr export <cr-id> --format zip [--out PATH]` | Save the whole change request as a zip. |

### 15.3 HTTP API (`api/app.py`, FastAPI)

Run the API with `python -m uvicorn workflow_compiler.api.app:app --reload` from the virtual
environment where the package is installed. A bare `uvicorn` resolves through `PATH` and may
belong to a different environment. That shows up as
`ModuleNotFoundError: No module named 'workflow_compiler'`. Interactive docs live at `/docs`.

**Authentication.** The HTTP surface uses local accounts. You register or sign in once, and a
signed HttpOnly session cookie travels with every call. Projects created through the API carry an
`owner_id` (recorded for attribution). By default every signed-in user can see and open every
project. Set `WORKFLOW_COMPILER_PROJECTS_SHARED=false` to restore isolation per owner: you then
see only your own projects (plus legacy and CLI projects with no owner), and other accounts'
projects answer 404. The `author` and `reviewer` fields default to the signed-in user's display
name. Accounts live as JSON under the state store (scrypt-hashed passwords, no external
services). The CLI talks to the compiler directly and needs no login. This protects the HTTP
surface only. Anyone with filesystem access to the state store can read it.

**Auth and settings routes**

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, display_name?}` | Create a local account (signs you in). |
| POST | `/auth/login` | `{email, password}` | Sign in (sets the session cookie). |
| POST | `/auth/logout` | — | Sign out. |
| GET | `/auth/me` | — | The signed-in user and preferences (401 when signed out). |
| PUT | `/auth/me` | `{display_name?, preferences?}` | Update the display name and/or preferences (page size, per-user baseline overrides). Omitted fields stay unchanged. |
| GET | `/settings/defaults` | — | The org-wide baseline-hour defaults (so the Settings UI can show defaults and a reset). |

**Project routes** (the compile → validate → approve pipeline). Spec files travel as
`spec_markdown: {slug: markdown}`.

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/projects/compile` | `{document_text, persist?, provider?, model?, nickname?, kb_id?, change_request_id?}` | Segment into specs per workflow (the spec gate). `model` picks a local gateway model. `nickname` sets an optional label. `kb_id` grounds every prompt in a knowledge base and adds `changes.md`. `change_request_id` seeds it from the request (implies its KB). |
| POST | `/projects/compile-upload` | multipart `file` plus the same form fields | Parse a `.docx/.pdf/.md/.html/.txt` upload to text, then the same as `/projects/compile`. |
| GET | `/projects` | — | List visible projects as summaries (`{projects: [{project_id, nickname, stage, workflow_count, updated_at}]}`, newest first). |
| GET | `/projects/{id}` | — | Load a project and its rendered spec files. `ETag: "<version>"`; `project.version` is the CAS token. |
| PATCH | `/projects/{id}` | `{nickname, expected_version?}` (+ `If-Match`) | Set or clear the project nickname (metadata only, no recompile). Returns the summary. 409 when the token is stale. |
| PUT | `/projects/{id}/spec` | `{spec_markdown, expected_version?}` (+ `If-Match`) | Fold edited spec Markdown back in (no LLM). `spec_markdown["__changes__"]` is `changes.md`. Optional compare-and-swap: a stale token gives 409 ([§7.3](#73-state-storage)). |
| POST | `/projects/{id}/edit` | `{edit_document, workflows?, author?, resolved?}` | Apply an edit-request document and re-arm the gate. Pass `resolved` from a preview to replay it with no LLM call (a stale preview gives 409). |
| POST | `/projects/{id}/edit/preview` | `{edit_document, workflows?}` | Dry-run the edit: the would-be summary, the post-edit spec Markdown, and the `resolved` handoff blob. Saves nothing. |
| POST | `/projects/{id}/validate` | `{spec_markdown?}` | Ingest edits and run the spec validator passes (synchronous). |
| POST | `/projects/{id}/approve` | `{workflows?, reviewer?, spec_markdown?, accept_incomplete?, allow_unconfirmed_references?}` | Approve the specs and compile every workflow (synchronous). |
| GET | `/metrics/summary` | — | Total time saved across your projects (measured pipeline seconds against the configurable `baseline_hours` human-team estimates). |

**Conversational spec resolution.** This is the alternative to hand-editing the spec Markdown.
The validator's **blocking and warning** findings (never INFO), plus each spec's unresolved open
questions, become plain-language questions. The answers are prose. Related findings may be
**grouped** into one question. A vague answer gets exactly **one** clarifying follow-up. Each
answer is applied **at once**: one patch set and one patch-version bump per answered question,
through the same human-authority applier that the edit path uses. So additions need no document
grounding, and are marked `human_provided`. An answer that cannot be mapped to a spec change is
**parked** as a new open question, not discarded (the edit path aborts; this path never does). The
agenda is a snapshot taken at the start, so a session always ends. Applied answers return the
project to `spec_drafted`. Closing the session drops the findings for the changed specs, so
validation must run again before approval.

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/projects/{id}/dialogue` | — | The open session (or `session: null`). |
| POST | `/projects/{id}/dialogue` | — | Open a session. 400 when there is nothing to resolve. Replaces any existing session. |
| POST | `/projects/{id}/dialogue/answer` | `{answer}` | Answer the current question in prose. Applies patches, or asks a follow-up, or parks. |
| POST | `/projects/{id}/dialogue/skip` | — | Pass on the current question. The spec is untouched. |
| DELETE | `/projects/{id}/dialogue` | — | Close the session. Answers already applied stay applied. |

Every response carries `prompt`: the exact text to show the user. It is the pending clarifying
follow-up when one is open, and the question otherwise. The response also carries `changes` /
`parked_as`, which describe what the last answer did, and the refreshed `spec_markdown`.

**Background runs.** Validate and approve can also run as **cancelable background runs** that
continue after the user navigates away (the web UI uses these). A run is an in-process task.
**Cancelling never saves a partial result**, so the project stays exactly as it was. At most one
run per project may be in flight (a second start answers `409`), but any number of *different*
projects may run at once. Runs live in memory. A server restart drops them. Nothing was saved, so
the project simply stays in its pre-run state.

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| POST | `/projects/{id}/jobs` | `{kind: "validate"\|"approve", spec_markdown?, …approve knobs}` | Start a background run. Returns `202` and the run descriptor at once. |
| GET | `/jobs` | `?project_id=` (optional) | List the caller's runs, newest first (all users' runs when `projects_shared`). |
| GET | `/jobs/{job_id}` | — | The status of one run. The finished project is embedded when `status == "succeeded"`. |
| POST | `/jobs/{job_id}/cancel` | — | Cancel a run and leave the project untouched (a no-op once the run is terminal). |

`GET /jobs` also accepts `?scope_id=` (an alias of `project_id`) and
`?scope_kind=project|knowledge_base`. Every job carries `scope_id`, `scope_kind` and, for long
runs, `progress {message, done, total}`.

**Knowledge-base routes** ([§10](#10-knowledge-bases-kg)). Uploading a corpus answers `202` with
the knowledge base **and** its `kb_ingest` job. Poll the job or the KB until `status == "ready"`.
The same visibility rule as projects applies.

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| POST | `/knowledge-bases` | multipart `file` (zip), `name?`, `enrich?`, `provider?`, `model?` | Extract the corpus (400 on a bad or unsafe zip) and start indexing. |
| GET | `/knowledge-bases` | — | List knowledge bases (stats, catalog, status). |
| GET | `/knowledge-bases/{id}` | — | One knowledge base (plus the running job, if any). `ETag` / `version` (the CAS token). |
| DELETE | `/knowledge-bases/{id}` | — | Remove the record, the corpus and the graph (cancels a running ingest). |
| POST | `/knowledge-bases/{id}/reindex` | `{enrich?, provider?, model?}` | Rebuild the graph as a job (the enrichment cache is reused). |
| POST | `/knowledge-bases/{id}/retrieve` | `{prompt, budget?, max_hops?}` | A grounded context packet (`rendered`, `sections`, `files`, `coverage`). |
| GET | `/knowledge-bases/{id}/impact` | `?seed=…` (repeatable) `&max_hops=` | The deterministic impact table. |
| GET | `/knowledge-bases/{id}/search` | `?q=…&k=` | BM25 anchor candidates. |
| GET | `/knowledge-bases/{id}/files` | `?path=` (optional) | The corpus file list, or one file as text. |
| GET | `/knowledge-bases/{id}/graph/summary` | `?top=` | Counts by node and edge type, plus the best-connected nodes. |

**Change-request routes** ([§11](#11-change-requests-change)).

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| POST | `/change-requests` | multipart `kb_id`, `file` (docx/md/txt) or `text`, `title?`, `provider?`, `model?` | Register a change request (201; no LLM call). |
| GET | `/change-requests` | — | List change requests (summary rows). |
| GET | `/change-requests/{id}` (`/wizard`) | — | The change request: wizard steps, questions and turns, artifacts, ids, the running job. `ETag` / `version` (the CAS token). |
| DELETE | `/change-requests/{id}` | — | Delete (cancels a running job). |
| POST | `/change-requests/{id}/wizard/start` | `{provider?, model?}` | Reserve ids and run the impact traversal (sync), then draft the current step's questions as a `cr_questions` job (202; idempotent). |
| POST | `/change-requests/{id}/wizard/answer` | `{answer, option?}` | Answer the current question (one short LLM call; may return one follow-up). |
| POST | `/change-requests/{id}/wizard/skip` | — | Skip the current question. |
| POST | `/change-requests/{id}/wizard/draft` | `{step?}` | Draft the step's artifact as a `cr_draft` job (202; pending questions are skipped). |
| POST | `/change-requests/{id}/wizard/revise` | `{step, message}` | A chat revision of a drafted artifact, as a `cr_revise` job (202). |
| GET | `/change-requests/{id}/artifacts/{kind}` | `?version=` | The artifact Markdown (latest or one version), plus history, sources and coverage. |
| PUT | `/change-requests/{id}/artifacts/{kind}` | `{markdown, note?, expected_version?}` (+ `If-Match`) | A human edit → a new `human_edit` version (400 when the structure is lost; 409 when the CAS token is stale). |
| POST | `/change-requests/{id}/artifacts/{kind}/approve` | — | Approve. The cursor advances and the next step's questions job starts. |
| GET | `/change-requests/{id}/artifacts/{kind}/export` | `?format=docx\|md\|xlsx` | Download the artifact as Word (stories: a zip of one document per story), Markdown, or the TC preview workbook (impact only). Deterministic. `Content-Disposition` names the file. Labelled DRAFT until approved. |
| GET | `/change-requests/{id}/export.zip` | — | Every artifact as Word and Excel, plus `markdown/*.md` and `MANIFEST.txt`. |
| POST | `/change-requests/{id}/send-to-workflow` | `{provider?, model?, nickname?}` | Compile the **approved** TDD into a KB-grounded workflow project (`kb_id` and `change_request_id` set, `changes.md` seeded), append it to `project_ids`, and return the `ProjectResponse` (201; 409 while the TDD is unapproved). Synchronous. The provider defaults to the wizard's, else cloud Nemotron. |

**Change-output routes** ([§14](#14-post-approval-change-outputs-change_outputs)).

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| GET | `/projects/{id}/change-outputs` | — | The stored post-approval change outputs (diagrams, code diff, test docs), the running `change_outputs` job if any, and `available` (grounded and compiled). |
| POST | `/projects/{id}/change-outputs/regenerate` | `{stage: all\|diagrams\|code\|tests_doc, provider?, model?}` | Run the stage(s) again as a `change_outputs` job (202; 409 while a run is in flight or the project is not grounded and compiled; 422 for an unknown stage). Cloud Nemotron by default. The approve job starts this automatically for grounded projects. |
| GET | `/projects/{id}/change-outputs/export.zip` | — | `src/` and `tests/` (the updated code), `docs/diagrams/`, `docs/test-cases/` (the TC matrix `.xlsx`, the test-plan addendum `.docx` / `.md`), `changes.patch`, `CHANGES.md` (404 until generated). |
| GET | `/projects/{id}/change-outputs/files/{name}` | — | One rendered document: `test-cases.xlsx`, `test-plan-addendum.docx`, `test-plan-addendum.md`, `system-flow-diagram.md`, `changes.patch`. |

**Time saved in responses.** Project responses include `time_saved`: each pipeline step's
measured wall-clock seconds (saved per project as `stage_timings`) compared against configurable
human-team estimates (`WORKFLOW_COMPILER_BASELINE_HOURS`, a JSON object of hours per step
category). The baselines are **estimates, not measurements**. Tune them to your organization.
Each signed-in user can also override the baselines for their own view from the **Settings** page
(`PUT /auth/me` with `preferences.baseline_hours`). Their overrides take precedence over the
org-wide config default, and `time_saved` and `/metrics/summary` recompute live with the caller's
values.

**Per-workflow routes** (viewing, plus the manual override for graphs below the threshold).

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| POST | `/approve` | `{workflow_id, reviewer?}` | Approve → run CVPA and Temporal. |
| POST | `/reject` | `{workflow_id, reviewer?, reason?}` | Reject a graph. |
| GET | `/workflow/{id}` | — | Load a stored workflow state. |
| GET | `/workflows` | — | List the stored workflow ids. |
| GET | `/providers/local/models` | — | List the models that the local eGPU gateway exposes (for the picker). |
| GET | `/health` | — | Liveness probe. |

`get_compiler` provides the compiler once (a cached `from_settings()`). Tests override it with a
mock-backed compiler. A small `_guard` helper maps domain exceptions to HTTP codes:
`StateNotFoundError → 404`, `ApprovalError → 409`, `CompilationError → 400`.

An example call that compiles one sentence of prose:

```bash
curl -s localhost:8000/projects/compile \
  -H 'content-type: application/json' \
  -d '{"document_text": "When a customer submits an order, validate payment, then ship it."}'
```

---

## 16. A worked example

Follow the data through one run.

**Input** (`examples/order_workflow.md`, shortened): *"When a customer submits an order, validate
the payment. If valid, process and ship it. If declined, cancel and notify. Retry shipment up to
3 times; on final failure, release inventory."*

1. **Parse** → `text` (plus format = markdown and a character count).
2. **Discovery** → metadata: name "Order Fulfillment", actors [Customer, Warehouse], systems
   [Payment Gateway, OMS], triggers [Order submitted], end states [shipped, cancelled].
3. **Facts** → activities [Validate payment, Process order, Ship order, Notify customer],
   decisions [Is payment valid?], exceptions [Payment declined], retries [Retry shipment],
   compensation [Release inventory].
4. **Graph (deterministic)** → nodes `start, activity_1..4, decision_1, exception_1,
   compensation_1, end`; the spine `start→activity_1→…→end`; `decision_1` with `yes` / `no`
   edges; a dotted error edge to `exception_1`; a retry back-edge; exception → compensation → end.
   Plus a Mermaid diagram. (A real run produced a 7-node graph at **health 1.0**.)
5. **Review** → no errors; `health_score = 1.0`; `approval_status = PENDING`. **Saved to disk.
   The pipeline stops.** You get a `workflow_id`.
6. **Approve** (`approve_graph(id)`):
   - **CVPA** → every node gets a label: `start` → Capture, `decision_1` → Validate,
     `activity_*` → Process, `end` → Activate. Nodes the model skipped are filled by the
     type-based fallback. The diagram is **rendered again with colors** (blue / amber / green /
     purple).
   - **Temporal design** → workflow `OrderFulfillment`; activities (ValidatePayment, ProcessOrder,
     ShipOrder, …); a `cancel` signal; a `ReleaseInventory` compensation that `compensates`
     ProcessOrder; a default retry policy; and a plan IR that orders the activity calls, with the
     result of `ValidatePayment` bound into the input of `ProcessOrder`.
   - **Temporal code (deterministic)** → a `temporal-order-fulfillment` package: `shared.py`,
     `activities.py` (stubs), `workflow.py` (the run body waits for each activity in plan order,
     registers `ReleaseInventory` for saga rollback, and fires it in reverse on failure),
     `worker.py`, `starter.py`, `README.md`. With `--out-dir gen` these are written under
     `gen/temporal_order_fulfillment/`.
   - `stage = CODE_GENERATED → COMPLETED`, saved.

If you **reject** instead, `approval_status = REJECTED`, the reason is recorded, and CVPA,
Temporal design and code generation never run.

---

## 17. Testing strategy

- **Unit tests** for each component: models, ingestion, the LLM layer (with
  `httpx.MockTransport`), prompts, each agent, the graph builder, reviewer and Mermaid renderer,
  GraphEditor, and the state stores.
- **Integration tests** (`tests/test_integration.py`) run the **whole pipeline** against a
  `MockProvider` and an `InMemoryStateStore`: the gated path, the auto-approve path, reject halts,
  disk persistence and reload across two compiler instances, a GraphEditor round trip, and CVPA
  exactly-once coverage.
- **API tests** drive every endpoint with a mock-backed compiler through `dependency_overrides`.
- **Relational extraction tests** (`tests/test_relational_structure.py`) cover the
  referential-integrity guard (dangling ids dropped, entity-id transition leaks dropped) and the
  semantic wiring (relations attach to the correct nodes, parallel groups become gateways,
  exceptions with no compensation terminate).
- **Temporal codegen tests** (`tests/test_temporal_codegen.py`) assert that the generator renders
  the expected six-file bundle, threads step outputs into later inputs, emits saga compensation,
  and imports `asyncio` only when a parallel step exists.
- **Temporal IR runtime test** (`tests/test_temporal_ir_runtime.py`) writes a generated bundle to
  disk and **runs it under a Temporal `WorkflowEnvironment`** (time-skipping, flat imports). This
  proves that the emitted code actually runs. It is the final guard against codegen
  hallucination.
- **Review-pipeline tests** (`tests/test_review_pipeline.py`) exercise the deterministic patch
  appliers (grounded `add`, duplicate and ungrounded drops, `merge` that re-points references,
  dangling relations made null by `validated()`), the end-to-end `ReviewPipelineAgent` (generate
  plus three passes, and the idempotent settle to `no_change`), and the compiler's
  **review → plain** precedence.
- The suite needs no network. Run `pytest` and `ruff check src tests`.

Because the LLM sits behind `BaseLLMProvider`, the `MockProvider` returns *queued* structured
responses in order, for example `[discovery, facts, cvpa, temporal]`. So tests can drive the
exact path deterministically. Note: with the **review pipeline on (the default)**, each reviewed
stage also consumes three `ReviewResult` responses. So the end-to-end suites that use an exact
queue (integration, API, compiler) construct the compiler with
`review=ReviewConfig(enabled=False)`. `tests/test_review_pipeline.py` covers the review behavior
on its own.

---

## 18. How to extend the system

- **Add an LLM vendor:** subclass `OpenAICompatibleProvider` (or `HttpChatProvider` for a
  different wire format), then call `ProviderFactory().register("myvendor", MyProvider)`. Nothing
  else changes.
- **Add a document format:** implement `BaseDocumentParser` and register it with
  `DocumentParserFactory`.
- **Swap the persistence:** implement `StateStore` (for example SQLite or S3) and pass it to the
  compiler.
- **Change a prompt:** edit the Markdown in `prompts/templates/`. No code change is needed.
- **Add a pipeline stage:** write a `BaseAgent` subclass and add it to `agents` or
  `post_approval_agents`.

---

## 19. File map

Where everything lives:

```
src/workflow_compiler/
  __init__.py          Public exports (WorkflowCompiler, ProjectCompiler, stores, providers, …)
  compiler.py          WorkflowCompiler — orchestrates the whole pipeline + the gate
  project_compiler.py  ProjectCompiler — spec-centric front-end (segment → specs → spec gate →
                       per-workflow back-end with the automatic graph-health threshold gate)
  config.py            Settings from .env (pydantic-settings)
  env.py               Loads .env into the environment (python-dotenv)
  logging.py           Loguru + Rich logging
  exceptions.py        Typed exception hierarchy

  models/              Pydantic artifacts:
    state.py           WorkflowState (the aggregate; incl. temporal_code)
    project.py         CompilationProject + ProjectStage + WorkflowSegment (spec front-end)
    spec.py            WorkflowSpec + SpecItem + CrossReference + Provenance
    enums.py           CompilationStage, NodeType, EdgeType, CVPAPhase, FactCategory, …
    temporal.py        Temporal design + plan IR (StepKind, BindingSource, TemporalStep, …)
                       and the generated-code models (GeneratedFile, TemporalCodeBundle)
    patch.py           review-pipeline patch vocabulary (PatchAction, Evidence, Patch, ReviewResult)
    metadata.py facts.py structure.py graph.py review.py cvpa.py mermaid.py confidence.py

  interfaces/          Abstract contracts: BaseParser, BaseAgent, BaseLLMProvider,
                       StateStore, ReviewManager

  ingestion/           Document parsing → DocumentContent
    factory.py         DocumentParserFactory (selects a parser)
    docx_parser.py pdf_parser.py markdown_parser.py html_parser.py text_parser.py
    content.py encoding.py base.py

  llm/                 Provider-agnostic LLM layer
    factory.py         ProviderFactory (name → provider)
    base.py            HttpChatProvider (retries, structured output, validation)
    config.py retry.py json_utils.py types.py
    providers/         nemotron.py, openai_compatible.py, mock.py

  prompts/             Markdown prompt templates + manager/loader/renderer
    templates/*.md

  agents/              One class per pipeline stage
    discovery.py fact_extraction.py graph_builder.py review.py cvpa.py temporal.py
    temporal_code.py   TemporalCodeGeneratorAgent (deterministic; wraps codegen/)
    review_pipeline.py ReviewPipelineAgent + ReviewPass/ReviewSpec/PatchApplier (default-on review)
    segmentation.py    WorkflowSegmentationAgent (multi-workflow discovery + document slicing)
    serialization.py   compact graph/CVPA/facts text for prompts

  spec/                Spec projection layer (spec-centric front-end, no LLM except validator)
    renderer.py        deterministic WorkflowSpec → Markdown (the human review surface)
    ingest.py          deterministic Markdown → merged spec (provenance + validated())
    validator.py       SpecValidator + provenance-aware SpecPatchApplier (3 review passes)

  checklist/           Readiness rules, surfaced as the spec's Open Questions
    validator.py       ChecklistValidator (deterministic R0–R9 rules)
    amend.py           deterministic fold-back of answered questions (no LLM)

  graph/               Deterministic graph machinery (no LLM)
    builder.py         WorkflowGraphBuilder (facts → graph, NetworkX; positional + structural)
    mermaid.py         to_mermaid / to_mermaid_with_cvpa (CVPA coloring)
    review.py          GraphReviewer (structural QA + health score)

  codegen/temporal/    Deterministic Temporal code generation (no LLM)
    generator.py       TemporalPythonCodeGenerator (walks plan IR → Python run body + Jinja files)
    templates/*.jinja  shared / activities / workflow / worker / starter / README skeletons

  review/              The approval gate + editing
    manager.py         DefaultReviewManager (review/approve/reject)
    editor.py          GraphEditor (validated, immutable edits)

  storage/             State persistence
    file.py            FileStateStore (atomic JSON on disk)
    memory.py          InMemoryStateStore
    project_store.py   FileProjectStore / InMemoryProjectStore (CompilationProject JSON)

  api/                 FastAPI app (app.py, schemas.py, dependencies.py)
  cli/                 Typer CLI (main.py)

examples/              Sample business documents (order, onboarding, subscription_upgrade)
docs/                  architecture.md, HOW_IT_WORKS.md (this file), TEMPORAL_CODEGEN_FINDINGS.md
tests/                 Unit + integration + API tests (incl. test_temporal_codegen.py,
                       test_temporal_ir_runtime.py, test_relational_structure.py)
```

The change-pipeline modules (`kg/`, `change/`, `docs_export/`, `change_outputs/`,
`storage/change_store.py`, `storage/ids.py`, `execution/bundles.py`, `cli/kb.py`) are described
in [§10](#10-knowledge-bases-kg) to [§14](#14-post-approval-change-outputs-change_outputs) and in
[§7.3](#73-state-storage).

---

## 20. Gotchas and "why is it like that?"

- **`end` in Mermaid** is a reserved word. It silently breaks diagrams. Node ids that collide are
  renamed (`end` → `end_node`). Edge labels must not be quoted. The system handles both
  automatically.
- **The graph builder never calls the LLM.** This is by design, for determinism and testability.
  When a graph looks wrong, the fix is in the *facts* or in the *builder rules*, not in a prompt.
  Note the distinction: *wrong nodes* (missing or extra entities) is an extraction problem.
  *Wrong wiring* (edges to the wrong place) means one of two things: either the relational
  `structure` was absent (so the positional fallback guessed), or the LLM linked the wrong ids.
  The referential-integrity validator only drops links to ids that were *not declared*. It cannot
  catch a link to the wrong *declared* id.
- **CVPA always covers every node**, even when the LLM is incomplete, because of the type-based
  fallback. So the rule "exactly one phase per node" can never be broken downstream.
- **The LLM emits a design, never code. A deterministic generator emits the code.** The Temporal
  *design* stage (Stage 6) is specification-only. A test asserts that the design models have no
  `code`, `body` or `implementation` field. The no-LLM generator (Stage 7) produces the runnable
  Temporal Python on its own. So the generated code is a reproducible function of a reviewed
  design, not a model hallucination.
- **Generated code uses flat, absolute imports, and you run it directly** (`python worker.py`
  from inside the package). This matches the Temporal Python docs. It does *not* use
  `from .x import` relative imports or `python -m package.worker`. Both of those were earlier
  hallucinations that did not run. See `TEMPORAL_CODEGEN_FINDINGS.md`.
- **The risky part of codegen is emitted in Python, not in Jinja.** The `@workflow.run` body
  (data threading, saga rollback, `asyncio.gather`, branches) lives in `generator.py`, where it is
  unit-tested and even run under a real `WorkflowEnvironment`. The templates carry only
  boilerplate.
- **The API key** is held as a `SecretStr`, sent only as a bearer header, and never logged or
  printed.
- **Reasoning-model latency:** Nemotron's "detailed thinking off" preamble and generous timeouts
  keep structured calls fast and parseable.
- **The gate is durable.** Because the state is saved, `compile`, `validate` and `approve-spec`
  can be separate commands, requests or processes, minutes or days apart.
- **The review passes never certify truth.** They filter with *reference-free* signals (evidence
  quotes, referential integrity, grounding). They raise grounding and consistency, but they cannot
  detect a misreading that the generator and all three reviewers share. That is why the human spec
  gate stays the oracle, and why flagged elements are shown, not trusted. See
  [§7.10](#710-the-sequential-review-pipeline).
- **The store checks ids before it builds a path.** A path-shaped id is refused as "not found",
  and the answer never reveals whether the path would have resolved. See
  [§7.3](#73-state-storage).
- **Saves are last-write-wins unless you send a version.** The CLI and background jobs send
  none. The API and the frontend send `expected_version` or `If-Match`, and get a 409 when the
  record moved. See [§7.3](#73-state-storage).
- **Enrichment and file rewrites default to the cloud provider on purpose.** The local gateway is
  one GPU with no queue. A knowledge-base enrichment is one call per file, and a code rewrite is
  one long call per file. Neither must land there unless the user asks. See
  [§10](#10-knowledge-bases-kg) and [§14](#14-post-approval-change-outputs-change_outputs).
- **The bundle smoke test is a verdict, not a gate.** It tells you whether the rewritten code
  compiles and imports. It never blocks the run. See
  [§14](#14-post-approval-change-outputs-change_outputs).

---

> **The 30-second version.** A document goes in. Agents fill one `WorkflowState` step by step:
> the LLM for understanding, pure functions for structure. A person approves the reviewed graph.
> Then CVPA labels every node, the LLM produces a Temporal design (with a typed plan IR), and a
> deterministic renderer turns that design into runnable Temporal Python code. Every part is
> swappable behind a clean interface. Every state is saved. Every step is observable through
> progress events. Everything is tested without a network, and the generated code even runs under
> a Temporal test environment.
