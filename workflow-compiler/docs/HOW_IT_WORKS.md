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
| **Temporal design** | A blueprint for implementing the workflow on [Temporal](https://temporal.io) (activities, signals, retries, compensations) — *specifications only, not code* — including a typed **plan IR** that orders the "categories of action" and binds each step's inputs to the workflow input or earlier step outputs. |
| **Temporal code bundle** | Runnable Temporal Python SDK source files (`shared.py`, `activities.py`, `workflow.py`, `worker.py`, `starter.py`, `README.md`) rendered **deterministically** from the design. The LLM never writes this code. |
| **Confidence scores** | How sure the system is about each stage. |

A **human approval gate** sits in the middle: the structured graph is generated and reviewed, then
a person approves (or rejects) it before the final design artifacts are produced. This keeps the
expensive, opinionated outputs (CVPA, Temporal design, Temporal code) tied to a graph a human
signed off on.

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
- **Temporal** — a workflow-orchestration platform. We generate a *design* (specification) for it
  with the LLM **and then deterministically render that design into runnable Temporal Python code**.
- **Plan IR** — the typed intermediate representation inside a Temporal design: an ordered list of
  `TemporalStep` "categories of action" (activity, child workflow, signal gate, timer, parallel,
  branch) whose inputs are explicitly *bound* to the workflow input or an earlier step's output. The
  code generator walks this IR; it is what makes generated code data-flow-correct rather than guessed.
- **Code generator** — a *deterministic* (no-LLM) renderer that turns the approved Temporal design +
  plan IR into Temporal Python SDK source files via Jinja templates (`codegen/temporal/`).
- **WorkflowState** — the single object that flows through the whole pipeline, accumulating
  artifacts. **This is the heart of the system.**
- **Provider** — an implementation of the LLM interface. The real one calls NVIDIA; the `mock` one
  returns canned answers for tests.
- **Progress callback** — an optional observer (`ProgressCallback`) the compiler calls with a timed
  `ProgressEvent` as each step starts and finishes, so callers can render a live "what is happening
  at what time" view without coupling to compiler internals.
- **Sequential review pipeline** — the *default* quality lever on the LLM stages: generate **one**
  canonical output, then improve it with **three sequential review passes**
  (completeness → grounding → consistency) that emit **minimal patches or `no_change`**, never a
  rewrite. Idempotent by construction. On by default. See
  [§7.10](#710-the-sequential-review-pipeline-default-on).
- **Patch** — a single deterministic edit (`add`/`remove`/`modify`/`merge`/`flag`/`no_change`) a
  review pass requests, carrying its supporting **evidence** from the document. Applied by a pure
  *applier*, never by the model.

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
    temporal_design: ...|None      # filled by Temporal design (after approval)
    temporal_code: ...|None         # filled by Temporal code generation (after approval)
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
         → CLASSIFIED → TEMPORAL_DESIGNED → CODE_GENERATED → COMPLETED   (FAILED on error)
```

(The enum also declares a `DIAGRAMMED` value reserved for a future diagram-export stage; the current
pipeline advances `CODE_GENERATED → COMPLETED` directly.)

**The readiness checklist** is computed between fact extraction and graph building. A deterministic
`ChecklistValidator` (`checklist/validator.py`) scores the document against the requirements that
`examples/ideal_temporal_workflow.md` satisfies — a trigger, named inputs, decisions with both
branches, bound compensations, and so on — and attaches the result to `state.checklist`. The spec
layer (§8b) surfaces every uncleared item as an **Open Question** in the workflow's spec file; the
user's answers are folded back in as **deterministic local amendments** (`checklist/amend.py`) — no
LLM re-run — at spec approval, and unmet *required* items become blocking findings there.

---

## 4. The pipeline at a glance

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

Three crucial design rules:

1. **LLM where judgment is needed, determinism where correctness is needed.** Reading prose and
   classifying are LLM jobs. *Building the graph, reviewing it, and generating Temporal code are pure
   functions* — same input in, same output out, every time, no model involved.
2. **The gate splits the pipeline.** `compile_document` runs everything up to and including Review,
   then stops. `approve_graph` runs the rest (CVPA → Temporal design → Temporal code). This is what
   makes the human-in-the-loop real.
3. **The LLM specifies; the generator emits code.** The Temporal *design* stage (LLM) produces a
   specification — names, parameters, policies, and a typed plan IR — but never source code. A
   separate *deterministic* generator renders that approved design into runnable Temporal Python.

Every stage is observable: the compiler emits timed `start`/`done` `ProgressEvent`s to an optional
`ProgressCallback`, which the CLI renders as a live, timestamped step log.

The orchestrator that runs all of this is `WorkflowCompiler` (`src/workflow_compiler/compiler.py`).
It is the **engine**; the user-facing entry point is the spec-centric `ProjectCompiler` front-end
(§8b), where the human gate is the editable spec files and the graph gate above becomes an
automatic health-score threshold (with `approve`/`reject` as the manual override).

---

## 5. Installation & configuration (so the rest makes sense)

Installation and configuration are two steps. A wheel cannot run code at install time, so `pip`
cannot write the configuration for you — `init` is a command the user types.

```bash
# Requires Python 3.12+ (use a virtual environment — see README.md for full steps)
pip install .                    # installs the package + the `workflow-compiler` CLI
workflow-compiler init           # asks for provider + credentials, writes .env
```

Contributors install `pip install -e ".[dev]"` instead — `-e` keeps the install pointed at the
working tree, `[dev]` adds `pytest`/`ruff`/`mypy` (README §Develop).

`init` is non-interactive with `--yes`, which is what CI and containers use:

```bash
workflow-compiler init --provider mock --yes                       # offline, no key
workflow-compiler init --provider nemotron --nvidia-api-key "$K" --yes
```

It accepts `--provider` (`nemotron` | `local` | `local-fallback` | `mock`), `--nvidia-api-key`,
`--env-file` (default `./.env`), `--force` (replace an existing file), and `--yes`. Rendering
lives in `cli/init_env.py::render_env` — a pure function of its arguments, so the generated file
is tested without a terminal (`tests/test_cli_init.py`). `init` never validates credentials
against a live provider; it writes the file and names anything still missing.

The result — `.env`, read by `config.py` via `python-dotenv`:

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
  parsing produces readable plain text that **keeps the `#` heading markers** (multi-workflow
  segmentation slices by them) and **preserves snake_case identifiers verbatim** — emphasis
  stripping only applies at word boundaries, so `order_id` can never be mangled into `orderid`
  (the field names are what workflow inputs/outputs and cross-references bind by).

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
- **Quality lever:** by default the agent is wrapped in the **sequential review pipeline**, which
  generates this metadata once and then runs three review passes over it (completeness / grounding /
  consistency) to fill gaps, drop ungrounded items, and merge equivalent labels — see
  [§7.11](#711-the-sequential-review-pipeline-default-on). (This codebase discovers one workflow per
  document, so the "workflow review" passes operate on the metadata's lists.)

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
- **Quality lever:** by default this stage (and discovery) is wrapped in the **sequential review
  pipeline** — generate once, then completeness/grounding/consistency review passes that patch the
  facts in place (see [§7.10](#710-the-sequential-review-pipeline-default-on)).

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

- **Approve** → run CVPA → Temporal design → Temporal code generation (below), set `COMPLETED`.
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

- **In:** `state.workflow_graph` + `state.cvpa_classification` + `state.workflow_facts`.
- **Out:** `state.temporal_design` (a `TemporalWorkflowDesign`). Stage → `TEMPORAL_DESIGNED`.
- **Code:** `agents/temporal.py` → `TemporalGeneratorAgent`.
- **What it generates** (architecture **specifications only — never executable code**), in two layers:
  - **Declarations** — a workflow name + task queue, typed `workflow_inputs`, **activities** (with
    typed params, outputs, result type, timeouts, retry policies), **signals** (human/external
    waits), **queries** (in-flight state), **child workflows** (subprocesses), **timers**
    (SLAs/deadlines), and **compensation activities** (saga rollbacks naming the activity they undo),
    plus a default retry policy.
  - **Plan IR (`plan`)** — an ordered list of `TemporalStep` "categories of action"
    (`activity` / `child_workflow` / `signal_gate` / `timer` / `parallel` / `branch`). Each step
    carries `bindings` that source every input from the **workflow input**, an **earlier step's
    output**, or a **constant** (`BindingSource`), and a `result_name` so later steps can consume it.
    `parallel`/`branch` steps nest child steps in `lanes`. This IR is the explicit control-and-data
    flow the code generator walks; when the model omits it, the generator synthesizes a linear plan
    from the declarations in graph order (backward compatibility).
- **How:** render `design_temporal.md` with the graph + CVPA + **facts** text (so retries, timeouts,
  compensations, and I/O are *derived from the document* rather than guessed), call `llm.structured(
  ..., TemporalDesignOutput)`, then **normalize**: names are slugged to PascalCase, empty entries and
  zero-duration timers are dropped, retry values are clamped to valid ranges, unknown step kinds /
  binding sources are coerced to safe defaults, and the workflow name falls back to the metadata name
  if the model omits it.
- **Confidence:** blends self-reported confidence with design completeness → `confidence_scores.
  temporal`.
- **No-code guarantee:** the design models have no field that could carry source code (a test
  asserts `code`/`body`/`implementation` fields don't exist), and the system prompt explicitly
  forbids emitting SDK code. The runnable code is produced by the *separate, deterministic* Stage 7
  — so "the LLM specifies, templates emit code" holds.

### Stage 7 — Temporal Code Generation (deterministic, no LLM, post-approval)

- **In:** `state.temporal_design` (required) + `state.workflow_graph` (for ordering when the plan IR
  is absent).
- **Out:** `state.temporal_code` (a `TemporalCodeBundle` of `GeneratedFile`s). Stage →
  `CODE_GENERATED`; the compiler then marks the run `COMPLETED`.
- **Code:** `agents/temporal_code.py` → `TemporalCodeGeneratorAgent` (a no-LLM agent, like the graph
  builder), delegating to `codegen/temporal/generator.py` → `TemporalPythonCodeGenerator`.
- **How it works:** like the graph builder, this is a renderer, not a model. It walks the design's
  **plan IR** and emits the body of `@workflow.run` *in Python* (where it is unit-testable), while
  Jinja templates render the surrounding file skeletons and the simple signal/query/timer/child
  declarations:
  - **activity / child_workflow** → `await workflow.execute_activity(...)` /
    `execute_child_workflow(...)`, constructing the typed input dataclass and binding each field from
    its `InputBinding` (workflow input → `arg.<field>`, step output → that step's result variable,
    constant → the dataclass default). The result is captured into `result_name`.
  - **signal_gate** → `await workflow.wait_condition(lambda: self._<signal>_received)`. When the
    design declares a timer that pairs with the signal (the step's explicit `timer` ref, or the
    unique timer sharing a meaningful name token — `carrier.picked_up` ↔ `CarrierPickupTimeout`),
    the wait is **bounded**: `wait_condition(..., timeout=<TIMER_CONST>)`, so a signal that never
    arrives raises `TimeoutError` and fires the saga compensations instead of blocking forever.
    Only a gate with no pairable timer stays unbounded, marked with an explicit TODO.
  - **timer** → `await workflow.sleep(<TIMER_CONST>)` using the declared duration.
  - **parallel** → concurrent calls via `asyncio.gather(...)` (the workflow template only imports
    `asyncio` when a parallel step is actually present). Each lane's result is **captured
    positionally** from the gather so a later step can bind to it (no discarded results → no
    `NameError`).
  - **branch** → a real `if/else`. When the design bound the branch to a data dependency it
    branches on that expression (`if bool(<expr>):`). When the predicate is a simple comparison
    whose identifier resolves to a known step result or workflow input
    (`eligibility == 'eligible'`), the **real condition is emitted as code**
    (`should_x = eligibility == 'eligible'`). Only when neither resolves does it emit an explicit
    placeholder flag (`should_<predicate> = True  # TODO`) — named and commented, never a silent
    literal `if True` — defaulting to the main (then) path so the stub bundle runs out of the box.
  - **Saga compensation** — every activity that has a registered compensation appends
    `(comp_fn, comp_input)` to a `compensations` list — including activities **inside a parallel
    group** (registered after the gather succeeds). The compensation input is built from the
    compensation's own `bindings` (so a `release`/`reverse` receives the id it must undo), not an
    empty dataclass. On any exception the `@workflow.run` body fires the compensations **in
    reverse** before re-raising, retrying each with the workflow's default retry policy and setting
    `self._status = "compensated"`. Compensations are matched to their activity by normalized
    (PascalCase) name, so casing differences don't break the link.
- **The emitted bundle** is six files written in order: `shared.py` (input dataclasses),
  `activities.py` (`@activity.defn` stubs that log and **return a typed placeholder** with a
  `# TODO`, so `python worker.py` + `python starter.py` run the workflow end-to-end out of the
  box — replace the placeholder with real logic), `workflow.py`
  (`@workflow.defn` with the generated run body, signals, queries), `worker.py` (registers the
  workflow + activities on the task queue), `starter.py` (a client that starts one execution), and
  `README.md` (run instructions). They use **flat, absolute imports** (`from activities import ...`)
  and are each run directly from inside the package directory — matching the Temporal Python docs, so
  no package install or `PYTHONPATH` is needed. See `docs/TEMPORAL_CODEGEN_FINDINGS.md` for the
  standard this satisfies (and the earlier hallucinations it was built to prevent).
- **Confidence/notes:** records `"<n> files for package '<name>'"` in `confidence_scores.notes`.

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
GatewaySessionProvider (llm/providers/gateway.py) — local eGPU gateway; email+password session auth
                                       (login → cookie/bearer, expiry refresh, 401 re-login),
                                       model discovery via /auth/config

FallbackProvider (llm/providers/fallback.py) — composite: try the local gateway (primary), fall back
                                       to Nemotron on unreachable/timeout/HTTP-5xx; auth/4xx errors
                                       surface. Implements BaseLLMProvider directly.

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
  under a name (`nemotron` (default), `local`, `local-fallback`, `openai-compatible`, `mock`);
  `factory.from_settings()` builds the one named in `.env`. **Adding a new vendor never touches agent
  or compiler code** — you register a builder.
- **Local eGPU gateway + fallback (opt-in).** `local-fallback` makes a local gateway the primary LLM
  and Nemotron the automatic safety net. The gateway (`GatewaySessionProvider`) is OpenAI-compatible
  for chat but authenticates with **email+password** (`LLM_GATEWAY_EMAIL`/`LLM_GATEWAY_PASSWORD`) —
  it logs in lazily, replays the session as a bearer token, refreshes before expiry, and re-logs-in
  once on a 401. `FallbackProvider` delegates each call to the gateway and, only on
  `ProviderConnectionError`/`ProviderTimeoutError`/HTTP-5xx, retries on Nemotron (caching "down"
  briefly); auth failures and other 4xx surface instead of being masked. Model discovery reads the
  gateway's public `/auth/config` (no auth) — exposed via `workflow-compiler models`,
  `GET /providers/local/models`, and the frontend picker; the per-compile `model` selection is
  applied by injecting a provider built with that local-model override.
- **Why Nemotron has a "detailed thinking off" preamble:** Nemotron "super" models are reasoning
  models that, left alone, emit long chains of thought that slow down and pollute JSON output. The
  preamble keeps responses fast and clean.

### 7.2 Prompts — markdown templates, not hardcoded strings

`prompts/templates/*.md` hold every prompt (`discover_workflow`, `discover_workflows`,
`extract_facts`, `classify_cvpa`, `design_temporal`, plus the review/validator pass prompts). Only
LLM stages have templates — graph building, Mermaid rendering, and code generation are
deterministic and prompt-less. Each file has YAML front-matter declaring its
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

### 7.8 The Temporal code-generation layer (`codegen/temporal/`)

This is the deterministic counterpart to the LLM Temporal-design agent, and it mirrors the graph
builder's "no model, pure function" philosophy:

- **`generator.py` → `TemporalPythonCodeGenerator`** — owns the Jinja `Environment` (over the bundled
  `templates/`, with `StrictUndefined` so a missing template variable fails loudly) and the
  `_RunBodyEmitter` that walks the plan IR to produce the `@workflow.run` body in Python. Helpers
  `_snake`/`_pascal` make safe identifiers; `_retry_expr`/`_timeout_expr` render `RetryPolicy(...)`
  and `timedelta(...)` expressions; `_synthesize_plan` builds a linear plan (topologically ordered
  over the graph's forward "backbone" edges) when the design has no plan IR.
- **`templates/*.jinja`** — `shared.py.jinja`, `activities.py.jinja`, `workflow.py.jinja`,
  `worker.py.jinja`, `starter.py.jinja`, `README.md.jinja`. The workflow template injects the
  emitted `run_body` and conditionally imports `asyncio` only when a parallel step is used. Templates
  emit *file skeletons and simple declarations*; the complex control/data-flow body is emitted in
  Python (in `generator.py`) precisely because that is the part worth unit-testing.
- **Why split Python-emitted body vs. Jinja skeletons?** The risky logic (data threading, saga
  rollback, gather/branch) lives where tests can exercise it directly; the boilerplate lives in
  templates where it's easy to read and tweak.

The agent wrapper (`agents/temporal_code.py`) is what plugs this into the pipeline; the generator is
also usable standalone via `to_temporal_python(design, graph=...)`.

### 7.9 Progress & observability

`compiler.py` defines a small observer protocol so any caller can watch the pipeline run live without
reaching into internals:

- **`ProgressEvent`** (frozen dataclass) — `phase` (`"agent"`/`"review"`/`"approve"`), `name`,
  `status` (`"start"`/`"done"`), 1-based `index`/`total` within its sub-pipeline, and on `"done"` the
  elapsed `seconds` and resulting `stage`.
- **`ProgressCallback`** — `Callable[[ProgressEvent], None]`, passed to `compile_document` /
  `approve_graph`. The compiler wraps every call in `_emit`, which **swallows observer exceptions** so
  a misbehaving progress sink can never break a compilation.
- `_run_agents` emits a timed `start`/`done` pair around each agent; the review and approve steps emit
  their own. The CLI's `_make_progress()` renders these as timestamped lines
  (`12:34:58 OK 2/3 temporal-generator  1.42s -> temporal_designed`), using ASCII markers (`>>`/`OK`)
  so output is safe when piped on Windows (cp1252) consoles.
- **Nested sub-steps:** before running each agent, `_run_agents` hands any agent exposing a
  `set_progress(report)` hook a **nested sub-reporter**. `ReviewPipelineAgent` uses it to emit a
  `phase="review-pass"` `start`/`done` pair around its canonical generation (`generate`) and each
  review pass (`review:completeness`, `review:grounding`, `review:consistency`). The CLI renders these
  **indented under the parent agent** with a quieter marker, so a live run shows the review pipeline's
  internal stages — e.g. `> 2/4 review:grounding  0.71s` — not just one opaque line. The agent stays
  decoupled from `ProgressEvent`: it calls `report(name, status, index, total, …)` and the compiler's
  `_sub_reporter` builds the event.

### 7.10 The sequential review pipeline (default-on)

The **default** way the LLM stages raise accuracy. The review pipeline follows a compiler
discipline: **generate one canonical output, then improve it with three specialized review
passes.** It never regenerates the artifact — each pass emits only **minimal patches or
`no_change`**.

- **The three passes** (`agents/review_pipeline.py` → `ReviewPass`), run in order, each feeding the
  next:
  1. **completeness** — add workflow elements *explicitly in the document but missing* from the
     output (allowed action: `add`). No renaming, no inference.
  2. **grounding** — `remove`/`flag` any element *not explicitly supported* by the document. Only
     textual evidence counts; implied business knowledge never does.
  3. **consistency** — `merge` duplicates / semantically-equivalent labels, `modify` to a canonical
     label or to fix a relation. No new elements are invented.
- **Patches, not rewrites** (`models/patch.py`): a pass returns a `ReviewResult` of `Patch`es, each
  an `add`/`remove`/`modify`/`merge`/`flag`/`no_change` carrying `Evidence` (quote / section /
  offsets where practical). The model proposes; a **deterministic `PatchApplier`** disposes —
  applying each patch as a pure function. `MetadataPatchApplier` edits the single `WorkflowMetadata`
  (the "workflow discovery" artifact — this codebase extracts one workflow per document, so the
  workflow-review passes operate on its lists: actors/systems/triggers/states); `FactsPatchApplier`
  edits the `WorkflowFacts` + relational `WorkflowStructure`.
- **Grounded + idempotent by construction:** the applier drops any `add` that duplicates an existing
  element (case-insensitively) or fails a reference-free grounding check (quote substring or
  majority token-overlap against `document_text`). After applying, `FactsPatchApplier` re-runs
  `WorkflowStructure.validated()` so a patched relation can only point at a *declared* entity. The
  net effect: running a pass again over an already-reviewed artifact yields `no_change` — the
  defining property the passes are built to guarantee.
- **Generic framework:** a stage is bound to the engine by a `ReviewSpec`
  (extract / serialize / apply-to-state + the three prompt names + the applier).
  `ReviewPipelineAgent` wraps the inner generator agent, runs it once,
  then the three passes, and records per-pass provenance ("completeness: 1 applied, 2 dropped; …")
  in `confidence_scores.notes[<stage>_review]`. Adding a review pipeline for a future stage
  (Mermaid, Temporal) is a new spec + three prompts — no engine change.
- **Prompts:** `prompts/templates/review_{workflow,facts}_{completeness,grounding,consistency}.md`,
  each documenting its pass's responsibility and allowed actions.
- **Precedence and default:** on by default (`--review` / `WORKFLOW_COMPILER_REVIEW_ENABLED`).
  Per stage the compiler chooses **review → plain**: the review pipeline runs on any stage it is
  enabled for, otherwise the plain agent.
- **The honest boundary:** the passes raise grounding/consistency but
  cannot certify semantic truth — a misreading the generator and all three reviewers share survives.
  The human spec gate remains the oracle; flagged elements are what a reviewer should scrutinize.

Cost note: review adds three (sequential) LLM calls per reviewed stage. It is on by default because
those calls are cheap relative to a wrong graph reaching the human gate; disable with `--no-review`.

---

## 8. The orchestrator: `WorkflowCompiler`

`compiler.py` ties it all together. Construction wires the collaborators, defaulting anything not
injected:

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

- **`compile_document(text, *, review_mode=True, persist=True, workflow_id=None, progress=None)`** —
  runs the pre-review agents in order, reviews, sets `PENDING`/`REVIEWED`, saves, and **returns
  (stops at the gate)**. If `review_mode=False`, it auto-approves and runs the whole pipeline
  end-to-end in one call (handy for automation). `progress` receives live `ProgressEvent`s.
- **`approve_graph(id, *, reviewer=None, persist=True, progress=None)`** — loads the saved state,
  approves it, runs the post-approval agents (CVPA → Temporal design → Temporal code) via the shared
  `_finalize_approval`, marks `COMPLETED`, saves.
- **`reject_graph(id, *, reviewer, reason)`** — loads, marks `REJECTED` with the reason, saves. No
  LLM needed.
- **`review_graph(id)`** — refresh a stored workflow's review report.
- **`save_state` / `load_state` / `list_states`** — thin pass-throughs to the store.

A subtlety worth knowing: both the gated path (`approve_graph`) and the automated path
(`compile_document(review_mode=False)`) call the same `_finalize_approval(state)` helper, so they
produce identical downstream results; the automated path just doesn't reload from disk.

---

## 8b. The spec-centric front-end: `ProjectCompiler`

Everything above describes the classic single-document pipeline, which remains unchanged. For
**large documents describing several workflows** — where downstream quality degrades because every
stage reasons about the whole document at once — a second orchestrator, `ProjectCompiler`
(`project_compiler.py`), layers a *spec-centric* front-end on top:

```
Document ─▶ Segmentation ─▶ per-workflow Discovery+Facts ─▶ one WorkflowSpec per workflow
         ─▶ spec .md files on disk      [SPEC GATE: the user edits ⇄ `validate`]
         ─▶ approve-spec ─▶ per workflow: Graph ─▶ auto-review ≥ threshold ─▶ CVPA
                            ─▶ Temporal design ─▶ Temporal code
```

The pieces, and where they live:

- **Segmentation** (`agents/segmentation.py` → `WorkflowSegmentationAgent`): one LLM call
  enumerates *every* distinct workflow, the document sections belonging to each, and any
  **output→input dependencies** between workflows (`prompts/templates/discover_workflows.md`),
  improved by the same three-pass review discipline (completeness / grounding / consistency with
  a deterministic `SegmentationPatchApplier`). Deterministic code then slices the document per
  workflow — so fact extraction sees **only its own workflow's text**, which is the
  scope-isolation win this front-end exists for. A single-workflow document yields one segment
  holding the full text (the classic path's behavior, unchanged).
- **The project aggregate** (`models/project.py` → `CompilationProject`): document text, segments,
  one `WorkflowSpec` per workflow, typed `CrossReference`s, the spec approval status, and a
  `ProjectStage` (`INGESTED → WORKFLOWS_DISCOVERED → SPEC_DRAFTED → SPEC_VALIDATED →
  SPEC_APPROVED → COMPILING → COMPLETED | NEEDS_ATTENTION`). Persisted by
  `storage/project_store.py` under `<state-root>/projects/`. `WorkflowState` stays the
  per-workflow unit — it only gained an optional `project_id` back-link.
- **The spec is the source of truth; Markdown is a projection.** `WorkflowSpec` (`models/spec.py`)
  bundles the metadata + facts/structure with review-surface lists (assumptions, ambiguities,
  **open questions** — the readiness checklist absorbed as fill-in questions — and suggested
  edits), each element carrying **provenance**: `document_grounded`, `llm_inferred`, or
  `human_provided`. `spec/renderer.py` renders it to a strict-grammar Markdown file;
  `spec/ingest.py` parses edits back **deterministically** and merges them onto the existing model
  (ids preserved, unrendered fields survive, `WorkflowStructure.validated()` re-run). A test
  asserts the round trip is the identity — this is what keeps the compiled graph a pure function
  of what the human approved, with no LLM between the gate and the graph.
- **The edit ⇄ validate loop.** `validate_specs` ingests the edited files and runs three review
  passes over each spec *against the original document* (`spec/validator.py`,
  `prompts/templates/review_spec_*.md`). The applier is **provenance-aware**: unsupported
  machine-extracted elements are removed, but a `remove` aimed at a *human-provided* element is
  converted into a finding ("please confirm") — the validator challenges human additions, never
  deletes them. Findings land in `project.validation_findings` and the re-rendered files.
- **Approval → the unchanged back-end.** `approve_spec` requires the cross-references to be
  user-confirmed (checkboxes), folds answered open questions in via the existing deterministic
  `checklist/amend.py`, seeds one `WorkflowState` per spec (its `document_text` is the **rendered
  spec**, so CVPA/Temporal prompts see the normalized artifact instead of the raw document), and
  calls `WorkflowCompiler.compile_prepared`. The old human graph gate becomes a **threshold
  gate**: review `health_score ≥ settings.graph_health_threshold` (default 0.9) auto-approves and
  runs CVPA → Temporal design → code; below it the workflow stays `PENDING` (the classic
  `approve <workflow-id>` is the manual override) and the project is marked `NEEDS_ATTENTION`.

- **Edit requests (changing compiled workflows later).** `edit_specs` applies a structured
  **edit-request document** (`docs/EDIT_FORMAT_GUIDE.md`): `spec/edit_ingest.py` parses the
  skeleton deterministically and fails fast (unknown slug, unknown block, reserved split/merge
  syntax — all before any LLM call); `agents/edit_interpreter.py` translates each section's
  natural-language bullets into an `EditPlan` (`models/edit.py` — `Patch`es plus typed
  `TriggerOp`/`XrefOp` wiring ops); `spec/edit_applier.py` applies them with **human authority**
  (`SpecPatchApplier(human_authority=True)`): no grounding requirement on adds (they become
  `human_provided`), removals honored even for human-provided or referenced elements (dangling
  references pruned). The edit is **atomic** — worked on a deep copy, aborted whole on any
  unresolved entry or inapplicable patch (the error names the dropped operations; an add whose
  value is already present is skipped as satisfied instead, with a summary line). Success bumps
  each edited spec's version, appends an
  `EditRecord` to `project.edit_log` (the audit trail), and resets the stage to `SPEC_DRAFTED`
  so the normal validate → approve-spec gate re-runs over the changed specs. `## Add Workflow:`
  bodies run through the standard discovery + facts pipeline (and are appended to
  `document_text` so grounding passes can see them); `## Remove Workflow:` drops the spec and
  every trigger/dependency touching it.

- **Preview → confirm.** `preview_edit` dry-runs the same pipeline (nothing persisted) and
  returns the would-be summary/diff plus a `ResolvedEdit` blob — the interpreted plans, drafted
  add-workflow specs, measured timings, and a fingerprint over the project state + document.
  Confirming (`edit_specs(resolved=...)`, or `POST /projects/{id}/edit` with `resolved`)
  replays those plans with **no LLM call**, so what applies is exactly what was previewed; any
  project change in between makes the fingerprint stale (`EditPreviewStaleError` → HTTP 409 →
  preview again). The CLI's `edit --dry-run` prints the same preview and simply re-interprets
  on the real run.

- **Time saved.** Each pipeline step's wall-clock seconds accumulate in
  `project.stage_timings`; `metrics.py` compares them against the configurable
  `baseline_hours` human-team **estimates** (per step category: discovery / spec / validate /
  compile / edit) to produce `time_saved` on project responses and the `GET /metrics/summary`
  aggregate shown in the web UI. No timings recorded → no claimed savings.

CLI: `compile <doc> --spec-dir <dir>` → edit the files → `validate <project-id>` →
`approve-spec <project-id>` (code lands under `./generated/<project-id>/<slug>/`); later
changes via `edit <project-id> <edit-file.md>` (add `--dry-run` to preview) → `validate` →
`approve-spec`. HTTP (all project/workflow routes behind local-account cookie auth —
`/auth/register`, `/auth/login`, `/auth/me`; projects are shared across users by default,
with `owner_id` kept for attribution — set `WORKFLOW_COMPILER_PROJECTS_SHARED=false` to scope
listings/access to each project's `owner_id`):
`POST /projects/compile`, `GET/PUT /projects/{id}/spec`, `POST /projects/{id}/edit` (+
`/edit/preview`), `POST /projects/{id}/validate`, `POST /projects/{id}/approve`,
`GET /metrics/summary`.

### Cross-workflow triggers (standalone workflows, explicit starts)

When one workflow starts another ("if the application is approved, provisioning begins"), the
relationship compiles to an **explicit trigger between independent workflows** — never a
Temporal child workflow. The full path:

1. **Discovery.** Segmentation extracts explicit triggers (source, target, condition, mode)
   alongside data dependencies; deterministic assembly turns both into `WorkflowTrigger`
   scaffolds (a data dependency contributes a typed `input_map` row to its pair's trigger).
2. **Review.** Triggers render in each source workflow's **Triggers** spec section (checkbox =
   confirmed, ``when `…` `` = the predicate, indented `input` lines = the typed hand-off) and
   round-trip through ingest like everything else.
3. **Validation (deterministic, no LLM).** Unknown target or an `input_map` field the target
   doesn't declare → `BLOCKING`; type mismatch / unconfirmed predicate / blocking trigger with
   no result binding → `WARNING`. `validate` exits non-zero on blocking findings and
   `approve-spec` refuses while they remain.
4. **Design.** Approval copies the slug's triggers to `WorkflowState.outgoing_triggers` and
   injects `TriggerNode`s into the structure (graph: `NodeType.TRIGGER`). The design agent
   deterministically appends `TemporalTriggerDesign` declarations + plan `TRIGGER` steps —
   a conditional trigger becomes a `BRANCH` whose then-lane holds the trigger step.
5. **Codegen.** The *source* bundle gains `triggers.py`: one activity per target that connects
   a client (`TEMPORAL_ADDRESS`) and calls `client.start_workflow("<TargetType>", payload,
   id=<deterministic business key>, task_queue=<target queue>,
   id_conflict_policy=USE_EXISTING)`. Blocking mode also `await handle.result()` inside the
   activity. The workflow body calls it via `workflow.execute_activity(...)`.

**Temporal limitations this design answers:** workflow code may not start another workflow
(non-deterministic) → the start lives in an activity; `get_external_workflow_handle` can only
signal/cancel an already-running workflow → starting is always by client;
activity retries could double-start → deterministic workflow id + `USE_EXISTING` dedupes;
a blocking trigger's activity stays open for the target's whole run → it gets a generous
`start_to_close_timeout` (1h) — for longer-running targets, prefer fire-and-forget plus a
callback signal (documented future upgrade). Targets remain byte-identical whether or not
anything triggers them — every workflow always starts standalone via its own `starter.py`.

### Debug surface (inspecting branches and triggers)

Every generated workflow tracks `self._current_step`, `self._decisions_taken`
(`{branch, predicate, taken}` per branch) and `self._triggers_fired`, exposed via read-only
queries `current_step` / `decisions_taken` / `triggers_fired` — no I/O, no wall-clock, safe in
production. The always-generated `test_stepthrough.py` runs the bundle under
`WorkflowEnvironment.start_time_skipping()` with the stub activities (trigger activities
mocked) and prints those queries — run it to see exactly which branch a conditional takes.
Opt into interactive gating with `WORKFLOW_COMPILER_STEPWISE=1`: every top-level plan step then
waits on an `advance` signal (`wait_condition` + signal, so determinism is preserved).

## 8c. Knowledge bases (`kg/`) — a corpus indexed into a graph

A **knowledge base** is a zipped corpus (business docs, mermaid diagrams, source code, tests)
turned into a Context Hub graph that later phases use to *ground* change requests and specs in
the real modules, activities, stories and test cases of an existing system. Phase 0 of the
KG change pipeline (`docs/kg-plan/`) ships the foundation: upload → index → query.

**Engine.** `kg/contexthub/` is a vendored subset of the KG-Context / Context Hub project
(`model/`, `bootstrap/`, `retrieval/`; pinned SHA and every local edit are listed in
`kg/contexthub/VENDORED.md`). It is untyped upstream code excluded from `mypy --strict`; the app
never imports it outside `workflow_compiler.kg`.

**Façade.** `kg/service.py::KgService(store, provider_factory)` is the only surface the rest of the
app uses:

| Method | What it does |
|---|---|
| `create_from_zip(name, bytes)` / `create_from_path(name, dir)` | Safe extraction (`kg/ingest.py`: zip-slip / symlink rejection, size + count caps, one top-level folder stripped) into `<state-root>/knowledge_bases/<kb_id>/corpus/`; record saved with `status="ingesting"`. |
| `index(kb_id, enrich, provider, model, progress)` | Runs `init_repo(corpus, out=…/.contexthub)` in a worker thread. Static ingest is instant; with `enrich` each Document/Module gets one LLM call (summary, topics, entities) plus a clustering pass — through the app's own `BaseLLMProvider` via `kg/llm_bridge.py::ProviderJsonClient` (results cached by content hash under `.contexthub/llm_cache/`). Records `stats` (nodes/edges by type), the business-id `catalog` (Epic/UserStory/TestCase/Requirement ids), `status="ready"` — or `failed` + `error`. |
| `retrieve(kb_id, prompt, budget, max_hops)` | BM25 anchors → bounded traversal → dereferenced file spans, as a `KgPacket` (`rendered` text for prompts, `sections`, `files` with line spans, `coverage`, `low_confidence`). |
| `impact(kb_id, seeds, max_hops)` | Deterministic BFS over dependency-shaped edges (`DEPENDS_ON`, `CALLS`, `IMPORTS`, `IMPLEMENTS`, `RELATES_TO`, `DOCUMENTED_BY`, …; `CONTAINS` only downwards from file nodes). Seeds may be node ids or search terms. Rows are ordered by hops then id. |
| `search`, `catalog`, `graph_summary`, `list_files`, `read_file` | Debug/UI surfaces; `read_file` is path-traversal safe and text-extracts docx/xlsx/pdf. |

Node ids are relative to `corpus/` and POSIX (`mod:existing_Codebase/workflows/order_workflow.py`,
`doc:Business_Docs/epics/EPIC-001-….docx`, `US-003`, `TC-05`, `BR-02`), so a graph built on Windows
dereferences anywhere. Ids crossing the store boundary are validated against `[A-Za-z0-9_-]+`.

**Jobs.** Indexing runs as a `kb_ingest` background job. `JobManager` is keyed by
`scope_id` + `scope_kind` (`project` | `knowledge_base`); `project_id` stays as an alias so
existing callers are unchanged, and jobs carry a `progress` (`message`, `done`, `total`) that the
worker updates per file.

**Config.** `kg_enrich_default` (True), `kg_retrieve_budget` (4000), `kg_max_upload_mb` (50).
KB routes take `provider`/`model` per request like `/projects/compile`; the default is cloud
Nemotron on purpose (enrichment is one call per file and must not land on the single-GPU
gateway unasked).

**Example corpus.** `examples/knowledge_bases/order-lifecycle/` is a verbatim copy of the
manager's `Existing_KG` (BRD, EPIC-001, US-001..005, TDD, test plan, TC matrix, three mermaid
diagrams, the Temporal `OrderWorkflow` code + tests); `scripts/make_kb_zip.py` zips it, and
`examples/change_requests/BCR-001-partial-shipment-support.docx` is the change request the later
phases consume.

## 8d. Change requests (`change/`) — a guided wizard from a BCR to Impact / EPIC / Stories / TDD

A **change request** pairs a business-change document (a BCR `.docx`, or markdown/text) with a
knowledge base. A deterministic wizard walks it through four steps — **Impact → EPIC → Stories →
TDD** — asking a few clarifying questions before each draft and producing one versioned markdown
artifact per step, grounded in knowledge-graph retrievals and a deterministic impact traversal.
Phase 1 of the KG change pipeline (`docs/kg-plan/`).

**Reading the BCR (no LLM).** `change/bcr.py` parses the metadata block (`Document ID`, `Status`,
`Requested By`, `Date Raised`, `Target Workflow`), the numbered requirements (`BCR-01-03 | text`
rows or `ID — text` lines) and *seed terms* for the impact traversal (file names such as
`types.py`, identifiers such as `complete_order`, `TDD §4.3`-style references, `PARTIALLY_*`
states, `US-/TC-/EPIC-` ids). The document itself goes through the normal `DocumentParserFactory`.

**Ids come from the catalog, never from the model.** `change/ids.py` reads
`KgService.catalog(kb_id)` — the ids present in the corpus, now including document ids
(`KbCatalog.documents`, regexed from the ingest extracts) — and mints the next free ones:
`EPIC-002` after `EPIC-001`, `US-008…` after `US-001..007`, `TDD-ORD-002` after `TDD-ORD-001`,
`TC-18` for Phase 4. The drafting prompts receive them in the brief and the engine overwrites
whatever the model returns.

**The wizard (`change/engine.py::ChangeWizardEngine`).** Per step: `start_step` (the
`ChangeAnalystAgent` drafts 2–5 clarifying questions with grounded suggested options) →
`answer` (each prose answer becomes one brief line; at most **one** follow-up, like the Resolve
dialogue; unmappable answers are recorded verbatim) / `skip` → `draft` (assemble the **brief** =
BCR text + requirements + assigned ids + the requester's decisions + the deterministic
`impact()` table + de-duplicated KG retrievals for every requirement, seed-term group and a few
step-specific queries, capped by `change_kg_budget` tokens + every artifact already drafted →
agent plan → engine post-processing → `change/render.py`) → `revise` (a chat instruction; the
agent edits the markdown, the result must still parse) → `edit` (human markdown, a
`human_edit` version) → `approve` (cursor advances; approving the last step completes the CR).
"Draft now" is allowed at any time after start — pending questions are marked skipped. Later
steps cannot be drafted before the previous one is approved; earlier steps can be re-drafted
(new version, needs re-approval). Long TDD answers are drafted in four chunks of sections and
stories in batches of three, because a single long Nemotron JSON answer is unreliable.

**Artifacts (`models/change.py`, `change/render.py`, `change/parse.py`).** Each artifact keeps a
full history (`llm_draft` | `llm_revision` | `human_edit`) and renders to markdown whose heading
structure mirrors the manager's reference documents: the impact analysis is numbered like a BCR
(Change Summary, Requirements Assessment, Affected Components table, Impact on Existing Design,
Risks & Assumptions, Open Decisions, a deterministic knowledge-graph appendix); the EPIC has the
unnumbered `Epic Statement / Business Value / In-Scope Capabilities / Definition of Done / Story
Map / Non-Functional Requirements / Dependencies / Risks` sections; user stories are one
`## US-00N: Title` section each with `### Story` (As/I want/so that), `### Acceptance Criteria`
(checkable Given… lines) and `### Notes`; the TDD keeps TDD-ORD-001's `## N. Title` /
`### 4.x Title` sections with an **Existing** and a **Proposed** part each. Every artifact ends
with a `## Sources` footer (KB files + line spans the brief was grounded on) and carries a
retrieval-coverage note when coverage is low. `parse.py` reads all four back (round-trip tests);
a human edit or revision that loses the title heading is rejected with 400.

**Façade + storage.** `change/service.py::ChangeRequestService(store, kg_service,
provider_factory)` mirrors `ProjectCompiler` (load → engine → save on every call, so a cancelled
job leaves the previous state); `storage/change_store.py` persists
`<state-root>/change_requests/<cr_id>.json` with the same id validation as the KB store.
Questions, drafts and revisions run as `cr_questions` / `cr_draft` / `cr_revise` jobs
(`JobManager` scope kind `change_request`); `answer` is one short synchronous call. Approving a
step kicks the next step's `cr_questions` job automatically. Provider/model are chosen per
change request (cloud Nemotron by default) and stored on its wizard.

**Config.** `change_kg_budget` (9000 tokens of KG excerpts per brief). CLI: `cr create|list|show|
draft [--auto]|approve|export|delete`; UI: **Changes** page (list + new) and the wizard page
(stepper + chat on the left, artifact editor with versions / approve / Sources / Export on the
right). Word/Excel export: §8e.

## 8e. Document export (`docs_export/`) — Word / Excel in the reference template style

Markdown stays the source of truth; `docs_export/` projects the **parsed** artifacts
(`change/parse.py` → `ImpactDoc` / `EpicDoc` / `StoriesDoc` / `TddDoc`) into files that look like
the manager's reference documents. It is 100 % deterministic — no model call, and identical
input yields identical bytes (`docs_export/package.py` pins the OOXML timestamps), so exports can
be cached, diffed and asserted in tests.

| Module | Role |
|---|---|
| `docx_writer.py` | `DocxWriter` over python-docx: 22 pt bold `2F5496` title, 14 pt subtitle, thin rules around a bold `Label: value` block, Word *Heading 1/2/3*, *List Paragraph* `•` bullets and real `1.` numbering, tables with a `2F5496` header row (white bold, `tblHeader`) and `FFFFFF` body cells, `☑  `/`☐  ` checklists, Consolas `AA3377` inline code, boxed code blocks, a left-barred callout. Body font Times New Roman 10 pt (what Word renders for the reference files, whose styles carry no font defaults). |
| `markdown_to_docx.py` | Converter for our artifact grammar (headings, paragraphs, bullets, `1.` lists, `- [ ]`/`- [x]`, pipe tables with `<br>`/`\|`, code fences, `> notes`, `**Label:** value`, inline `` `code` ``/`**bold**`/`*italic*`); used for free-text bodies and as a whole-document fallback. |
| `xlsx_writer.py` | Test-case matrix: sheet **Test Cases** (`TC ID | Title | Preconditions | Steps | Expected Result | Type | Automated | Linked Story/Req | Notes`, Arial 10, `2F5496` header, frozen + autofilter) and **Summary** (title, Linked TDD/Epic/Automation, *Totals by Automation Status*, *Totals by Type* in the reference vocabulary order, Notes — totals are literal numbers). `read_test_case_rows` reads a matrix back. |
| `artifacts.py` | Per-kind layouts: **Impact** (title "Impact Analysis", `BCR-001 — title` subtitle, numbered H1s, KG appendix + Sources annexes), **EPIC** (title `EPIC-002`, unnumbered H1s, callout statement, ☑/☐ DoD, tables), **User story** (one file per story: `US-00N: Title`, meta, Heading 2 only — Story with bold subject / Acceptance Criteria ☐ / Notes), **TDD** ("Technical Design Document (TDD)", `N. Title` H1s, `4.x` H2s, *Existing* / *Proposed* as Heading 3), **TC preview** (the impact analysis' affected test cases; when the knowledge base holds the original matrix its Title/Preconditions/Steps/Expected/Type/Automated are merged in and the change note appended — otherwise the Title carries the impact rationale). `export_artifact(cr, kind, "docx"|"md"|"xlsx")`. |
| `bundle.py` | `export_change_request(cr) -> zip`: `Impact-Analysis-BCR-001.docx`, `EPIC-002-<slug>.docx`, one `US-00N-<slug>.docx` per story, `TDD-ORD-002-<slug>.docx`, `TC-preview-BCR-001.xlsx`, `markdown/*.md` sources, `MANIFEST.txt`. |

**Approval labelling.** Every export carries an `Export:` metadata line — `Approved vN (date)` or
`DRAFT vN — not approved` (drafts also say so in the subtitle and get a `-DRAFT` filename suffix);
the bundle skips undrafted artifacts and lists them in the manifest. The stories artifact's
`docx` export is a zip with one document per story, mirroring the reference layout.
`ChangeRequestService.export` / `export_bundle` add the KB lookup for the TC preview
(`KgService.read_bytes`); the CLI is `cr export <cr-id> <step> --format md|docx|xlsx [--out]` and
`cr export <cr-id> --format zip`; the UI shows `.docx` / `.md` (/ `.xlsx`) buttons on the artifact
panel and **Export all (.zip)** in the wizard header.

## 8f. Knowledge-graph-grounded projects + the change spec (`kg/grounding.py`, `spec/change_*.py`)

The "upload the TDD to the workflow GUI" half of the change pipeline. A workflow project compiled
**with a knowledge base** (`kb_id`, optionally the `change_request_id` whose approved TDD the
document is) differs from a plain compile in exactly two ways — and in nothing else when the ids
are absent (`grounder=None` renders every prompt byte-for-byte as before; the 664 pre-Phase-3
tests are untouched):

1. **Grounded prompts.** `kg/grounding.py::KgGrounder(kg_service, kb_id)` retrieves a
   `KgPacket` for the text about to be analysed (`grounding_query` = the document's identifiers —
   the same seed extractor the change request uses — then a slice of prose) and renders it as a
   self-contained block, *"KNOWLEDGE-GRAPH CONTEXT — prefer these real names / paths"*, that the
   `discover_workflows` (segmentation), `discover_workflow`, `extract_facts` and `design_temporal`
   prompts carry as an **optional** `{{ kg_context }}` variable (`optional:` front-matter; the
   renderer defaults it to `""`). `ProjectCompiler.compile_document(..., grounder=)` passes the
   block for the whole document to segmentation and per segment to fact extraction
   (`WorkflowCompiler.extract_facts(kg_context=)` → `WorkflowState.kg_context`); `approve_spec`
   re-grounds each seeded state so the Temporal-design prompt sees the same names. Retrieval is
   cached per text, never raises into the pipeline (a broken graph degrades to an ungrounded
   compile), and the packets' files/spans accumulate into `project.grounding`
   (`ProjectGrounding{kb_name, change_request_title, sources, coverage, low_confidence,
   requirement_ids}`) — the visible provenance behind the UI's *Grounded by ‹KB› · from ‹CR›*.
   The `discover_workflows` prompt also carries a hint that a TDD's state machine / activities
   table define **one** workflow with per-group sub-steps rather than one workflow per design
   section (plan Phase 3 design note).
2. **A change spec.** `agents/change_spec.py::ChangeSpecAgent.extract(tdd_text, kg_context,
   impact_table, seed_components, requirement_ids)` (prompt `extract_change_spec.md`) returns a
   `models/change_spec.py::ChangeSpec{components: [ComponentChange{name, kind: module|activity|
   workflow|type|signal|query|test|diagram|doc, path (KG node id / file), existing, proposed,
   change_type: modify|add|remove|verify, requirement_ids, provenance}], assumptions,
   open_questions, sources, version}`. When a change request is linked, `change/spec_seed.py`
   seeds the components from its approved impact analysis (`AffectedItem` rows + the TDD's
   Existing/Proposed section texts) and the request's requirement ids are the only ones the model
   may cite; the deterministic `KgService.impact` table over the document's identifiers goes into
   the prompt too. Cleaning is deterministic (kind/change-type coercion, de-duplication, provenance
   = `document_grounded` when the name occurs in the document, seeds kept when the model returns
   nothing). The spec is stored on `CompilationProject.change_spec` (+ `kb_id`,
   `change_request_id`) and rendered to **`changes.md`** by `spec/change_renderer.py`
   (`# Change Spec` → `## Grounding` (read-only) → `## Components` with one
   `### name — kind, change [marker]` block, `- path:` / `- requirements:` bullets and
   `#### Existing` / `#### Proposed` free text → `## Assumptions` → `## Open Questions` →
   `## Sources` (read-only)); `spec/change_ingest.py` folds edits back (match by `kind:name`,
   changed text → `human_provided`, new heading → new human component, missing heading → removed;
   `render → ingest(None) → render` is identity and every field, provenance included, round-trips).
   `spec/change_validator.py` runs no model: **empty Proposed → BLOCKING**, a `path` that
   `KgService.resolve_ref` cannot find (node id, file path or suffix, `fn:` symbol) → WARNING with
   `KgService.search` suggestions, a requirement id the change request does not declare → WARNING.
   Findings land in `validation_findings["__changes__"]` (`CHANGES_SLUG`, never a workflow slug).

**Same gate.** `changes.md` travels through every existing door: `ProjectCompiler.spec_markdown`
lists it with the workflow files (`ProjectResponse.spec_markdown`, the CLI's spec dir,
`write_spec_files` / `read_spec_files`); `PUT /projects/{id}/spec` and `validate` fold it in
(`markdown_by_slug["__changes__"]`); `approve_spec` re-validates it and **refuses on a BLOCKING
change finding unless `accept_incomplete`** (WARNINGs never block); the Resolve dialogue drafts
questions from its findings and open questions (`draft_change_questions.md`), and a prose answer
becomes deterministic `ComponentUpdate`s (`interpret_change_answer.md` → `dialogue/change_ops.py`:
modify carries only changed fields, add/remove, resolve open questions, one version bump; unmapped
answers park as a human-provided open question, one follow-up at most). `agenda_fingerprint` /
`has_anything_to_ask` include the change spec, so pre-drafting stays correct.

**Ingress.** `POST /projects/compile` and `/projects/compile-upload` take `kb_id?` /
`change_request_id?` (a request implies its KB; a mismatching explicit KB is 422; an unindexed KB
409); `POST /change-requests/{id}/send-to-workflow {provider?, model?, nickname?}` compiles the
**approved** TDD markdown (409 otherwise) with both ids, defaults the provider to the wizard's
(else cloud Nemotron), links the new project into `cr.project_ids`, and runs synchronously like
`/projects/compile`. CLI: `compile … --kb <id> [--change-request <id>]` writes `changes.md` into
the spec dir. UI: the home page's *Ground with knowledge base* selector, the wizard's **Send to
workflow GUI** button (approved TDD only), and in the Spec tab `changes.md` as a second file with
its own grammar highlighting, a change-spec summary in the right rail, findings under its entry
and the *Grounded by …* header (grammar: `frontend/SPEC_GUIDE.md`, guide page → *changes.md*).

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
    for f in final.temporal_code.files:        # the runnable Temporal Python bundle
        print(f.path)

asyncio.run(main())
```

### 9.2 CLI (`cli/main.py`, Typer + Rich)

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

Each command builds a provider (or `--provider mock`), constructs a compiler with the file store,
runs the async work (passing a live progress sink), closes the provider, and prints Rich tables
(metadata, facts-by-category, review issues, CVPA assignments, Temporal components, generated code
files). `--out` writes the Mermaid diagram; `--out-dir` writes the `TemporalCodeBundle` as one file
per `GeneratedFile` under `<out-dir>/<slug>/`. `reject`/`show` build a compiler with **no
LLM** because they don't need one. The compiling commands stream a timestamped step log via the
progress callback.

`compile`, `validate`, `approve-spec`, and `approve` use the LLM (set the local gateway or
`NVIDIA_API_KEY`, or pass `--provider mock` — the mock answers every stage with a scripted demo
workflow, so every command runs offline); `reject` and `show` need no LLM. `models` lists the
models the local eGPU gateway exposes (`workflow-compiler models`). `--version` prints the
version, and `workflow-compiler <command> --help` is always the authoritative reference.

For the local gateway, `--model ID` selects the **local** model (discover ids with
`workflow-compiler models`); `--provider nemotron` bypasses the eGPU and uses the hosted API.

#### `init` — write the `.env` configuration (one-time, no LLM)

The configuration half of the install (§5). Asks which provider to use and for the credentials
that provider needs, then writes `.env`. Builds no provider and makes no network call — it never
checks the credentials against a live endpoint, it writes the file and names anything still
missing.

| Flag | Default | Description |
|---|---|---|
| `--provider NAME` | asked for | `nemotron` \| `local` \| `local-fallback` \| `mock`. |
| `--nvidia-api-key KEY` | asked for | Only read for `nemotron` / `local-fallback`. |
| `--env-file PATH` | `.env` | Where to write. Parent directories are created. |
| `--force` | off | Replace an existing file. Without it, an existing file is an error (exit 1). |
| `--yes` / `-y` | off | Ask nothing; use the flags given plus defaults (provider `mock`). |

Credentials the chosen provider does not need are written as commented placeholders, so switching
provider later is an uncomment rather than a trip back to `.env.example`. Rendering is
`cli/init_env.py::render_env`, a pure function of its arguments — tested without a terminal in
`tests/test_cli_init.py`.

#### `compile <document>` — segment into editable specs, stop at the spec gate

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
| `--kb ID` | — | Ground the compile with a knowledge base (KG context in every prompt) and write `changes.md` next to the spec files (§8f). |
| `--change-request ID` | — | The change request whose approved TDD this document is: seeds `changes.md`, restricts its requirement ids, links the project into `cr.project_ids`; implies `--kb`. |

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

#### `validate <project-id>` — fold edits back in and re-check the specs

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

#### `edit <project-id> <edit-file>` — change compiled workflows with an edit request

```bash
workflow-compiler edit <project-id> examples/order_edit_request.md --spec-dir ./specs --author alice
```

Applies a **workflow edit-request document** (format: [`EDIT_FORMAT_GUIDE.md`](EDIT_FORMAT_GUIDE.md))
to a compiled project: structured sections (`## Workflow: <slug>` with `### Add` / `### Modify` /
`### Remove`, plus `### Triggers` / `### Dependencies`, `## Add Workflow:` and
`## Remove Workflow:`) hold natural-language entries that an LLM translates into deterministic
patches against the current specs. Your changes carry **human authority** — additions need no
support in the original document (they are marked `[human]`) and removals are honored. The edit
is **atomic**: an entry that cannot be translated or applied aborts the whole request with the
offending entries listed, and nothing changes. (An addition whose value is already in the spec is
treated as satisfied and skipped with a `skipped (already present)` summary line rather than
aborting.)

On success the edited workflows' versions are bumped, an `EditRecord` is appended to the
project's audit log, the spec files are re-written, and the project returns to the spec gate —
run `validate` then `approve-spec` to regenerate graphs, designs, and code.

`--dry-run` previews the edit — full parse + interpretation + per-workflow summary — without
applying or writing anything; re-run without the flag to apply. (The web UI goes further: its
preview hands the interpreted operations back on confirm, so the apply replays exactly what was
previewed with no second LLM call.)

| Flag | Default | Description |
|---|---|---|
| `--workflow SLUG` | all | Only allow edits touching these workflow slug(s) (repeatable). |
| `--author NAME` | — | Author recorded in the edit log. |
| `--spec-dir DIR` | `./specs` | Where the updated spec files are re-written. |
| `--dry-run` | off | Preview the edit (nothing is applied or saved). |
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | Same LLM overrides as `compile`. |

#### `approve-spec <project-id>` — compile every workflow through to code

```bash
workflow-compiler approve-spec <project-id> --spec-dir ./specs
```

Approves the specs and runs each workflow **independently** through graph building, structural
review, CVPA, Temporal design, and code generation. The graph gate is automatic: health ≥ the
configured threshold continues; below it the workflow is left pending (`approve <workflow-id>`
remains the manual override). Unanswered required questions block a workflow unless you pass
`--accept-incomplete`; unconfirmed dependencies block approval unless you pass
`--allow-unconfirmed`. Each completed workflow's runnable Temporal bundle is written under
`<out-dir>/<project-id>/<slug>/` — `--out-dir` defaults to `./generated`, so repeated runs
never litter the working directory with loose bundle folders.

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

#### `approve <workflow_id>` — manual override for a below-threshold graph

When a workflow's graph health lands below the auto-approve threshold at `approve-spec`, it is
left pending. Inspect it (`show`), then approve it manually to produce CVPA + Temporal design +
code:

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | Reviewer identity recorded on the approval. |
| `--provider NAME` / `--model ID` / `--timeout SECONDS` | from `.env` / `120` | Same LLM overrides as `compile`. |
| `--out PATH` | — | Write the CVPA-colored Mermaid diagram to a file. |
| `--out-dir DIR` | `./generated` | Root for generated output; the bundle lands in `<out-dir>/<workflow-id>/`. |

```bash
workflow-compiler approve <workflow_id> --reviewer alice --out workflow.mmd
```

#### `reject <workflow_id>` — halt a pending workflow (no LLM)

| Flag | Default | Description |
|---|---|---|
| `--reviewer NAME` | — | Reviewer identity. |
| `--reason TEXT` | — | Why the graph was rejected (recorded in the report). |

#### `show <workflow_id>` — display a stored workflow (no LLM, no flags)

#### Windows console note

The progress/table output contains Unicode (e.g. `→`). On a legacy `cp1252` console this raises
`UnicodeEncodeError`. Run with UTF-8 mode: `set PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8=1`).
This is a console-rendering issue only — it does not affect the generated code. Nemotron's
reasoning models can also be slow; bump `--timeout` (e.g. `300.0`) to avoid
`ProviderTimeoutError` on a slow request.

**`kb …` — knowledge bases** (`cli/kb.py`; same file store as the API, no login):

| Command | Purpose |
|---|---|
| `kb init <zip-or-folder> [--name] [--enrich/--no-enrich] [--provider] [--model] [--id]` | Create + index (progress printed per file). |
| `cr create <kb-id> <bcr.docx|.md|.txt> [--title] [--provider] [--model]` | Register a change request against a knowledge base (metadata, requirements and impact seeds parsed deterministically). |
| `cr list` / `cr show <cr-id>` | Change requests and their wizard/artifact state. |
| `cr draft <cr-id> <impact|epic|stories|tdd> [--auto] [--out FILE]` | Draft one wizard step; `--auto` starts the wizard, drafts the questions, answers each with its first suggested option, then drafts. |
| `cr approve <cr-id> <step>` / `cr delete <cr-id>` | Approve (advances the wizard), delete. |
| `cr export <cr-id> <step> [--format md\|docx\|xlsx] [--version N] [--out PATH]` / `cr export <cr-id> --format zip [--out PATH]` | Print/save an artifact — markdown (any version), Word (stories → zip of per-story docs), the affected-test-cases workbook (impact only) — or the whole change request as a zip. Deterministic; unapproved artifacts are labelled DRAFT. |
| `kb list` / `kb show <kb-id>` | List; stats by type, catalog ids, warnings. |
| `kb ask <kb-id> "<prompt>" [--budget] [--hops] [--json]` | Print the retrieved packet + sources with line spans. |
| `kb impact <kb-id> <seed>… [--hops]` | Deterministic impact table. |
| `kb search <kb-id> "<query>"` / `kb delete <kb-id>` | Anchor candidates; remove. |

### 9.3 HTTP API (`api/app.py`, FastAPI)

Run it with `python -m uvicorn workflow_compiler.api.app:app --reload` from the virtual environment
the package is installed in (a bare `uvicorn` resolves through `PATH` and may belong to a different
environment, which surfaces as `ModuleNotFoundError: No module named 'workflow_compiler'`);
interactive docs live at `/docs`.

**Authentication.** The HTTP surface uses local accounts: register/sign in once and a signed
HttpOnly session cookie rides every call. Projects created via the API carry an `owner_id`
(recorded for attribution). By default every signed-in user can see and open every project;
set `WORKFLOW_COMPILER_PROJECTS_SHARED=false` to restore per-owner isolation, where you see
only your own projects (plus unowned legacy/CLI ones) and other accounts' projects answer 404.
`author`/`reviewer` fields default to the signed-in user's display name. Accounts live as JSON
under the state store (scrypt-hashed passwords, no external services); the CLI talks to the
compiler directly and needs no login. This protects the HTTP surface only — anyone with
filesystem access to the state store can read it.

| Method | Path             | Body                                  | Purpose                                  |
|--------|------------------|---------------------------------------|------------------------------------------|
| POST   | `/auth/register` | `{email, password, display_name?}`    | Create a local account (signs you in).   |
| POST   | `/auth/login`    | `{email, password}`                   | Sign in (sets the session cookie).       |
| POST   | `/auth/logout`   | —                                     | Sign out.                                |
| GET    | `/auth/me`       | —                                     | The signed-in user + preferences (401 when signed out).|
| PUT    | `/auth/me`       | `{display_name?, preferences?}`       | Update display name and/or preferences (page size, per-user baseline overrides). Omitted fields unchanged. |
| GET    | `/settings/defaults` | —                                 | Org-wide baseline-hour defaults (so the Settings UI can show defaults + reset). |

Project endpoints (the compile → validate → approve pipeline; spec files travel as
`spec_markdown: {slug: markdown}`):

| Method | Path                        | Body                                        | Purpose                                        |
|--------|-----------------------------|---------------------------------------------|------------------------------------------------|
| POST   | `/projects/compile`         | `{document_text, persist?, provider?, model?, nickname?, kb_id?, change_request_id?}` | Segment into per-workflow specs (spec gate). `model` picks a local gateway model; `nickname` sets an optional label; `kb_id` grounds every prompt in a knowledge base and adds `changes.md`; `change_request_id` seeds it from the request (implies its KB). |
| POST   | `/projects/compile-upload`  | multipart `file` + the same form fields          | Parse a `.docx/.pdf/.md/.html/.txt` upload to text, then as `/projects/compile`. |
| GET    | `/projects`                 | —                                           | List visible projects as summaries (`{projects: [{project_id, nickname, stage, workflow_count, updated_at}]}`, newest first). |
| GET    | `/projects/{id}`            | —                                           | Load a project + rendered spec files.           |
| PATCH  | `/projects/{id}`            | `{nickname}`                                | Set or clear the project nickname (metadata only — no recompile). Returns the summary. |
| PUT    | `/projects/{id}/spec`       | `{spec_markdown}`                           | Fold edited spec Markdown back in (no LLM); `spec_markdown["__changes__"]` is `changes.md`. |
| POST   | `/projects/{id}/edit`       | `{edit_document, workflows?, author?, resolved?}` | Apply an edit-request document; re-arms the gate. Pass `resolved` from a preview to replay it with no LLM call (stale preview → 409). |
| POST   | `/projects/{id}/edit/preview` | `{edit_document, workflows?}`             | Dry-run the edit: would-be summary, post-edit spec Markdown, and the `resolved` handoff blob. Persists nothing. |
| POST   | `/projects/{id}/validate`   | `{spec_markdown?}`                          | Ingest edits + run the spec validator passes (synchronous). |
| POST   | `/projects/{id}/approve`    | `{workflows?, reviewer?, spec_markdown?, accept_incomplete?, allow_unconfirmed_references?}` | Approve specs, compile every workflow (synchronous). |

**Conversational spec resolution.** The alternative to hand-editing spec Markdown: the
validator's **blocking and warning** findings (never INFO) plus each spec's unresolved open
questions become plain-language questions, and answers are prose. Related findings may be
**grouped** into one question; a vague answer earns exactly **one** clarifying follow-up. Each
answer is applied **immediately** — one patch set and one patch-version bump per answered
question — through the same human-authority applier the edit path uses, so additions need no
document grounding and are marked `human_provided`. An answer that cannot be mapped to a spec
change is **parked** as a new open question rather than discarded (the edit path aborts; this
one never does). The agenda is a snapshot taken at start, so a session always terminates.
Applied answers return the project to `spec_drafted`, and closing the session drops the
findings for changed specs — validation must run again before approval.

| Method | Path                          | Body        | Purpose                                    |
|--------|-------------------------------|-------------|--------------------------------------------|
| GET    | `/projects/{id}/dialogue`     | —           | The open session (or `session: null`).      |
| POST   | `/projects/{id}/dialogue`     | —           | Open a session. 400 when there is nothing to resolve. Replaces any existing session. |
| POST   | `/projects/{id}/dialogue/answer` | `{answer}` | Answer the current question in prose. Applies patches, or asks a follow-up, or parks. |
| POST   | `/projects/{id}/dialogue/skip` | —          | Pass on the current question; the spec is untouched. |
| DELETE | `/projects/{id}/dialogue`     | —           | Close the session. Answers already applied stay applied. |

Every response carries `prompt` — the exact text to show the user, which is the pending
clarifying follow-up when one is open and the question otherwise — plus `changes` /
`parked_as` describing what the last answer did, and the refreshed `spec_markdown`.
| GET    | `/metrics/summary`          | —                                           | Total time saved across your projects (measured pipeline seconds vs. the configurable `baseline_hours` human-team estimates). |

Validate and approve can also run as **cancelable background runs** that keep going after
the user navigates away (the web UI uses these). A run is an in-process task; **cancelling
never persists a partial result**, so the project is left exactly as it was. At most one run
per project may be in flight (a second start answers `409`), but any number of *different*
projects may run at once. Runs live in memory — a server restart drops them (nothing was
persisted, so the project simply stays in its pre-run state).

| Method | Path                        | Body / Params                               | Purpose                                          |
|--------|-----------------------------|---------------------------------------------|--------------------------------------------------|
| POST   | `/projects/{id}/jobs`       | `{kind: "validate"\|"approve", spec_markdown?, …approve knobs}` | Start a background run; returns `202` + the run descriptor immediately. |
| GET    | `/jobs`                     | `?project_id=` (optional)                   | List the caller's runs, newest first (all users' when `projects_shared`). |
| GET    | `/jobs/{job_id}`            | —                                           | One run's status; the finished project is embedded when `status == "succeeded"`. |
| POST   | `/jobs/{job_id}/cancel`     | —                                           | Cancel a run, leaving the project untouched (no-op once terminal). |

`GET /jobs` also accepts `?scope_id=` (alias of `project_id`) and `?scope_kind=project|knowledge_base`;
every job carries `scope_id`, `scope_kind` and, for long runs, `progress {message, done, total}`.

Knowledge bases (§8c). Uploading a corpus answers `202` with the knowledge base **and** its
`kb_ingest` job; poll the job or the KB until `status == "ready"`. Same visibility rule as projects.

| Method | Path                                   | Body / Params                                              | Purpose |
|--------|----------------------------------------|------------------------------------------------------------|---------|
| POST   | `/knowledge-bases`                     | multipart `file` (zip), `name?`, `enrich?`, `provider?`, `model?` | Extract the corpus (400 on a bad/unsafe zip) and start indexing. |
| GET    | `/knowledge-bases`                     | —                                                          | List knowledge bases (stats, catalog, status). |
| GET    | `/knowledge-bases/{id}`                | —                                                          | One knowledge base (+ the running job, if any). |
| DELETE | `/knowledge-bases/{id}`                | —                                                          | Remove record, corpus and graph (cancels a running ingest). |
| POST   | `/knowledge-bases/{id}/reindex`        | `{enrich?, provider?, model?}`                             | Rebuild the graph as a job (enrichment cache reused). |
| POST   | `/knowledge-bases/{id}/retrieve`       | `{prompt, budget?, max_hops?}`                             | Grounded context packet (`rendered`, `sections`, `files`, `coverage`). |
| GET    | `/knowledge-bases/{id}/impact`         | `?seed=…` (repeatable) `&max_hops=`                        | Deterministic impact table. |
| GET    | `/knowledge-bases/{id}/search`         | `?q=…&k=`                                                  | BM25 anchor candidates. |
| GET    | `/knowledge-bases/{id}/files`          | `?path=` (optional)                                        | Corpus file list, or one file as text. |
| GET    | `/knowledge-bases/{id}/graph/summary`  | `?top=`                                                    | Counts by node/edge type + best-connected nodes. |
| POST   | `/change-requests`                     | multipart `kb_id`, `file` (docx/md/txt) or `text`, `title?`, `provider?`, `model?` | Register a change request (201; no LLM call). |
| GET    | `/change-requests`                     | —                                                          | List change requests (summary rows). |
| GET    | `/change-requests/{id}` (`/wizard`)    | —                                                          | The change request: wizard steps/questions/turns, artifacts, ids, running job. |
| DELETE | `/change-requests/{id}`                | —                                                          | Delete (cancels a running job). |
| POST   | `/change-requests/{id}/wizard/start`   | `{provider?, model?}`                                      | Reserve ids + impact traversal (sync), then draft the current step's questions as a `cr_questions` job (202; idempotent). |
| POST   | `/change-requests/{id}/wizard/answer`  | `{answer, option?}`                                        | Answer the current question (one short LLM call; may return one follow-up). |
| POST   | `/change-requests/{id}/wizard/skip`    | —                                                          | Skip the current question. |
| POST   | `/change-requests/{id}/wizard/draft`   | `{step?}`                                                  | Draft the step's artifact as a `cr_draft` job (202; pending questions are skipped). |
| POST   | `/change-requests/{id}/wizard/revise`  | `{step, message}`                                          | Chat revision of a drafted artifact as a `cr_revise` job (202). |
| GET    | `/change-requests/{id}/artifacts/{kind}` | `?version=`                                              | Artifact markdown (latest or a version) + history + sources + coverage. |
| PUT    | `/change-requests/{id}/artifacts/{kind}` | `{markdown, note?}`                                      | Human edit → new `human_edit` version (400 if the structure is lost). |
| POST   | `/change-requests/{id}/artifacts/{kind}/approve` | —                                                | Approve; the cursor advances and the next step's questions job starts. |
| GET    | `/change-requests/{id}/artifacts/{kind}/export` | `?format=docx\|md\|xlsx`                          | Download the artifact as Word (stories: zip of per-story docs) / markdown / TC preview workbook (impact only). Deterministic; `Content-Disposition` names the file; DRAFT-labelled until approved. |
| GET    | `/change-requests/{id}/export.zip`     | —                                                          | Every artifact as Word/Excel + `markdown/*.md` + `MANIFEST.txt`. |
| POST   | `/change-requests/{id}/send-to-workflow` | `{provider?, model?, nickname?}`                       | Compile the **approved** TDD into a KB-grounded workflow project (`kb_id` + `change_request_id` set, `changes.md` seeded), append it to `project_ids`, return the `ProjectResponse` (201; 409 while the TDD is unapproved). Synchronous; provider defaults to the wizard's, else cloud Nemotron. |

Project responses include `time_saved`: each pipeline step's measured wall-clock seconds
(persisted per project as `stage_timings`) compared against configurable human-team estimates
(`WORKFLOW_COMPILER_BASELINE_HOURS`, a JSON object of hours per step category). The baselines
are **estimates, not measurements** — tune them to your organization. Each signed-in user can
also override the baselines for their own view from the **Settings** page (`PUT /auth/me`
`preferences.baseline_hours`); their overrides take precedence over the org-wide config default,
and `time_saved`/`/metrics/summary` recompute live with the caller's values.

Per-workflow endpoints (viewing plus the manual override for below-threshold graphs):

| Method | Path                | Body / Params                              | Purpose                                   |
|--------|---------------------|--------------------------------------------|-------------------------------------------|
| POST   | `/approve`          | `{workflow_id, reviewer?}`                 | Approve → run CVPA + Temporal.            |
| POST   | `/reject`           | `{workflow_id, reviewer?, reason?}`        | Reject a graph.                           |
| GET    | `/workflow/{id}`    | —                                          | Load a stored workflow state.             |
| GET    | `/workflows`        | —                                          | List stored workflow ids.                 |
| GET    | `/providers/local/models` | —                                    | List models the local eGPU gateway exposes (for the picker). |
| GET    | `/health`           | —                                          | Liveness probe.                           |

The compiler is provided once via `get_compiler` (a cached `from_settings()`), and tests override it
with a mock-backed compiler. A small `_guard` helper maps domain exceptions to HTTP codes:
`StateNotFoundError → 404`, `ApprovalError → 409`, `CompilationError → 400`.

Example:

```bash
curl -s localhost:8000/projects/compile \
  -H 'content-type: application/json' \
  -d '{"document_text": "When a customer submits an order, validate payment, then ship it."}'
```

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
   - **Temporal design** → workflow `OrderFulfillment`, activities (ValidatePayment, ProcessOrder,
     ShipOrder…), a `cancel` signal, a `ReleaseInventory` compensation that `compensates`
     ProcessOrder, a default retry policy, and a plan IR ordering the activity calls with
     `ValidatePayment`'s result bound into `ProcessOrder`'s input.
   - **Temporal code (deterministic)** → a `temporal-order-fulfillment` package: `shared.py`,
     `activities.py` (stubs), `workflow.py` (the run body awaits each activity in plan order,
     registers `ReleaseInventory` for saga rollback, fires it in reverse on failure), `worker.py`,
     `starter.py`, `README.md`. With `--out-dir gen` these are written under
     `gen/temporal_order_fulfillment/`.
   - `stage = CODE_GENERATED → COMPLETED`, saved.

If instead you **reject**, `approval_status = REJECTED`, the reason is recorded, and
CVPA/Temporal/code generation never run.

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
  integrity guard (dangling ids dropped, entity-id transition leaks dropped) and the semantic wiring
  (relations attach to the right nodes, parallel groups become gateways, uncompensated exceptions
  terminate).
- **Temporal codegen tests** (`tests/test_temporal_codegen.py`) assert the generator renders the
  expected six-file bundle, threads step outputs into later inputs, emits saga compensation, and only
  imports `asyncio` when a parallel step exists.
- **Temporal IR runtime test** (`tests/test_temporal_ir_runtime.py`) materializes a generated bundle
  to disk and **runs it under a Temporal `WorkflowEnvironment`** (time-skipping, flat imports) to
  prove the emitted code is actually executable — the ultimate guard against codegen hallucination.
- **Review-pipeline tests** (`tests/test_review_pipeline.py`) exercise the deterministic patch
  appliers (grounded `add`, duplicate/ungrounded drops, `merge` repointing references, dangling
  relations nulled by `validated()`), the end-to-end `ReviewPipelineAgent` (generate + three passes,
  and idempotent settle to `no_change`), and the compiler's **review → plain** precedence.
- No network is required for the suite. Run `pytest` and `ruff check src tests`.

Because the LLM is hidden behind `BaseLLMProvider`, the `MockProvider` returns *queued* structured
responses in order — e.g. `[discovery, facts, cvpa, temporal]` — letting tests drive the exact path
deterministically. Note that with the **review pipeline on (the default)** each reviewed stage also
consumes three `ReviewResult` responses, so the exact-queue end-to-end suites (integration, API,
compiler) construct the compiler with `review=ReviewConfig(enabled=False)`; review behavior is
covered separately in `tests/test_review_pipeline.py`.

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
- **The LLM emits a design, never code; a deterministic generator emits the code.** The Temporal
  *design* stage (Stage 6) is specification-only — a test asserts the design models have no
  `code`/`body`/`implementation` field. The runnable Temporal Python is produced separately by the
  no-LLM generator (Stage 7), so the generated code is a reproducible function of a reviewed design,
  not a model hallucination.
- **Generated code uses flat, absolute imports and is run directly** (`python worker.py` from inside
  the package), matching the Temporal Python docs — *not* `from .x import` relative imports or
  `python -m package.worker`, both of which were earlier hallucinations that did not run. See
  `TEMPORAL_CODEGEN_FINDINGS.md`.
- **The risky part of codegen is emitted in Python, not Jinja.** The `@workflow.run` body (data
  threading, saga rollback, `asyncio.gather`, branches) lives in `generator.py` where it is
  unit-tested and even run under a real `WorkflowEnvironment`; templates only carry boilerplate.
- **The API key** is held as a `SecretStr`, sent only as a bearer header, and never logged or
  printed.
- **Reasoning-model latency:** Nemotron's "detailed thinking off" preamble and generous timeouts
  keep structured calls fast and parseable.
- **The gate is durable:** because state is persisted, `compile`, `validate`, and `approve-spec`
  can be separate commands, requests, or processes — minutes or days apart.
- **The review passes never certify truth.** They filter with *reference-free* signals (evidence
  quotes, referential integrity, grounding) — raising grounding/consistency but unable to detect a
  misreading the generator and all three reviewers share, which is why the human spec gate stays
  the oracle and flagged elements are surfaced, not trusted. See §7.10.

---

> Want the 30-second version? **A document goes in; agents (LLM for understanding, pure functions
> for structure) progressively fill one `WorkflowState`; a human approves the reviewed graph; then
> CVPA labels every node, a Temporal design (with a typed plan IR) is produced, and that design is
> deterministically rendered into runnable Temporal Python code — all swappable behind clean
> interfaces, all persisted, all observable via progress events, all tested (the generated code is
> even executed under a Temporal test environment) without a network.**
