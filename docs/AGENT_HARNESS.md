# workflow-compiler — Agent Harness

> **Purpose.** Standing context for any agent/prompt working in this repo. Distilled from (a) the
> original build prompts and (b) `docs/HOW_IT_WORKS.md`. Read this first — it should answer most
> questions and support most changes **without sweeping the codebase**. For full prose, see
> `docs/HOW_IT_WORKS.md`. If this file and the code disagree, the code wins — update this file.

---

## 0. What this project is (one paragraph)

`workflow-compiler` turns a **business process described in prose** (`.docx/.pdf/.txt/.md/.html`) into a
chain of structured artifacts: workflow metadata → typed facts → a deterministic graph → a Mermaid
diagram → an automated review → a **human approval gate** → CVPA classification (every node labeled
Capture/Validate/Process/Activate, diagram re-colored) → a Temporal implementation **design** (specs,
never code). One Pydantic object, `WorkflowState`, flows through every stage accumulating fields. LLM is
used only for understanding/classification; graph building and review are pure deterministic functions.

---

## 1. Original design intent (the build prompts)

Built across ~10 prompts. Binding requirements that came directly from the user:

1. **Layered scaffold first** — Pydantic models, abstract interfaces, typed exceptions, config/logging,
   then concrete implementations. Clean interfaces so every layer is swappable.
2. **Ingestion** — multi-format document parsing behind a factory; the rest of the system only sees `text`.
3. **Workflow Discovery agent** (LLM) — extract metadata (name, purpose, actors, systems, triggers,
   start/end states).
4. **Fact Extraction agent** (LLM) — pull atomic statements into 13 typed categories.
5. **Graph Builder** (deterministic, **no LLM**) — facts → nodes/edges + Mermaid.
6. **Review** (deterministic, **no LLM**) — structural QA + health score, sets the approval gate.
7. **CVPAClassifierAgent** — *"Classify every graph node into Capture / Validate / Process / Activate.
   Rules: every node belongs to exactly one category. Provide rationale. Implement confidence scoring."*
   → hence the **structural fallback** guaranteeing 100% coverage and per-node rationale.
8. **Complete WorkflowCompiler** — *"full execution pipeline: Document → Parser → Workflow Discovery →
   Fact Extraction → Graph Builder → Review → Approval → CVPA Classification → Temporal Design."*
9. **Re-color the `.mmd` after CVPA** — *"after the cvpa classification, go back and color code the
   relevant mmd file… group the nodes into c, v, p, or a and color them."* → `to_mermaid_with_cvpa`.
10. **Documentation** — generate a complete, gap-free `docs/HOW_IT_WORKS.md` understandable by someone
    with zero prior knowledge.

Standing user preferences observed during the build:
- **Autonomy:** *"don't ask for any commands; you have full permission to do whatever it takes."* Prefer
  to act and complete the goal end-to-end rather than stopping to ask, when the path is clear.
- Strong bias toward **determinism, typed models, and tests that need no network**.

---

## 2. The one mental model: `WorkflowState`

`models/state.py`. A folder traveling down an assembly line; each stage fills one field.

```
workflow_id, document_text         # document_text is the only field set at start
workflow_metadata   ← Discovery
workflow_facts      ← Fact Extraction
workflow_graph      ← Graph Builder
mermaid_diagram     ← Graph Builder (re-colored after CVPA)
review_report       ← Review
approval_status     ← gate: PENDING → APPROVED / REJECTED
cvpa_classification ← CVPA (post-approval)
temporal_design     ← Temporal (post-approval)
confidence_scores   ← every stage writes its own via model_copy(update=...)
stage: CompilationStage, created_at/updated_at  # touch() bumps updated_at
```

Stages (`models/enums.py::CompilationStage`):
`INGESTED → METADATA_EXTRACTED → FACTS_EXTRACTED → GRAPH_BUILT → REVIEWED → CLASSIFIED →
TEMPORAL_DESIGNED → COMPLETED` (`FAILED` on error). State is JSON-serializable → persisted → reloaded;
that durability is what makes the approval gate work across separate CLI commands / HTTP requests / processes.

---

## 3. Pipeline & the gate

```
Document ─▶ Parser ─▶ Discovery ─▶ Fact Extract ─▶ Graph Builder ─▶ Review ─▶ [GATE]
          (no LLM)    (LLM)        (LLM)            (no LLM)         (no LLM)     │
                                                          approve ───────────────┴─── reject (halts, REJECTED)
                                                             │
                                                  CVPA Classify (LLM) + recolor diagram
                                                             │
                                                  Temporal Design (LLM) ─▶ COMPLETED
```

Two invariants that define the whole architecture:
1. **LLM for judgment, determinism for correctness.** Reading/classifying = LLM. Building/reviewing the
   graph = pure functions (same facts in → same graph out, no model). If a graph looks wrong, fix the
   **facts** or **builder rules**, never a prompt.
