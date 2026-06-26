# How workflow-compiler Works — A Complete, Ground-Up Walkthrough

This document explains the **entire system end to end**, assuming you know nothing about the
project. By the end you should understand *what* it does, *why* each piece exists, *how* the pieces
fit together, and *where* each piece lives in the code. Read it top to bottom; later sections build
on earlier ones.

> If you just want to run it, see the [README](../README.md). This document is the "how and why."

---

## 1. What problem does this solve?

Businesses describe their processes in **prose** — Word docs, PDFs, wiki pages: *"When a customer
submits an order, validate the payment. If it's valid, the warehouse ships it; if not, cancel the
order and notify the customer."*

That prose is unstructured. You cannot run it, diagram it reliably, or hand it to engineers to
implement without a lot of manual translation. **workflow-compiler** automates that translation. It
takes a business document and produces a chain of increasingly structured, machine-usable
artifacts:

| Artifact | Plain-English meaning |
|---|---|
| **Workflow metadata** | The title card: name, purpose, who's involved, what systems, what triggers it, where it starts/ends. |
| **Workflow facts** | Every atomic statement pulled out of the prose, sorted into 13 buckets (activities, decisions, exceptions, retries, …), plus — when the document supports it — an **id-referenced relational structure** that says *how* those facts connect (which exception each activity raises, which compensation reverses which activity, which steps run in parallel). |
| **Workflow graph** | A flowchart as data: nodes (steps) and edges (arrows), normalized and de-duplicated. |
| **Mermaid diagram** | That graph rendered as text you can paste into a diagram tool to *see* it. |
| **Review report** | An automatic QA pass: "this node is unreachable," "this decision has no 'no' branch," plus a health score. |
| **CVPA classification** | Every step labeled as **C**apture, **V**alidate, **P**rocess, or **A**ctivate — a standard way to reason about business processes. |
| **Temporal design** | A blueprint for implementing the workflow on [Temporal](https://temporal.io) (activities, signals, retries, compensations) — *specifications only, not code.* |
| **Confidence scores** | How sure the system is about each stage. |

A **human approval gate** sits in the middle: the structured graph is generated and reviewed, then
a person approves (or rejects) it before the final design artifacts are produced. This keeps the
expensive, opinionated outputs (CVPA, Temporal) tied to a graph a human signed off on.

---

## 2. Key terms (glossary)

You'll see these throughout. Skim now, refer back as needed.

- **LLM (Large Language Model)** — an AI text model (here, NVIDIA-hosted *Nemotron*). Used for the
  "understanding" stages (reading prose, classifying). It is **never** used where determinism
  matters (building the graph).
- **Agent** — a small class that performs *one* stage of the pipeline (e.g. "extract facts"). Each
  agent takes the current state, does its job, and returns the updated state.
- **Pydantic** — a Python library for data models that validate themselves. Every artifact is a
  Pydantic model, so malformed data is rejected early.
- **NetworkX** — a graph library. The graph builder uses it to reason about reachability, cycles,
  etc.
- **Mermaid** — a text format for diagrams (`flowchart TD ...`). Paste into <https://mermaid.live>
  to render.
- **CVPA** — *Capture / Validate / Process / Activate*. A four-phase lens for business processes:
  intake → checks → core work → downstream effects.
- **Temporal** — a workflow-orchestration platform. We generate a *design* for it, not runnable
  code.
- **WorkflowState** — the single object that flows through the whole pipeline, accumulating
  artifacts. **This is the heart of the system.**
- **Provider** — an implementation of the LLM interface. The real one calls NVIDIA; the `mock` one
  returns canned answers for tests.

---

## 3. The one mental model: `WorkflowState`

Everything revolves around one object: `WorkflowState`
(`src/workflow_compiler/models/state.py`). Think of it as a **folder that travels down an assembly
line**. It starts almost empty (just the document text) and each station fills in one more field.

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
    temporal_design: ...|None      # filled by Temporal (after approval)
    confidence_scores: ...|None    # accumulated every stage

    stage: CompilationStage     # where we are: INGESTED → ... → COMPLETED
    created_at / updated_at     # timestamps; touch() bumps updated_at
```

Every field except `document_text` is `None` until its producing stage runs. The `stage` enum
records progress. Because the whole thing is one Pydantic model, it can be **serialized to JSON and
saved to disk**, then reloaded later to continue (that's exactly how the approval gate works across
separate CLI commands or HTTP requests).

The ordered stages (`models/enums.py` → `CompilationStage`):

```
INGESTED → METADATA_EXTRACTED → FACTS_EXTRACTED → GRAPH_BUILT → REVIEWED
         → CLASSIFIED → TEMPORAL_DESIGNED → COMPLETED      (FAILED on error)
```

---

## 4. The pipeline at a glance

```
            ┌─────────── LLM stages ───────────┐        ┌──── LLM stages ────┐
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
                                                                 COMPLETED
```

Two crucial design rules:

1. **LLM where judgment is needed, determinism where correctness is needed.** Reading prose and
   classifying are LLM jobs. *Building the graph and reviewing it are pure functions* — same facts
   in, same graph out, every time, no model involved.
2. **The gate splits the pipeline.** `compile_document` runs everything up to and including Review,
   then stops. `approve_graph` runs the rest. This is what makes the human-in-the-loop real.

The orchestrator that runs all of this is `WorkflowCompiler` (`src/workflow_compiler/compiler.py`).

---

## 5. Installation & configuration (so the rest makes sense)

```bash
pip install -e ".[dev]"          # installs the package + the `workflow-compiler` CLI
cp .env.example .env             # then edit .env
```

`.env` (read by `config.py` via `python-dotenv`):

```dotenv
NVIDIA_API_KEY=nvapi-xxxx                 # only needed for the LLM stages
WORKFLOW_COMPILER_LLM_PROVIDER=nemotron   # which provider to use
WORKFLOW_COMPILER_LLM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
WORKFLOW_COMPILER_STATE_STORE_PATH=.workflow_state   # where states are saved as JSON
```

- `NVIDIA_API_KEY` is loaded into the process environment and used as a bearer token. It is **never
  logged or printed**.
- `WORKFLOW_COMPILER_*` settings are read by `Settings` (pydantic-settings) in `config.py`.
- For offline use/tests there's a `mock` provider that needs no key.

`get_settings()` is cached (`functools.lru_cache`) so the `.env` is read once per process.

---

## 6. Stage-by-stage deep dive

For each stage: **what goes in, what it does, how, what comes out, and the code.**

### Stage 0 — Document ingestion (Parser, no LLM)

- **In:** a file path or raw bytes/string (`.docx`, `.pdf`, `.txt`, `.md`, `.html`).
- **Out:** a `DocumentContent` object holding normalized plain `text`, a detected `document_format`,
  `metadata` (char/word counts), and `sections`.
- **Code:** `src/workflow_compiler/ingestion/`. `DocumentParserFactory.parse(source)` picks the
  right parser by file extension / MIME type / explicit format, then that parser
  (`DocxParser`, `PdfParser`, `MarkdownParser`, `HtmlParser`, `TextParser`) extracts text.
- **Why a factory?** So the rest of the system never cares about file types — it just gets `text`.
- **Notable details:** encoding is auto-detected (`encoding.py` using `charset-normalizer`); empty
  or oversized files raise typed errors (`EmptyDocumentError`, `FileValidationError`); Markdown
  parsing flattens to readable plain text.

The CLI/compiler take the parser's `content.text` and put it into a fresh `WorkflowState`.

### Stage 1 — Workflow Discovery (LLM)

- **In:** `state.document_text`.
- **Out:** `state.workflow_metadata` (name, purpose, actors, systems, trigger events, start/end
  states). Stage → `METADATA_EXTRACTED`.
- **Code:** `agents/discovery.py` → `WorkflowDiscoveryAgent`.
- **How:**
  1. Render the prompt template `prompts/templates/discover_workflow.md` with the document text.
  2. Call `llm.structured(prompt, WorkflowDiscovery, system=...)`. The provider returns JSON
     validated into the `WorkflowDiscovery` Pydantic schema (permissive: extra keys ignored, so a
     slightly-off model response still parses).
  3. Clean the result into a `WorkflowMetadata` (`_clean_list` strips/dedupes/lowercases-dedupe
     lists; a missing name raises `CompilationError`).
  4. **Confidence:** blend the model's self-reported confidence with *completeness* (how many of the
     7 scored fields were populated) → `confidence_scores.metadata`.

### Stage 2 — Fact Extraction (LLM)

- **In:** `state.document_text`.
- **Out:** `state.workflow_facts` — a flat list of `WorkflowFact` objects (each with a `statement`,
  `category`, `confidence`) **plus an optional `structure`** (`WorkflowStructure`) holding the
  relational layer. Stage → `FACTS_EXTRACTED`.
- **Code:** `agents/fact_extraction.py` → `FactExtractionAgent`; structure models in
  `models/structure.py`.
- **How:** render `extract_facts.md`, call `llm.structured(..., FactExtraction)`. The model returns
  **two layers** in one call:
  1. **Flat scalar facts** — `inputs, outputs, rules, apis, systems, timers, retries` — short
     statements with no inter-entity relations.
  2. **Relational structure** — entities that each carry a short **id** and relations expressed by
     *referencing those ids*: `activity_nodes {id, name, parallel_group}`,
     `decision_nodes {id, question, after, yes_target, no_target}`,
     `exception_nodes {id, reason, raised_by}`,
     `compensation_nodes {id, name, compensates}`, `event_nodes {id, name, emitted_by}`,
     `transition_edges {source, target, trigger}`.
- **Referential-integrity validation (the anti-hallucination guard):** `WorkflowStructure.validated()`
  drops any relation that points at an id the model never declared — the entity is kept, the dangling
  link is nulled, and a warning is recorded. The model literally cannot wire an edge to a node that
  doesn't exist; if it tries, the bad link is discarded. It also drops **state transitions whose
  endpoints are actually entity ids** (e.g. `a1 -> a2`): a common failure mode where the model leaks
  the *step flow* into the *state graph*, which would otherwise build a junk subgraph duplicating the
  real flow. Real state-name transitions (`active -> upgrade_in_progress`) are kept. The count of
  dropped references is surfaced in the confidence note.
- **Backward compatibility:** if the relational layer is empty (a legacy/minimal extraction), the
  agent falls back to the old flat-list path and `structure` stays `None`. Either way the flat
  `WorkflowFacts.facts` are derived (from the structure when present), so every downstream consumer
  (CVPA, Temporal, the CLI summary) keeps working unchanged.
- **Cleaning:** `_normalize` collapses whitespace and repeatedly strips quotes/trailing periods until
  stable (`"Validate payment".` → `Validate payment`); case-insensitive duplicates are removed.
- **Confidence:** blends self-reported confidence with how many categories were populated →
  `confidence_scores.facts`. The note records counts, duplicates removed, and dangling refs dropped.

**Why facts before a graph?** The facts are the *typed building blocks*. The graph builder doesn't
re-read the prose — it works purely from these facts. Capturing the **relations** here (not just the
nouns) is what lets the builder wire edges *semantically* instead of guessing by position.

### Stage 3 — Graph Building (deterministic, no LLM) — *the cleverest part*

- **In:** `state.workflow_facts`.
- **Out:** `state.workflow_graph` (a `WorkflowGraph` of `WorkflowNode`s + `WorkflowEdge`s) **and** a
  Mermaid diagram. Stage → `GRAPH_BUILT`.
- **Code:** `graph/builder.py` → `WorkflowGraphBuilder`. Returns both the canonical `WorkflowGraph`
  and a backing NetworkX `MultiDiGraph` (used later for review).

This is a rules engine, not a model. There are **two wiring paths**, chosen by the agent based on
what Fact Extraction produced:

- **Semantic path — `build_from_structure(structure)` (preferred).** When the facts carry a relational
  `structure`, edges are placed by *reading the explicit links*: a decision is inserted **after the
  activity its `after` names** with its `yes_target`/`no_target` branches; an exception's error edge
  comes from the activity that **`raised_by`** it; a compensation hangs off the exception of the
  activity it **`compensates`** (never blanket-routed to the first one); an event emits from its
  **`emitted_by`** activity; activities sharing a `parallel_group` become a real fork/join. An
  exception with no compensation is routed to a terminal (reject/fail) so it ends the flow instead of
  dangling as a dead-end. References were already validated in Stage 2, so the wiring is grounded — no
  guessing.
- **Positional path — `build(facts)` (fallback).** When only flat facts exist (no structure), the
  builder can't know which decision gates which branch, so it pairs the *i-th* activity with the
  *i-th* decision / exception / compensation. This is plausible but can mis-attribute relationships —
  which is exactly why the relational path exists. It remains for legacy/minimal inputs.

The positional `build()`, step by step:

1. **Categorize** facts into activities/decisions/events/exceptions/retries/compensations/
   transitions (`_categorize`).
2. **Create `start` and `end` nodes** (NodeType.START / END).
3. **Activities → task nodes** (`activity_1`, `activity_2`, …). An activity whose text matches a
   "parallel" regex (`in parallel`, `concurrently`, …) is set aside as a *parallel* branch.
4. **Build the linear spine:** `start → activity_1 → activity_2 → … → end` as a list of `_EdgeSpec`s.
5. **Weave in parallelism:** if any parallel activities exist, insert a `gateway_fork` and
   `gateway_join` so the parallel tasks split and rejoin (`_weave_parallel`).
6. **Weave in decisions:** each decision becomes a `{diamond}` node with a **`yes`** edge to the
   normal next step and a **`no`** edge to the matching exception (or `end`) — guaranteeing both
   branches exist (`_weave_decision`).
7. **Attach exceptions:** a dotted **error** edge from the relevant activity to an exception node;
   if a compensation exists, route exception → compensation → end (saga rollback)
   (`_attach_exception`).
8. **Attach retries:** a **retry** edge from an exception back to the activity it retries
   (`_attach_retry`). (Retry/compensation back-edges are *intended* loops — the reviewer won't flag
   them.)
9. **Attach events:** trigger-like events (`submit`, `receive`, …) connect `start → event → first
   activity`; other events are emitted from the last activity (`_attach_event`).
10. **State transitions:** `"A -> B"` style facts create/reuse `state_*` nodes and connect them
    (`_attach_transition`).
11. **Emit:** de-duplicate edge specs, assign stable ids (`e1`, `e2`, …), and drop any edge whose
    endpoints don't exist (`_emit`). Node ids are stable and meaningful (`activity_3`,
    `decision_1`, `exception_1`, `gateway_fork`).

Node and edge *types* come from `enums.py`: `NodeType` (START/END/TASK/DECISION/GATEWAY/EVENT/…) and
`EdgeType` (SEQUENCE/CONDITIONAL/ERROR/RETRY/COMPENSATION/SIGNAL/…). The `WorkflowGraph` model
enforces an invariant: **node ids must be unique** (validated by Pydantic).

- **Confidence:** based on the breadth of structural fact categories present (more kinds of facts →
  higher) → `confidence_scores.graph`.

### Stage 3b — Mermaid rendering (deterministic)

- **Code:** `graph/mermaid.py` → `to_mermaid(graph)`.
- Produces a `flowchart TD` where node *shape* encodes type: `(["Start"])` for start/end/events,
  `{"Valid?"}` for decisions, `{{"Fork"}}` for gateways, `["Task"]` for tasks. Dotted arrows
  (`-.->`) for error/retry/compensation/signal edges; `-->|label|` for labeled edges.
- **Two hard-won correctness rules** (these were real bugs, now permanent):
  - `end` is a **reserved Mermaid keyword**. Any node id that collides with a reserved word is
    rewritten (`end` → `end_node`) via `_safe_id`, so diagrams render.
  - Edge labels use the **bare** `|label|` form (not quoted), and characters that break the parser
    (`"`, `|`, newlines) are neutralized.

### Stage 4 — Review (deterministic, no LLM)

- **In:** `state.workflow_graph`.
- **Out:** `state.review_report` (a `ReviewReport`). Stage → `REVIEWED`, `approval_status = PENDING`.
- **Code:** `graph/review.py` → `GraphReviewer.review(graph)`, wrapped by the `DefaultReviewManager`.
- **What it checks** (each produces a `ReviewIssue` with a severity and optional suggested fix):
  - missing start / missing end (errors),
  - isolated/disconnected nodes, orphan nodes (no incoming), dead-ends (no outgoing),
  - unreachable subgraphs (can't be reached from start),
  - duplicate nodes (same normalized label),
  - decisions missing a branch,
  - **unintended cycles** — but retry/compensation loops are recognized as intentional and *not*
    flagged.
- **Scoring:** a `health_score` in `[0,1]` computed by penalizing issues by severity weight
  (CRITICAL 0.5, ERROR 0.25, WARNING 0.05); a `confidence` reflecting the reachable fraction of the
  graph. Convenience properties expose `.errors`, `.warnings`, `.suggested_fixes`.

### The approval gate

After Review, `compile_document` **stops** and saves the state with `approval_status = PENDING`.
Nothing downstream runs yet. A human now inspects the graph/diagram/review and decides:

- **Approve** → run CVPA + Temporal (below), set `COMPLETED`.
- **Reject** → set `approval_status = REJECTED`, record the reason in the report summary, **halt**.

This is implemented as two separate operations (`approve_graph` / `reject_graph`) that *load the
saved state by id*, act, and save again — so the gate can span separate CLI invocations or HTTP
requests, even separate processes.

### Stage 5 — CVPA Classification (LLM, post-approval)

- **In:** `state.workflow_graph`.
- **Out:** `state.cvpa_classification` + a **re-colored** Mermaid diagram. Stage → `CLASSIFIED`.
- **Code:** `agents/cvpa.py` → `CVPAClassifierAgent`.
- **The rule that must hold:** *every node is assigned to exactly one phase* — Capture, Validate,
  Process, or Activate. The LLM proposes assignments, but the agent **reconciles** them so the rule
  always holds:
  1. Serialize the graph to compact text and ask the LLM (`classify_cvpa.md`) for `{node_id, phase,
     rationale, confidence}` per node.
  2. Keep only valid assignments (known node id, parseable phase); on duplicates keep the
     highest-confidence one.
  3. **Fill any node the model missed** using a structural fallback keyed on node type
     (START/EVENT→Capture, DECISION/GATEWAY→Validate, TASK/SUBPROCESS/TIMER→Process,
     END/SIGNAL→Activate) at reduced confidence, with a clear "Fallback by node type" rationale.
  4. Build per-phase summaries.
- **Confidence:** blends mean per-node confidence with how much of the coverage came from the model
  vs. fallback → `confidence_scores.cvpa`.
- **Re-coloring:** the agent then calls `to_mermaid_with_cvpa(graph, classification)` and replaces
  `state.mermaid_diagram`. That renderer emits Mermaid `classDef`s and `class` statements so each
  node is colored by phase: **Capture = blue, Validate = amber, Process = green, Activate =
  purple**, Unclassified = grey. This is the "go back and color-code the diagram" step.

### Stage 6 — Temporal Design (LLM, post-approval)

- **In:** `state.workflow_graph` + `state.cvpa_classification`.
- **Out:** `state.temporal_design` (a `TemporalWorkflowDesign`). Stage → `TEMPORAL_DESIGNED`, then
  the compiler marks `COMPLETED`.
- **Code:** `agents/temporal.py` → `TemporalGeneratorAgent`.
- **What it generates** (architecture **specifications only — never executable code**): a workflow
  name + task queue, **activities** (with inputs/outputs/timeouts/retry policies), **signals**
  (human/external waits), **queries** (in-flight state), **child workflows** (subprocesses),
  **timers** (SLAs/deadlines), and **compensation activities** (saga rollbacks naming what they
  undo), plus a default retry policy.
- **How:** render `design_temporal.md` with the graph + CVPA text, call `llm.structured(...,
  TemporalDesignOutput)`, then **normalize**: names are slugged to PascalCase, empty entries and
  zero-duration timers are dropped, retry values are clamped to valid ranges, and the workflow name
  falls back to the metadata name if the model omits it.
- **Confidence:** blends self-reported confidence with design completeness → `confidence_scores.
  temporal`.
- **No-code guarantee:** the design models have no field that could carry source code (a test
  asserts `code`/`body`/`implementation` fields don't exist), and the system prompt explicitly
  forbids emitting SDK code.

---

## 7. Cross-cutting machinery (the parts every stage relies on)

### 7.1 The LLM layer — provider-agnostic by design

The single most important architectural rule: **agents depend only on the abstract
`BaseLLMProvider` interface** (`interfaces/llm.py`), never on a concrete vendor. That interface has
three methods: `complete`, `structured`, `embed`.

```
BaseLLMProvider (abstract: complete / structured / embed)
        ▲
HttpChatProvider (llm/base.py) — retries, timeouts, JSON extraction, schema validation, logging
        ▲
OpenAICompatibleProvider (llm/providers/openai_compatible.py) — OpenAI-style wire format
        ▲
NemotronProvider (llm/providers/nemotron.py) — NVIDIA base URL, model, "detailed thinking off"

MockProvider (llm/providers/mock.py) — returns queued/canned responses (no network), implements the
                                       same interface directly. Used everywhere in tests.
```

- **`HttpChatProvider.structured(prompt, schema)`** is the workhorse used by every LLM agent. It:
  1. appends the target JSON Schema to the prompt and asks for JSON only,
  2. POSTs the chat request (with retries),
  3. extracts JSON from the reply (`json_utils.extract_json` tolerates stray prose/fences),
  4. validates it into the Pydantic `schema`,
  5. on failure, **re-asks** up to `structured_retries` times, feeding the validation error back to
     the model; if it still fails, raises `SchemaValidationError`.
- **Reliability** lives in `chat()` + `retry_async` (`llm/retry.py`): exponential backoff with
  jitter, retrying only on timeouts, connection errors, and configured HTTP statuses.
- **Auth:** `_auth_headers` adds `Authorization: Bearer <key>` from a `SecretStr` (so the key won't
  print).
- **Provider selection** is data-driven via `ProviderFactory` (`llm/factory.py`): providers register
  under a name (`nemotron`, `openai-compatible`, `mock`); `factory.from_settings()` builds the one
  named in `.env`. **Adding a new vendor never touches agent or compiler code** — you register a
  builder.
- **Why Nemotron has a "detailed thinking off" preamble:** Nemotron "super" models are reasoning
  models that, left alone, emit long chains of thought that slow down and pollute JSON output. The
  preamble keeps responses fast and clean.

### 7.2 Prompts — markdown templates, not hardcoded strings

`prompts/templates/*.md` hold every prompt (`discover_workflow`, `extract_facts`, `build_graph`,
`classify_cvpa`, `design_temporal`, `render_mermaid`). Each file has YAML front-matter declaring its
`variables`. `PromptManager.render("classify_cvpa", workflow_graph=...)` loads (and caches) the
template and substitutes variables (`prompts/loader.py`, `renderer.py`, `manager.py`). Editing a
prompt requires no code change.

### 7.3 State storage — how the gate persists across calls

`interfaces/state_store.py` defines `StateStore` (`save/load/exists/delete/list_ids`). Two
implementations (`storage/`):

- **`FileStateStore`** — writes each state as `<root>/<workflow_id>.json`. Writes are **atomic**
  (temp file + `replace`) so a crash can't corrupt a file, and blocking I/O runs in a thread via
  `asyncio.to_thread`. This is the default (root from `WORKFLOW_COMPILER_STATE_STORE_PATH`).
- **`InMemoryStateStore`** — a dict, deep-copying on save/load so stored state can't be mutated by
  reference. Used in tests.

Missing ids raise `StateNotFoundError`. This store is *why* `compile` (request 1) and `approve`
(request 2, possibly a different process) can work together: the state is durable between them.

### 7.4 Editing the graph — `GraphEditor`

If a reviewer wants to fix the graph before approving, `review/editor.py` → `GraphEditor` offers six
**pure, validated** operations: `add_node`, `remove_node` (drops incident edges), `rename_node`,
`modify_node_type`, `add_edge` (auto-assigns the next `eN` id, validates endpoints), `remove_edge`.
Each returns a **new** validated `WorkflowGraph`; invalid edits raise `GraphEditError` rather than
corrupting state. (The integration tests show a reviewer editing a graph and the change surviving a
save/reload.)

### 7.5 Confidence scores

`models/confidence.py` → `ConfidenceScores` holds a per-stage float in `[0,1]` (`metadata`, `facts`,
`graph`, `cvpa`, `temporal`, `overall`) plus a `notes` dict. Each agent writes its own score via
`model_copy(update=...)` so scores accumulate without clobbering each other.

### 7.6 Errors

`exceptions.py` is a typed hierarchy under `WorkflowCompilerError`: parsing errors
(`UnsupportedFormatError`, `EmptyDocumentError`, …), `CompilationError`, `ApprovalError`,
`GraphEditError`, `StateNotFoundError`, and LLM errors (`ProviderTimeoutError`, `ProviderHTTPError`,
`SchemaValidationError`, …). The API maps these to HTTP codes (below).

### 7.7 Config & logging

`config.py` (pydantic-settings, `.env`) provides `Settings`; `logging.py` sets up Loguru + Rich.
Logs never include the API key.

---

## 8. The orchestrator: `WorkflowCompiler`

`compiler.py` ties it all together. Construction wires the collaborators, defaulting anything not
injected:

```python
WorkflowCompiler(
    llm_provider=...,          # injected; agents use it via the abstract interface
    agents=[...],              # default: [Discovery, FactExtraction, GraphBuilder]
    post_approval_agents=[...], # default: [CVPAClassifier, TemporalGenerator]
    review_manager=...,        # default: DefaultReviewManager (graph reviewer + gate)
    state_store=...,           # default: FileStateStore
)
# Convenience builder used by the CLI and API:
WorkflowCompiler.from_settings()   # provider + file store straight from .env
```

Its methods:

- **`compile_document(text, *, review_mode=True, persist=True)`** — runs the pre-review agents in
  order, reviews, sets `PENDING`/`REVIEWED`, saves, and **returns (stops at the gate)**. If
  `review_mode=False`, it auto-approves and runs the whole pipeline end-to-end in one call (handy
  for automation).
- **`approve_graph(id, *, reviewer=None)`** — loads the saved state, approves it, runs the
  post-approval agents (CVPA → Temporal) via the shared `_finalize_approval`, marks `COMPLETED`,
  saves.
- **`reject_graph(id, *, reviewer, reason)`** — loads, marks `REJECTED` with the reason, saves. No
  LLM needed.
- **`review_graph(id)`** — refresh a stored workflow's review report.
- **`save_state` / `load_state` / `list_states`** — thin pass-throughs to the store.

A subtlety worth knowing: both the gated path (`approve_graph`) and the automated path
(`compile_document(review_mode=False)`) call the same `_finalize_approval(state)` helper, so they
produce identical downstream results; the automated path just doesn't reload from disk.

---

## 9. The three entry points (same engine, three faces)

### 9.1 Library

```python
import asyncio
from workflow_compiler import WorkflowCompiler

async def main():
    compiler = WorkflowCompiler.from_settings()
    state = await compiler.compile_document(open("examples/order_workflow.md").read())
    # ... a human reviews state.review_report / state.mermaid_diagram ...
    final = await compiler.approve_graph(state.workflow_id, reviewer="alice")
    print(final.temporal_design.workflow_name)

asyncio.run(main())
```

### 9.2 CLI (`cli/main.py`, Typer + Rich)

```bash
workflow-compiler compile examples/order_workflow.md         # → prints a workflow_id, stops at gate
workflow-compiler approve <id> --reviewer alice --out wf.mmd # → CVPA+Temporal, writes colored diagram
workflow-compiler reject  <id> --reason "missing branch"     # → halts (no LLM)
workflow-compiler show    <id>                               # → display a stored state (no LLM)
workflow-compiler compile doc.md --auto-approve              # → whole pipeline in one shot
workflow-compiler inspect doc.md --out wf.mmd                # → preview discover→facts→graph, no save
```

Each command builds a provider (or `--provider mock`), constructs a compiler with the file store,
runs the async work, closes the provider, and prints Rich tables (metadata, facts-by-category,
review issues, CVPA assignments, Temporal components). `reject`/`show` build a compiler with **no
LLM** because they don't need one.

### 9.3 HTTP API (`api/app.py`, FastAPI)

| Method | Path | Body | Does |
|---|---|---|---|
| POST | `/compile` | `{document_text, persist?, auto_approve?}` | compile to the gate (or end-to-end) |
| POST | `/approve` | `{workflow_id, reviewer?}` | approve → CVPA + Temporal |
| POST | `/reject` | `{workflow_id, reviewer?, reason?}` | reject |
| GET | `/workflow/{id}` | — | load a stored state |
| GET | `/workflows` | — | list stored ids |
| GET | `/health` | — | liveness |

The compiler is provided once via `get_compiler` (a cached `from_settings()`), and tests override it
with a mock-backed compiler. A small `_guard` helper maps domain exceptions to HTTP codes:
`StateNotFoundError → 404`, `ApprovalError → 409`, `CompilationError → 400`. Run it with
`uvicorn workflow_compiler.api.app:app --reload`; interactive docs live at `/docs`.

---

## 10. A fully worked example (follow the data)

Input (`examples/order_workflow.md`, abridged): *"When a customer submits an order, validate the
payment. If valid, process and ship it. If declined, cancel and notify. Retry shipment up to 3
times; on final failure, release inventory."*

1. **Parse** → `text` (plus format=markdown, char count).
2. **Discovery** → metadata: name "Order Fulfillment", actors [Customer, Warehouse], systems
   [Payment Gateway, OMS], triggers [Order submitted], end states [shipped, cancelled].
3. **Facts** → activities [Validate payment, Process order, Ship order, Notify customer], decisions
   [Is payment valid?], exceptions [Payment declined], retries [Retry shipment], compensation
   [Release inventory].
4. **Graph (deterministic)** → nodes `start, activity_1..4, decision_1, exception_1,
   compensation_1, end`; spine `start→activity_1→…→end`; `decision_1` with `yes`/`no` edges;
   dotted error edge to `exception_1`; retry back-edge; exception→compensation→end. Plus a Mermaid
   diagram. (A real run produced a 7-node graph at **health 1.0**.)
5. **Review** → no errors; `health_score = 1.0`; `approval_status = PENDING`. **Saved to disk;
   pipeline stops.** You get a `workflow_id`.
6. **Approve** (`approve_graph(id)`):
   - **CVPA** → every node labeled: `start`→Capture, `decision_1`→Validate, `activity_*`→Process,
     `end`→Activate; nodes the model skipped are filled by the type-based fallback. The diagram is
     **re-rendered with colors** (blue/amber/green/purple).
   - **Temporal** → workflow `OrderFulfillment`, activities (ValidatePayment, ProcessOrder,
     ShipOrder…), a `cancel` signal, a `ReleaseInventory` compensation that `compensates`
     ProcessOrder, a default retry policy.
   - `stage = COMPLETED`, saved.

If instead you **reject**, `approval_status = REJECTED`, the reason is recorded, and CVPA/Temporal
never run.

---

## 11. Testing strategy

- **Unit tests** per component (models, ingestion, LLM layer with `httpx.MockTransport`, prompts,
  each agent, graph builder/reviewer/mermaid, GraphEditor, state stores).
- **Integration tests** (`tests/test_integration.py`) run the **whole pipeline** against a
  `MockProvider` + `InMemoryStateStore`: gated path, auto-approve path, reject-halts, disk
  persistence + reload across two compiler instances, GraphEditor round-trip, and CVPA exactly-once
  coverage.
- **API tests** drive every endpoint with a mock-backed compiler via `dependency_overrides`.
- **Relational extraction tests** (`tests/test_relational_structure.py`) cover the referential-
  integrity guard (dangling ids are dropped) and the semantic wiring (relations attach to the right
  nodes, parallel groups become gateways).
- No network is required for the suite. Run `pytest` and `ruff check src tests`.

Because the LLM is hidden behind `BaseLLMProvider`, the `MockProvider` returns *queued* structured
responses in order — e.g. `[discovery, facts, cvpa, temporal]` — letting tests drive the exact path
deterministically.

---

## 12. How to extend it

- **Add an LLM vendor:** subclass `OpenAICompatibleProvider` (or `HttpChatProvider` for a different
  wire format), then `ProviderFactory().register("myvendor", MyProvider)`. Nothing else changes.
- **Add a document format:** implement `BaseDocumentParser` and register it with
  `DocumentParserFactory`.
- **Swap persistence:** implement `StateStore` (e.g. SQLite/S3) and pass it to the compiler.
- **Change a prompt:** edit the markdown in `prompts/templates/` — no code change.
- **Add a pipeline stage:** write a `BaseAgent` subclass and add it to `agents` or
  `post_approval_agents`.

---

## 13. File map (where everything lives)

```
src/workflow_compiler/
  __init__.py          Public exports (WorkflowCompiler, stores, providers, …)
  compiler.py          WorkflowCompiler — orchestrates the whole pipeline + the gate
  config.py            Settings from .env (pydantic-settings)
  env.py               Loads .env into the environment (python-dotenv)
  logging.py           Loguru + Rich logging
  exceptions.py        Typed exception hierarchy

  models/              Pydantic artifacts:
    state.py           WorkflowState (the aggregate)
    enums.py           CompilationStage, NodeType, EdgeType, CVPAPhase, FactCategory, …
    metadata.py facts.py structure.py graph.py review.py cvpa.py temporal.py mermaid.py confidence.py

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
    serialization.py   compact graph/CVPA text for prompts

  graph/               Deterministic graph machinery (no LLM)
    builder.py         WorkflowGraphBuilder (facts → graph, NetworkX)
    mermaid.py         to_mermaid / to_mermaid_with_cvpa (CVPA coloring)
    review.py          GraphReviewer (structural QA + health score)

  review/              The approval gate + editing
    manager.py         DefaultReviewManager (review/approve/reject)
    editor.py          GraphEditor (validated, immutable edits)

  storage/             State persistence
    file.py            FileStateStore (atomic JSON on disk)
    memory.py          InMemoryStateStore

  api/                 FastAPI app (app.py, schemas.py, dependencies.py)
  cli/                 Typer CLI (main.py)

examples/              Sample business documents (order, onboarding)
docs/                  architecture.md, HOW_IT_WORKS.md (this file)
tests/                 Unit + integration + API tests
```

---

## 14. Gotchas & "why is it like that?"

- **`end` in Mermaid** is reserved and silently breaks diagrams; node ids that collide are renamed
  (`end` → `end_node`). Edge labels must be unquoted. Both are handled automatically.
- **The graph builder never calls the LLM** — by design, for determinism and testability. If a graph
  looks wrong, the fix is in the *facts* or the *builder rules*, not a prompt. Note the distinction:
  *wrong nodes* (missing/extra entities) is an extraction problem; *wrong wiring* (edges to the wrong
  place) means either the relational `structure` was absent (so the positional fallback guessed) or
  the LLM linked the wrong ids — the referential-integrity validator only drops links to *undeclared*
  ids, it can't catch a link to the wrong *declared* id.
- **CVPA always covers every node** even if the LLM is incomplete, thanks to the type-based fallback
  — so the "exactly one phase per node" rule can never be violated downstream.
- **Temporal output is a design, not code** — intentionally. It's an architecture spec for engineers
  to implement.
- **The API key** is held as a `SecretStr`, sent only as a bearer header, and never logged or
  printed.
- **Reasoning-model latency:** Nemotron's "detailed thinking off" preamble and generous timeouts
  keep structured calls fast and parseable.
- **The gate is durable:** because state is persisted, `compile` and `approve` can be separate
  commands, requests, or processes — minutes or days apart.

---

> Want the 30-second version? **A document goes in; agents (LLM for understanding, pure functions
> for structure) progressively fill one `WorkflowState`; a human approves the reviewed graph; then
> CVPA labels every node and a Temporal design is produced — all swappable behind clean interfaces,
> all persisted, all tested without a network.**
