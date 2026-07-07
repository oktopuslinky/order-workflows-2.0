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
- **Ensemble / consensus merge** — an *opt-in* mode that runs an LLM stage (discovery and/or fact
  extraction) **N times** at different temperatures and **combines the candidates' parts** rather
  than picking one. Cross-sample agreement is a hallucination filter — a real part shows up in most
  candidates, a fabrication usually in one. Off by default.
- **Sequential review pipeline** — the *default* quality lever on the discovery and fact-extraction
  stages: generate **one** canonical output, then improve it with **three sequential review passes**
  (completeness → grounding → consistency) that emit **minimal patches or `no_change`**, never a
  rewrite. Idempotent by construction. On by default; superseded by the ensemble on any stage where
  the ensemble is enabled. See [§7.11](#711-the-sequential-review-pipeline-default-on).
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
INGESTED → METADATA_EXTRACTED → FACTS_EXTRACTED → [CHECKLISTED] → GRAPH_BUILT → REVIEWED
         → CLASSIFIED → TEMPORAL_DESIGNED → CODE_GENERATED → COMPLETED   (FAILED on error)
```

(The enum also declares a `DIAGRAMMED` value reserved for a future diagram-export stage; the current
pipeline advances `CODE_GENERATED → COMPLETED` directly.)

**The readiness checklist gate** (`CHECKLISTED`) sits between fact extraction and graph building.
After facts are extracted, a deterministic `ChecklistValidator` (`checklist/validator.py`) scores the
document against the requirements that `examples/ideal_temporal_workflow.md` satisfies — a trigger,
named inputs, decisions with both branches, bound compensations, and so on. When `compile` runs with
the gate enforced (CLI default) and a **required** item is unmet, the run halts at `CHECKLISTED`, a
fill-in markdown form is written (`checklist/report.py`), and the user resumes via the `checklist`
command. Their answers are folded back in as **deterministic local amendments** (`checklist/amend.py`)
— no LLM re-run — and the gate re-validates in a loop until satisfied (or `--accept-as-is` overrides).
The checklist is always *computed* and attached to `state.checklist`; enforcement (halting) is opt-in
via `compile_document(enforce_checklist=...)`, so library/test callers keep the straight-through flow.

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
  facts in place (see [§7.11](#711-the-sequential-review-pipeline-default-on)). The opt-in
  **ensemble** ([§7.10](#710-the-consensus-merge-ensemble-opt-in)) supersedes it on any stage it is
  enabled for; precedence is ensemble → review → plain.

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
  - **signal_gate** → `await workflow.wait_condition(lambda: self._<signal>_received)`.
  - **timer** → `await workflow.sleep(<TIMER_CONST>)` using the declared duration.
  - **parallel** → concurrent calls via `asyncio.gather(...)` (the workflow template only imports
    `asyncio` when a parallel step is actually present). Each lane's result is **captured
    positionally** from the gather so a later step can bind to it (no discarded results → no
    `NameError`).
  - **branch** → a real `if/else`. When the design bound the branch to a data dependency it
    branches on that expression (`if bool(<expr>):`); otherwise it emits an explicit placeholder
    flag (`should_<predicate> = False  # TODO`) and branches on it — **never** a silent `if True`
    that would always take one lane.
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

### 7.10 The consensus-merge ensemble (opt-in)

An *opt-in* way to raise accuracy on the LLM stages that matter most. Instead of one sampled
completion, a stage is run **N times** at different temperatures and the candidates are **combined**
— not selected. It is **off by default**; enable it with `--ensemble` / `WORKFLOW_COMPILER_ENSEMBLE_ENABLED`.

- **Where it applies:** `discovery` and `facts` (configurable via `ensemble_stages`). Deterministic
  stages are never ensembled — there's nothing to vary.
- **Diversity:** `TemperatureProvider` (`llm/ensemble_provider.py`) is a pure provider decorator that
  injects a fixed temperature, because agents call `structured(...)` at temperature 0, which would
  otherwise make every candidate identical (and the merge a no-op).
- **Orchestration:** `ConsensusMergeAgent` (`agents/ensemble.py`) wraps an inner agent, runs N
  temperature-diversified copies **concurrently** on independent state deep-copies under a
  per-candidate timeout (300s) and overall budget (480s), then merges the survivors. A slow/failed
  candidate is simply excluded; the run only fails if **every** candidate fails.
- **The merge (`agents/ensemble_merge.py`)** decomposes each candidate into parts (activities,
  decisions, exceptions, compensations, events, transitions; metadata fields/list items) and applies
  **majority backbone + flagged singletons**: a part with ≥2 votes is accepted; a single-vote part is
  kept only if it **grounds** in the document, and is flagged low-confidence; conflicting attributions
  (e.g. an exception's `raised_by`) are resolved by vote count. The merged structure is then run
  through `WorkflowStructure.validated()` so any leftover dangling/leaked reference is dropped.
- **Reference-free signals (no gold answer):** *agreement* (vote count), *referential integrity*
  (`validated()`), and *evidence grounding* — each part's text supported by a span in `document_text`
  via local substring + token-overlap, with embeddings attempted first and **falling back
  gracefully** when the provider (e.g. Nemotron) doesn't implement `embed()`.
- **Provenance:** the merge records what it did (parts accepted, single-vote parts flagged, ungrounded
  singletons dropped, dangling refs removed) in `confidence_scores.notes[<stage>_ensemble]`, so a
  reviewer can see exactly which parts came from only one candidate.
- **The honest boundary:** the merge raises grounding/consistency/soundness — it does **not** certify
  semantic truth (all N candidates can share the same plausible misreading). The human approval gate
  remains the oracle; the flagged singletons are precisely what a reviewer should scrutinize.

Cost note: ensemble multiplies the discovery + facts LLM calls by N (run in parallel), which is why
it is opt-in and default-off.

### 7.11 The sequential review pipeline (default-on)

The **default** way the discovery and fact-extraction stages raise accuracy. Where the ensemble
samples N candidates and merges them, the review pipeline follows a compiler discipline: **generate
one canonical output, then improve it with three specialized review passes.** It never regenerates
the artifact — each pass emits only **minimal patches or `no_change`**.

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
  (extract / serialize / apply-to-state + the three prompt names + the applier), exactly mirroring
  the ensemble's `StageSpec`. `ReviewPipelineAgent` wraps the inner generator agent, runs it once,
  then the three passes, and records per-pass provenance ("completeness: 1 applied, 2 dropped; …")
  in `confidence_scores.notes[<stage>_review]`. Adding a review pipeline for a future stage
  (Mermaid, Temporal) is a new spec + three prompts — no engine change.
- **Prompts:** `prompts/templates/review_{workflow,facts}_{completeness,grounding,consistency}.md`,
  each documenting its pass's responsibility and allowed actions.
- **Precedence and default:** on by default (`--review` / `WORKFLOW_COMPILER_REVIEW_ENABLED`).
  Per stage the compiler chooses **ensemble → review → plain**: the ensemble wins on any stage it is
  enabled for, otherwise the review pipeline runs, otherwise the plain agent.
- **The honest boundary (shared with the ensemble):** the passes raise grounding/consistency but
  cannot certify semantic truth — a misreading the generator and all three reviewers share survives.
  The human approval gate remains the oracle; flagged elements are what a reviewer should scrutinize.

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
    ensemble=...,              # optional EnsembleConfig; when enabled, wraps discovery+facts (§7.10)
    review=...,                # ReviewConfig; default-on sequential review of discovery+facts (§7.11)
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

CLI: `compile <doc> --spec-dir <dir>` → edit the files → `validate <project-id>` →
`approve-spec <project-id> [--out-dir gen]`. HTTP: `POST /projects/compile`,
`GET/PUT /projects/{id}/spec`, `POST /projects/{id}/validate`, `POST /projects/{id}/approve`.

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
workflow-compiler compile examples/order_workflow.md          # → prints a workflow_id, stops at gate
workflow-compiler approve <id> --reviewer alice --out wf.mmd  # → CVPA+Temporal, writes colored diagram
        # … add --out-dir ./generated to also write the runnable Temporal code bundle to disk
workflow-compiler reject  <id> --reason "missing branch"      # → halts (no LLM)
workflow-compiler show    <id>                                # → display a stored state (no LLM)
workflow-compiler compile doc.md --auto-approve --out-dir gen # → whole pipeline + write code in one shot
workflow-compiler compile doc.md --ensemble --ensemble-n 3    # → run discovery+facts 3x, consensus-merge
workflow-compiler compile doc.md --no-review                  # → skip the default review passes (faster/cheaper)
workflow-compiler inspect doc.md --out wf.mmd                 # → preview discover→facts→graph, no save
```

Each command builds a provider (or `--provider mock`), constructs a compiler with the file store,
runs the async work (passing a live progress sink), closes the provider, and prints Rich tables
(metadata, facts-by-category, review issues, CVPA assignments, Temporal components, generated code
files). `--out` writes the Mermaid diagram; `--out-dir` writes the `TemporalCodeBundle` as one file
per `GeneratedFile` under `<out-dir>/<package_name>/`. `reject`/`show` build a compiler with **no
LLM** because they don't need one. `compile`/`approve` stream a timestamped step log via the progress
callback.

### 9.3 HTTP API (`api/app.py`, FastAPI)

| Method | Path | Body | Does |
|---|---|---|---|
| POST | `/compile` | `{document_text, persist?, auto_approve?}` | compile to the gate (or end-to-end) |
| POST | `/approve` | `{workflow_id, reviewer?}` | approve → CVPA + Temporal design + Temporal code |
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
  and idempotent settle to `no_change`), and the compiler's **ensemble → review → plain** precedence.
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
    ensemble_provider.py  TemperatureProvider (decorator forcing a sampling temperature)
    config.py retry.py json_utils.py types.py
    providers/         nemotron.py, openai_compatible.py, mock.py

  prompts/             Markdown prompt templates + manager/loader/renderer
    templates/*.md

  agents/              One class per pipeline stage
    discovery.py fact_extraction.py graph_builder.py review.py cvpa.py temporal.py
    temporal_code.py   TemporalCodeGeneratorAgent (deterministic; wraps codegen/)
    ensemble.py        ConsensusMergeAgent + per-stage specs (opt-in N-candidate merge)
    ensemble_merge.py  reference-free consensus merge (votes + validation + grounding)
    review_pipeline.py ReviewPipelineAgent + ReviewPass/ReviewSpec/PatchApplier (default-on review)
    segmentation.py    WorkflowSegmentationAgent (multi-workflow discovery + document slicing)
    serialization.py   compact graph/CVPA/facts text for prompts

  spec/                Spec projection layer (spec-centric front-end, no LLM except validator)
    renderer.py        deterministic WorkflowSpec → Markdown (the human review surface)
    ingest.py          deterministic Markdown → merged spec (provenance + validated())
    validator.py       SpecValidator + provenance-aware SpecPatchApplier (3 review passes)

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
- **The gate is durable:** because state is persisted, `compile` and `approve` can be separate
  commands, requests, or processes — minutes or days apart.
- **The ensemble needs varied temperatures, and never certifies truth.** Best-of-N/consensus is a
  no-op at temperature 0 (identical candidates), so `TemperatureProvider` injects distinct
  temperatures. The merge filters with *reference-free* signals (agreement, referential integrity,
  grounding) — it raises grounding/consistency but cannot detect a misreading shared by all
  candidates, which is why the human gate stays the oracle and single-vote parts are flagged, not
  trusted. See §7.10.

---

> Want the 30-second version? **A document goes in; agents (LLM for understanding, pure functions
> for structure) progressively fill one `WorkflowState`; a human approves the reviewed graph; then
> CVPA labels every node, a Temporal design (with a typed plan IR) is produced, and that design is
> deterministically rendered into runnable Temporal Python code — all swappable behind clean
> interfaces, all persisted, all observable via progress events, all tested (the generated code is
> even executed under a Temporal test environment) without a network.**