2. **The gate splits the pipeline.** `compile_document` runs through Review then **stops** and saves.
   `approve_graph` loads and runs the rest. `_finalize_approval(state)` is the shared helper used by both
   the gated path and the `review_mode=False` auto-approve path, so their downstream output is identical.

Orchestrator: `compiler.py::WorkflowCompiler`.

---

## 4. File map (authoritative — verified against the tree)

```
src/workflow_compiler/
  compiler.py        WorkflowCompiler — orchestration + gate. from_settings() builds provider+file store.
  config.py          Settings (pydantic-settings, .env). get_settings() is lru_cached.
  env.py             loads .env into process env (python-dotenv)
  logging.py         Loguru + Rich (never logs the API key)
  exceptions.py      typed hierarchy under WorkflowCompilerError
  __init__.py        public exports (WorkflowCompiler, stores, providers, …)

  models/            Pydantic artifacts
    state.py         WorkflowState (the aggregate — start here)
    enums.py         CompilationStage, NodeType, EdgeType, CVPAPhase, FactCategory, ApprovalStatus, …
    metadata.py facts.py graph.py review.py cvpa.py temporal.py mermaid.py confidence.py base.py

  interfaces/        Abstract contracts (agents depend on these, never concretes)
    parser.py llm.py agent.py state_store.py review_manager.py

  ingestion/         prose → DocumentContent
    factory.py       DocumentParserFactory.parse(source) picks parser by ext/MIME/explicit format
    docx_parser.py pdf_parser.py markdown_parser.py html_parser.py text_parser.py
    content.py encoding.py(charset-normalizer) base.py

  llm/               provider-agnostic LLM layer
    factory.py       ProviderFactory: name→provider; from_settings() builds the configured one
    base.py          HttpChatProvider: retries, structured() JSON-extract+validate+re-ask, auth
    config.py retry.py(backoff+jitter) json_utils.py(extract_json) types.py
    providers/       nemotron.py, openai_compatible.py, mock.py

  prompts/           markdown templates + manager/loader/renderer/models
    templates/*.md   discover_workflow, extract_facts, build_graph, classify_cvpa, design_temporal, render_mermaid
                     (each has YAML front-matter declaring its variables)

  agents/            one class per stage (thin LLM wrappers around graph/ logic where applicable)
    discovery.py fact_extraction.py graph_builder.py review.py cvpa.py temporal.py
    serialization.py  compact graph/CVPA → text for prompts

  graph/             deterministic graph machinery (NO LLM)
    builder.py       WorkflowGraphBuilder.build(facts) → (WorkflowGraph, NetworkX MultiDiGraph)
    mermaid.py       to_mermaid(graph) / to_mermaid_with_cvpa(graph, classification)  ← CVPA coloring
    review.py        GraphReviewer.review(graph) → ReviewReport (+ health_score)

  review/            the gate + editing
    manager.py       DefaultReviewManager (review/approve/reject)
    editor.py        GraphEditor — 6 pure validated ops, each returns a NEW WorkflowGraph

  storage/           StateStore implementations
    file.py          FileStateStore — atomic JSON (temp+replace), I/O via asyncio.to_thread (default)
    memory.py        InMemoryStateStore — deep-copy on save/load (tests)

  api/  app.py schemas.py dependencies.py   FastAPI
  cli/  main.py                             Typer + Rich

examples/   sample business docs        docs/  architecture.md, HOW_IT_WORKS.md
tests/      unit + integration + API (no network)
```

---

## 5. Hard rules & invariants (do not break these)

- **Node ids are unique** — enforced by the `WorkflowGraph` Pydantic validator.
- **Graph builder never calls the LLM.** Determinism is a feature. Node ids are stable & meaningful
  (`activity_3`, `decision_1`, `exception_1`, `gateway_fork`).
- **Every decision node has both `yes` and `no` edges** (builder guarantees it).
- **Retry/compensation back-edges are intentional loops** — the reviewer must NOT flag them as cycles.
- **CVPA covers every node, exactly once.** The LLM proposes; the agent reconciles: keep valid
  assignments (highest confidence on dup), then **fill misses via a type-based fallback**
  (START/EVENT→Capture, DECISION/GATEWAY→Validate, TASK/SUBPROCESS/TIMER→Process, END/SIGNAL→Activate)
  at reduced confidence with a "Fallback by node type" rationale.
- **CVPA colors:** Capture=blue, Validate=amber, Process=green, Activate=purple, Unclassified=grey
  (emitted as Mermaid `classDef` + `class` statements by `to_mermaid_with_cvpa`).
- **Mermaid gotchas (real bugs, now permanent):** `end` is a reserved keyword → any colliding id is
  rewritten via `_safe_id` (`end`→`end_node`). Edge labels use the **bare** `|label|` form (not quoted);
  `"`, `|`, newlines are neutralized.
