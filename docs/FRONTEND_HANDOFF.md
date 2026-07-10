# Frontend Handoff — workflow-compiler web UI

> Give this file to a fresh planning session. It contains everything needed to plan and build
> the frontend: what the product does, the verified pipeline behavior (live LLM runs, July 2026),
> the exact API surface and its gaps, the spec-file grammar the editor must respect, decisions
> already made, and known backend limitations the UI must surface.

## 1. What the product is

`workflow-compiler` (Python 3.12, this repo) compiles free-form business workflow documents
(`.docx/.pdf/.md/.html/.txt`) into runnable Temporal Python code through **one pipeline**:

```
upload document ─▶ POST /projects/compile      (LLM: segment → per-workflow facts → specs)
                ─▶ user edits spec markdown    [THE HUMAN GATE — this is the core UI surface]
                ─▶ POST /projects/{id}/validate  (fold edits in deterministically + LLM review passes)
                ─▶ iterate edit ⇄ validate until findings are clean
                ─▶ POST /projects/{id}/approve   (graph → CVPA → Temporal design → code, per workflow)
                ─▶ view/download generated Temporal bundles
```

Single-workflow documents flow through the same pipeline (segmentation yields one segment holding
the full document). A workflow whose graph health < 0.9 at approve is left `PENDING`; the user
resolves it with the manual override (`POST /approve` / `POST /reject` with its `workflow_id`).

Authoritative references in this repo: `README.md` (commands + API), `docs/HOW_IT_WORKS.md`
(design), `docs/architecture.md` (diagrams), `src/workflow_compiler/api/app.py` (endpoints),
`src/workflow_compiler/spec/renderer.py` (spec line grammar, docstring is normative).

## 2. Verified behavior (live Nemotron runs on the two ideal docs, 2026-07-10)

Both `examples/ideal_temporal_workflow.md` (1 workflow) and `examples/ideal_multi_workflow.md`
(3 workflows + cross-dependencies) were run end-to-end with the real LLM **twice** — once to
diagnose, once after the fixes (commits `c896bfa` and `f4b002b`) — including the full user
edit ⇄ validate loop. Final state:

- Segmentation found exactly the right workflows, **all 3 cross-workflow dependencies**, and
  (post-fix) exactly **one merged trigger scaffold per workflow pair**.
- The edit ⇄ validate loop works: user edits (fixing decision branches, removing wrong entities,
  answering open questions, confirming dependency/trigger checkboxes, re-adding an element the
  validator wrongly removed) all folded back in deterministically and survived validation.
- All four generated bundles **execute end-to-end** under Temporal's time-skipping test
  environment: `python -m pytest test_stepthrough.py` passes in every bundle — the happy path
  completes with signal gates auto-released by the harness. (Run the harness with **pytest**;
  invoking it with plain `python` is a silent no-op.)
- **Rejection paths terminate**: a decision's `no:` branch generates
  `raise ApplicationError(type=<ExceptionName>, non_retryable=True)`, which fires the reversed
  saga compensations and fails the run — a rejected order can no longer report success.