- **Temporal output is a DESIGN, never code.** A test asserts the design models have no
  `code`/`body`/`implementation` field; the system prompt forbids emitting SDK code. Don't add such fields.
- **API key** is a `SecretStr`, sent only as `Authorization: Bearer`, never logged/printed.
- **Nemotron** gets a "detailed thinking off" preamble (reasoning model would otherwise emit slow,
  JSON-polluting chains of thought).
- **Adding a vendor/format/store never touches agent or compiler code** — register with the relevant factory.

---

## 6. The 13 fact categories & key enums

`FactCategory`: inputs, outputs, activities, decisions, rules, events, apis, systems, exceptions,
state_transitions, timers, retries, compensation_candidates.

`NodeType`: START, END, TASK, DECISION, GATEWAY, EVENT, SUBPROCESS, TIMER, SIGNAL, … ·
`EdgeType`: SEQUENCE, CONDITIONAL, ERROR, RETRY, COMPENSATION, SIGNAL, … ·
`CVPAPhase`: CAPTURE, VALIDATE, PROCESS, ACTIVATE.

---

## 7. Entry points

**Library**
```python
compiler = WorkflowCompiler.from_settings()
state = await compiler.compile_document(text)          # runs to the gate, saves, returns
final = await compiler.approve_graph(state.workflow_id, reviewer="alice")  # CVPA + Temporal
```
`compile_document(text, *, review_mode=True, persist=True)` — `review_mode=False` auto-approves and runs
end-to-end in one call. Also: `reject_graph(id, reviewer, reason)`, `review_graph(id)`,
`save_state/load_state/list_states`.

**CLI** (`cli/main.py`)
```
workflow-compiler compile <doc>               # → workflow_id, stops at gate
workflow-compiler approve <id> --reviewer X --out wf.mmd   # CVPA+Temporal, writes colored diagram
workflow-compiler reject  <id> --reason "..."  # halts, no LLM
workflow-compiler show    <id>                 # no LLM
workflow-compiler compile <doc> --auto-approve # whole pipeline in one shot
workflow-compiler inspect <doc> --out wf.mmd   # discover→facts→graph preview, no save
# add --provider mock for offline runs
```

**HTTP API** (`api/app.py`, run `uvicorn workflow_compiler.api.app:app --reload`, docs at `/docs`)
`POST /compile` · `POST /approve` · `POST /reject` · `GET /workflow/{id}` · `GET /workflows` · `GET /health`.
Compiler injected via cached `get_compiler` (`from_settings()`); tests override via `dependency_overrides`.
`_guard` maps: `StateNotFoundError→404`, `ApprovalError→409`, `CompilationError→400`.

---

## 8. Config (.env, read by `config.py`)

```
NVIDIA_API_KEY=nvapi-xxxx                 # only for real LLM stages
WORKFLOW_COMPILER_LLM_PROVIDER=nemotron   # or openai-compatible / mock
WORKFLOW_COMPILER_LLM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
WORKFLOW_COMPILER_STATE_STORE_PATH=.workflow_state   # FileStateStore root
```

---

## 9. Testing & commands

- `pip install -e ".[dev]"` — install package + CLI.
- `pytest` — full suite (~173 tests, no network). LLM hidden behind `BaseLLMProvider`; `MockProvider`
  returns **queued** structured responses in order (e.g. `[discovery, facts, cvpa, temporal]`), HTTP
  layer tested with `httpx.MockTransport`.
- `ruff check src tests` — lint.
- Integration tests (`tests/test_integration.py`): gated path, auto-approve, reject-halts, disk
  persistence + reload across two compiler instances, GraphEditor round-trip, CVPA exactly-once coverage.
- **When you change behavior, add/adjust tests and keep the suite network-free.**

---

## 10. How to extend (the supported seams)

- **LLM vendor:** subclass `OpenAICompatibleProvider` (or `HttpChatProvider`), then
  `ProviderFactory().register("name", Provider)`. No agent/compiler changes.
- **Document format:** implement `BaseDocumentParser`, register with `DocumentParserFactory`.
- **Persistence:** implement `StateStore` (SQLite/S3/…), pass to the compiler.
- **Prompt:** edit the markdown in `prompts/templates/` — no code change.
- **Pipeline stage:** write a `BaseAgent` subclass, add to `agents` (pre-gate) or
  `post_approval_agents` (post-gate).

---

## 11. Working-tree note

Loose files at repo root (`*.docx`, `*.mmd` such as `New_Order_Workflow.docx`, `modify_order_workflow.mmd`,
`test_workflow.mmd`) are scratch inputs/outputs from manual runs — not source. Don't treat them as fixtures.

---

> **30-second version:** A document goes in; agents (LLM for understanding, pure functions for structure)
> progressively fill one `WorkflowState`; a human approves the reviewed graph; then CVPA labels every node
> (and re-colors the diagram) and a Temporal *design* is produced — all swappable behind clean interfaces,
> all persisted, all tested without a network.