- Generated code correctly contains: real branch conditions bound to step results
  (`eligibility == 'eligible'`, `bool(is_settleable)`), bounded `wait_condition` + signal handler
  (signal waits), `asyncio.gather` (parallel groups), reversed saga compensations, per-activity
  retry policies and SLA timeouts from the document, data threading between steps, `triggers.py`
  (cross-workflow starts on the target's task queue with idempotent ids), project `contracts.py`
  + `README.md`.

## 3. What the user actually has to fix in the loop (design the UI around this)

The LLM extraction is good but not perfect. Observed misses the user corrected via spec edits —
the editor should make these easy to spot:

- **Decisions missing their `no:` branch** (the readiness gate catches this and asks an Open
  Question — surface open questions prominently with answer inputs). Note the stakes: the `no:`
  target is what generates the rejection `raise` in code, so this edit matters most.
- **Missing `raised by:` on exceptions**, **missing `parallel: g` on one member of a pair**.
- **A compensation duplicated as an activity** (user deletes the activity line).
- **Outputs duplicated as events** (user deletes the event line).
- **Semantically wrong scaffolded triggers** the user deletes (e.g. auto-firing a
  *customer-initiated* return workflow). Duplicate half-entries are fixed — the scaffolder now
  merges condition + input rows into one entry per pair — but whether a trigger *should exist*
  remains a human call; render triggers as editable cards.
- **Elements the validator wrongly removed** (see R8): the validate pass occasionally deletes a
  correct, document-grounded element. Removals now appear as findings, and removals that would
  orphan references are blocked — but the UI should show removals prominently (a diff view of
  the spec before/after validate) so the user can re-add with one click. A re-added line sticks.
- **`domain:` / `owner:` / `tags:` metadata not extracted** from doc metadata tables (blank).

## 4. The spec markdown grammar (the editor's contract)

The spec file is a deterministic projection of a structured model; edits are parsed back with no
LLM. The editor (or its lint layer) must preserve:

- `[id]` markers on existing entity lines (`- [a1] Validate Cart — parallel: g1`); a line
  without an id is treated as a **new, human-provided** element.
- Tail syntax: `— key: value; key: value`. Keys per section:
  activities `parallel`; decisions `after`/`yes`/`no`; exceptions `raised by`;
  compensations `compensates`; events `kind` (`trigger` | `signal_wait` | `output_emit`,
  hyphen/space variants normalized) and `emitted by`.
- Open Questions: `- [ ] (<ref>) <question>` + indented `Answer:` line (tick `[x]` + fill answer).
- Cross-Workflow Dependencies: checkbox lines — ticking `[x]` is the confirmation the backend
  requires before approve (unconfirmed deps block approval unless overridden).
- Triggers: `- [x] triggers `slug` (blocking|fire-and-forget) when `<condition>`` with indented
  `result:` and `input <field>: <source> `ref` (<type>)` lines.
- Provenance markers `[human]` / `[inferred]` trailing a line (absent = document-grounded).
- Empty sections render `<!-- none -->`.

Deleting a line deletes the element; the validator only ever *flags* (never deletes) elements the
user added. **Event `kind` is critical**: it is what makes a wait a bounded `wait_condition`
instead of a hang — the UI should render it as a first-class affordance (e.g. a badge/dropdown),
not just text.

## 5. Existing API (FastAPI, `uvicorn workflow_compiler.api.app:app`)

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/projects/compile` | `{document_text, persist?}` | Segment → specs (stops at spec gate) |
| GET | `/projects` | — | List project ids |
| GET | `/projects/{id}` | — | Project + `spec_markdown: {slug: markdown}` |
| PUT | `/projects/{id}/spec` | `{spec_markdown}` | Fold edits back (no LLM — cheap save) |
| POST | `/projects/{id}/validate` | `{spec_markdown?}` | Ingest edits + LLM review passes + findings |
| POST | `/projects/{id}/approve` | `{workflows?, reviewer?, spec_markdown?, accept_incomplete?, allow_unconfirmed_references?}` | Compile all to code |
| POST | `/approve` | `{workflow_id, reviewer?}` | Manual override for a pending graph |
| POST | `/reject` | `{workflow_id, reviewer?, reason?}` | Reject a pending graph |
| GET | `/workflow/{id}` | — | Full `WorkflowState` (graph, mermaid, review report, CVPA, design, `temporal_code.files[].content`) |
| GET | `/workflows` | — | List workflow ids |
| GET | `/health` | — | Liveness |

Every project response returns the **rendered spec markdown for every workflow** plus the full
`CompilationProject`: `stage` (`ingested → workflows_discovered → spec_drafted → spec_validated →
spec_approved → compiling → completed | needs_attention`), `validation_findings: {slug: [{severity:
BLOCKING|WARNING|INFO, section, field, message, suggestion}]}`, `cross_references[].user_confirmed`,
`triggers[]`, `workflow_ids: {slug: workflow_id}`, `warnings[]`.

Generated code arrives **in-band as JSON** (`temporal_code.files[].{path, language, content}`) —
the frontend can render/zip client-side.

## 6. API gaps the frontend build must add (thin backend wiring, all logic exists)

1. **CORS middleware** — none configured.
2. **Multipart file upload** for `.docx`/`.pdf` — API is text-only today; wire
   `ingestion.DocumentParserFactory` (already parses all formats for the CLI) behind a new
   endpoint (note: it takes a `Path` today — needs a bytes/stream entry point or temp file).
3. **Zip download** of a bundle / whole project (optional; client-side zip also works).
4. **Project-glue files** (`codegen/temporal/project_generator.generate_project_files` →
   `contracts.py` + project `README.md`) — currently only the CLI writes them; expose on the
   project approve response or a dedicated endpoint.
5. Optional: request-level provider/model/timeout override (API is env-singleton today; per-request
   timeout matters because Nemotron requests can take 60–180s — see timings below).
6. Optional: an SSE/WebSocket progress channel. The compiler already emits structured
   `ProgressEvent`s (`compiler.py: ProgressCallback`) — segmentation 90–130s, per-workflow fact
   extraction 80–180s, validate 10–60s, approve (CVPA+design) 60–120s per workflow. Without
   progress streaming the UI will sit on multi-minute spinners.
7. **Request-duration plumbing**: `/projects/compile` and `/projects/{id}/approve` can run for
   several minutes. If the Next.js app proxies API calls through its own routes, default
   serverless/route timeouts will kill them — call the FastAPI origin directly from the browser
   (hence CORS in item 1) or move long operations to a background-job + polling pattern.
8. **No auth / single-user today**: the API has no authentication, no user scoping, and a
   process-wide `lru_cache` compiler singleton. Fine for a local/internal tool; anything
   client-facing needs at least a reverse-proxy auth layer, and concurrent LLM runs from several
   users will contend on the free Nemotron tier.

## 7. Decisions already made (do not re-litigate)

- **Next.js** app (new `frontend/` dir at repo root).
- Spec editing = **markdown editor + rendered preview** (CodeMirror/Monaco), with lint hints for
  broken `[id]` markers / grammar; structured widgets only for high-risk parts if time allows
  (open-question answers, dependency/trigger checkboxes, event-kind badges).
- **Extend the FastAPI layer** for the gaps above (yes to backend changes).
- Diagrams: `WorkflowState.mermaid_diagram.source` → render with mermaid.js (CVPA-colored after
  classification).

## 8. Known backend limitations to surface in the UI (fix plan, prioritized)

Fixed and verified live (regression-tested; all four ideal-doc bundles now pass their generated
`test_stepthrough.py` under a real Temporal test environment):

- event-kind round-trip corruption; dead-end penalty on output events (ideal docs clear the 0.9
  auto-gate); bare-identifier + `== literal` branch predicates compile to real conditions;
  decision-gated parallel groups are expressible; unbound step inputs fall back to name-matched
  workflow inputs.
- **R1 rejection paths**: a `raise` StepKind exists; a deterministic pass fills a rejecting
  decision's empty else-lane with `raise ApplicationError(<exception>)`, and a companion pass
  prunes LLM-misplaced raises (only the else-lane position is legal). Rejected runs now fail with
  a typed error and fire the saga compensations.
- **R2 predicate contract**: the design prompt requires predicates to be declared result names
  (bare or `== literal`) with fixed lane polarity (then = success).
- **R3 trigger dedup**: one scaffold per (source, target) pair; condition and input map merge.
- **Validator can no longer orphan the flow**: a grounding `remove` targeting an entity that other
  entities reference (a decision's branch target, a compensation's activity, …) is skipped and
  surfaced as a WARN instead of silently deleting it.
- **Runnable-by-default scaffolds**: activity stubs return truthy placeholders, and when a branch
  compares a result to a literal the producing stub returns that literal — the default run takes
  the happy path. The generated harness auto-sends every declared signal so bounded waits release.

**Flow rule the UI must encode:** after any spec edit, **Validate must run before Approve** —
`approve` checks the findings computed by the *last validate*, so approving with stale findings
fails with the previous cycle's blocks. In the UI: disable Approve until a validate has run on the
current spec content (or auto-chain validate → approve).

Remaining (the UI should tolerate/flag these):

- **R4 (P2): "Wait for X" duplicated** as both an activity and a `signal_wait` event → an unused
  activity stub in the bundle. Dedup at design fold.
- **R5 (P2): metadata table extraction** (domain/owner/tags land blank).
- **R6 (P2): no grammar for "on exception X, do Y"** (e.g. escalate-on-refund-failure) other than
  compensations.
- **R7 (P3): prose trigger conditions** (`when 'an order is placed'`) can't compile to code —
  always a TODO in `triggers.py` call sites; consider structured conditions.
- **R8 (P2): validator grounding flakiness.** The LLM validate pass sometimes proposes removing
  document-grounded elements (it tried to delete `Create Order` three times in one session). The
  referenced-entity guard now blocks the harmful cases; unreferenced correct elements can still be
  removed — the user re-adds the line and it sticks (surface removals prominently in the UI diff).

## 9. Suggested UI shape (starting point, not binding)

1. **Projects list** → new project (file upload or paste text) → compile with live progress.
2. **Project workspace**: left = workflow tabs (one per slug) + overview (stage, findings count,
   dependency confirmation status); center = markdown editor ⇄ preview; right = findings panel
   (BLOCK red / WARN yellow / INFO dim, clickable → scroll to section) + open questions + diagram.
3. Actions: **Save** (PUT spec — instant, no LLM), **Validate** (POST validate — shows new
   findings, editor reloads the re-rendered markdown), **Approve** (guarded by: a validate has
   run on the *current* editor content — see the §8 flow rule — blocking findings = 0, deps
   confirmed; else needs explicit override toggles matching `accept_incomplete` /
   `allow_unconfirmed_references`). Consider a combined "Validate & Approve" button that chains
   the two calls when validate comes back clean.
4. **Results view**: per-workflow file tree with code viewer (files from `temporal_code.files`),
   mermaid diagram, review report/health, CVPA table; download-zip. Pending (below-threshold)
   workflows get an approve/reject override card showing the review issues.
5. State is fully server-side (JSON stores under `.workflow_state/`); the UI can be stateless.

## 10. Repo facts a new session will want

- Run backend: `uvicorn workflow_compiler.api.app:app --reload` (needs `.env` with
  `NVIDIA_API_KEY`, or `WORKFLOW_COMPILER_LLM_PROVIDER=mock` for offline demo — the mock answers
  every stage with a scripted demo workflow, ideal for frontend development).
- Tests: `pytest` (295 passing, fully offline), `ruff check src tests`. mypy has ~35 pre-existing
  errors (not clean at HEAD either).
- Generated bundles' `test_stepthrough.py` must be run with **pytest** from inside the bundle
  directory (`python -m pytest test_stepthrough.py`); plain `python test_stepthrough.py` defines
  the test and exits 0 without running anything.
- Windows console needs `PYTHONUTF8=1` for CLI output (irrelevant to the API).
- Relevant commits: `df0d6a5` (pipeline consolidation), `c896bfa` (first five verified fixes +
  this handoff), `f4b002b` (rejection paths, predicate contract, trigger dedup, validator guard,
  runnable-by-default scaffolds).
- Real-run artifacts, **newest first** (best UI fixtures): `specs-r1-single/`, `specs-r1-multi/`,
  `generated-r1-single/`, `generated-r1-multi/` (post-fix: raises in rejection lanes, real
  predicates, merged triggers, harness auto-signals). Older pre-fix runs for comparison:
  `specs-ideal-single-2/`, `specs-ideal-multi-run/`, `generated-ideal-single-2/`,
  `generated-ideal-multi-run/`.
