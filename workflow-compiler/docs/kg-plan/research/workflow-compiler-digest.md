# workflow-compiler digest — branch `demo/dialogue-plus-run` (0a6e84d), 2026-08-17

Repo root: `C:\Users\devag\Documents\Code (local)\order-workflows-demo\workflow-compiler` (all paths below are relative to it; `src/workflow_compiler/` = `WC/`).
Worktrees: master @ `../order-workflows-iterative-2.0` (ed7c343), `feat/spec-dialogue` @ `../order-workflows-dialogue` (2010260), `feat/run-workflows` @ `../order-workflows-run` (59c60ac), `feat/live-diagram` @ `../order-workflows-live` (3c92f91).

---

## 1. Pipeline stages + data models

Two orchestrators, one engine:

- **`WorkflowCompiler`** (`WC/compiler.py`, 613 lines) — the per-workflow engine. `compile_document` → Parser → `WorkflowDiscoveryAgent` → `FactExtractionAgent` (+ default-on 3-pass `ReviewPipelineAgent`) → deterministic readiness checklist → `GraphBuilderAgent` (NetworkX) + Mermaid → `GraphReviewer` (health score) → **gate**. `approve_graph` → `CVPAClassifierAgent` → `TemporalGeneratorAgent` (design/plan IR) → `TemporalCodeGeneratorAgent` (Jinja) → COMPLETED. Key methods: `compile_document`, `compile_prepared`, `approve_graph`, `reject_graph`, `_default_agents`, `_default_post_approval_agents`, `from_settings`. Emits `ProgressEvent`s.
- **`ProjectCompiler`** (`WC/project_compiler.py`, 1771 lines) — the user-facing spec-centric front-end. `compile_document` (segmentation via `WorkflowSegmentationAgent` → per-segment discovery+facts → one `WorkflowSpec` per workflow), `validate_specs`, `update_specs`, `edit_specs`/`preview_edit` (edit-request docs), `approve_spec` (seeds one `WorkflowState` per spec, calls `WorkflowCompiler.compile_prepared`, threshold gate `graph_health_threshold`=0.9), `build_diagrams`, `classify_preview`, dialogue (`prepare_dialogue/start_dialogue/answer_dialogue/skip_dialogue/end_dialogue`), spec chat (`start_spec_chat/send_spec_chat/end_spec_chat`), `write_spec_files/read_spec_files/render_overview`, `load/save/list_project`.

Models (`WC/models/`, all pydantic):
- **`WorkflowState`** (`state.py`) — the per-workflow aggregate: `workflow_id, document_text, project_id, workflow_metadata, workflow_facts, checklist, outgoing_triggers, workflow_graph, review_report, approval_status, cvpa_classification, temporal_design, temporal_code (TemporalCodeBundle), mermaid_diagram, confidence_scores, stage (CompilationStage), created_at, updated_at`.
- **`CompilationProject`** (`project.py`) — `project_id, document_text (ONE string), segments: list[WorkflowSegment], specs: list[WorkflowSpec], cross_references, triggers: list[WorkflowTrigger], spec_approval_status, workflow_ids: {slug: workflow_id}, warnings, validation_findings: {slug: [SpecFinding]}, edit_log: [EditRecord], dialogue_session, prepared_dialogue: PreparedAgenda, spec_chat: SpecChatSession, owner_id, nickname, stage_timings, stage: ProjectStage, created/updated_at`. `ProjectStage`: INGESTED → WORKFLOWS_DISCOVERED → SPEC_DRAFTED → SPEC_VALIDATED → SPEC_APPROVED → COMPILING → COMPLETED | NEEDS_ATTENTION.
- **`WorkflowSpec`** (`spec.py`) — `slug, metadata (WorkflowMetadata incl. version), facts (WorkflowFacts + structure), assumptions/ambiguities/open_questions/suggested_edits: list[SpecItem{text, provenance, resolved, answer, ref}], provenance: dict`. Also `CrossReference`, `WorkflowTrigger{source,target,mode,condition,input_map,result_binding,user_confirmed}`, `Provenance` (document_grounded | llm_inferred | human_provided). Rendered to Markdown by `WC/spec/renderer.py`, parsed back by `WC/spec/ingest.py` (round trip is identity), validated by `WC/spec/validator.py`.
- **`EditPlan`** (`edit.py`) — `patches: list[Patch], trigger_ops: [TriggerOp], xref_ops: [XrefOp], unresolved, note`; `ResolvedEdit{fingerprint, plans, project_plan, drafted_workflows, timings}`; `EditRecord` (audit). Applied by `WC/spec/edit_applier.py` (`SpecPatchApplier(human_authority=True)`, `EditPatchApplier`).
- **Dialogue** (`dialogue.py`) — `DialogueQuestion{question_id, slug, text, origin, severity, section, covers, options:[SuggestedOption{label,detail}], status, answer, chosen_option, followups, followup_options, changes, parked_as}`, `DialogueSession{session_id, questions, cursor, applied_specs, …}`, `PreparedAgenda{fingerprint, questions, drafted_at}`, LLM outputs `DraftedQuestions`, `AnswerPlan{patches, xref_ops, needs_followup, followup_question, followup_options, park_note}`.
- **Spec chat** (`spec_chat.py`) — `SpecChatTurn`, `SpecChatSession{turns, pending_instruction/question/options/slug, applied_specs}`, LLM output `InstructionPlan{target_slug, patches, reply, already_satisfied, needs_clarification, clarifying_question, clarifying_options, park_note}`.
- Others: `temporal.py` (TemporalWorkflowDesign, plan IR `TemporalStep`/`StepKind`, `GeneratedFile`, `TemporalCodeBundle`), `patch.py` (Patch/PatchAction/ReviewResult), `graph.py`, `review.py`, `cvpa.py`, `mermaid.py`, `checklist`.

## 2. Ingestion

- `WC/ingestion/`: `factory.py::DocumentParserFactory` (select by explicit format → MIME → extension; `register(parser)` for custom formats), `base.py::BaseDocumentParser` (subclasses implement `_extract`; size limits, encoding), parsers: `docx_parser.py` (python-docx, paragraphs+tables), `pdf_parser.py` (pypdf), `markdown_parser.py`, `html_parser.py` (bs4), `text_parser.py`. Output `content.py::DocumentContent{text, document_format, metadata: DocumentMetadata, sections: [DocumentSection{order, section_type, text, level}], warnings}`.
- **Upload flow**: `POST /projects/compile-upload` (multipart form: `file`, `persist=true`, `provider?`, `model?`, `nickname?`) → `DocumentParserFactory().parse(bytes, filename, content_type)` → `content.text` → `ProjectCompiler.compile_document(text, persist)` → sets `owner_id`, `nickname` → `save_project` → `ProjectResponse{project, spec_markdown:{slug:md}, time_saved, diagrams:{slug:mermaid}}`. Text path: `POST /projects/compile {document_text, persist?, provider?, model?, nickname?}`. 415 on unsupported format. Frontend: `frontend/app/page.tsx` has `<input type="file" accept=".docx,.pdf,.md,.markdown,.html,.htm,.txt">` (single file) → `api.compileUpload(file, …)` (FormData) or `api.compileText`.
- **Multi-document: NO.** A project = exactly one document (`CompilationProject.document_text: str`; the upload accepts one `UploadFile`; no folder/zip/multi-file endpoint). Only sections are extracted (`DocumentContent.sections`) but the API only forwards `content.text`. Multi-*workflow* within one document is handled by segmentation. The only way to add text later is an edit-request `## Add Workflow:` body (appended to `document_text`). Extension point for multi-doc: a new endpoint that parses N files, concatenates/labels their text (or a `documents: list[...]` field on `CompilationProject`), then calls `compile_document`.

## 3. LLM layer, agents, prompts, config

- Interface `WC/interfaces/llm.py::BaseLLMProvider` — `complete(prompt, system=…)`, `structured(prompt, Model, system=…)` (pydantic-typed), `embed`. Providers in `WC/llm/providers/`: `nemotron.py` (NVIDIA cloud), `openai_compatible.py`, `gateway.py::GatewaySessionProvider` (local DGX Spark eGPU, `local`), `fallback.py` (`local-fallback` = local primary + Nemotron fallback), `mock.py::MockProvider` (queued responses + scripted demo defaults). Registry `WC/llm/factory.py::ProviderFactory` (`register(name, builder)`, `create`, `from_settings`); names: `nemotron`, `openai-compatible`, `local`, `local-fallback`, `mock`. Base HTTP impl `WC/llm/base.py::HttpChatProvider` (retries, JSON repair `json_utils.py`, `retry.py`, `types.py`).
- Agents: `WC/interfaces/agent.py::BaseAgent(llm)` with `async run(state: WorkflowState) -> WorkflowState`. Pipeline agents in `WC/agents/`: `discovery.py, fact_extraction.py, review_pipeline.py (ReviewPass/PatchApplier), review.py, graph_builder.py, cvpa.py, temporal.py, temporal_code.py, segmentation.py, edit_interpreter.py, dialogue.py, spec_chat.py, serialization.py`. Non-pipeline agents (dialogue, spec_chat, edit_interpreter) are plain classes taking `(llm, prompt_manager)` and exposing one async method returning a pydantic plan — the "LLM specifies, deterministic engine disposes" pattern.
- **Recipe to add an agent+prompt**: (1) drop `WC/prompts/templates/<name>.md` (Jinja-ish `{{var}}` markdown; `PromptManager().render("<name>", **vars)`; `PromptManager.names()/reload()`); (2) write class with `self._llm.structured(prompt, OutModel, system=_SYSTEM)`; (3) if a pipeline stage: subclass `BaseAgent`, populate one `WorkflowState` field, add to `WorkflowCompiler._default_agents` or `_default_post_approval_agents`; if project-level: add a method on `ProjectCompiler` + route in `api/app.py` + schema in `api/schemas.py`; (4) test with `MockProvider` queued responses; (5) add to `tests/test_prompts.py` if the prompt list is asserted.
- Prompt templates (21): `classify_cvpa, design_temporal, discover_workflow, discover_workflows, draft_dialogue_questions, extract_facts, interpret_dialogue_answer, interpret_edit_request, interpret_spec_instruction, review_facts_{completeness,consistency,grounding}, review_segmentation_{…x3}, review_spec_{…x3}, review_workflow_{…x3}`.
- `WC/config.py::Settings` (pydantic-settings, env prefix `WORKFLOW_COMPILER_`): `app_name, log_level, log_json, state_store_path (".workflow_state"), llm_provider, llm_model, llm_base_url, llm_local_base_url, llm_local_model, llm_temperature, llm_timeout, require_human_approval, session_secret, session_ttl_hours, cors_origins, projects_shared, review_enabled, review_stages, predraft_questions ("off"|"cloud"|"always"), graph_health_threshold (0.9), baseline_hours, temporal_address (localhost:7233), temporal_namespace, generated_root ("./generated"), stepwise`.

## 4. Conversational surfaces (two doors to the same spec gate)

- **Guided dialogue** ("Resolve"): `WC/agents/dialogue.py::DialogueAgent.draft_questions / interpret_answer` + deterministic `WC/dialogue/engine.py::DialogueEngine` (`start/prepare/answer/skip/finish`) + `agenda.py` (askable_findings = BLOCKING+WARNING findings + unresolved open questions; fingerprint for pre-draft freshness). Agenda snapshot at start; each answer → patches applied immediately via `EditPatchApplier` with human authority, or ONE follow-up, or parked as new open question. Pre-drafting runs as a `predraft` background job after validate. Routes: `GET/POST/DELETE /projects/{id}/dialogue`, `POST …/dialogue/answer {answer, option?}`, `POST …/dialogue/skip` → `DialogueResponse{project, session, question, prompt, options}`.
- **Free-form spec chat** ("Chat"): `WC/agents/spec_chat.py::SpecChatAgent.interpret_instruction` + `WC/dialogue/chat.py::SpecChatEngine` (`start/send`, resolves target slug: caller > current > single-spec > agent pick). Routes: `GET/POST/DELETE /projects/{id}/chat`, `POST {message, slug?, option?}` → `SpecChatResponse{project, session, reply, status, slug, changes, parked_as, warnings}`.
- Shared bookkeeping `WC/dialogue/spec_ops.py` (`apply_patches`, `bump_patch_version`, `reset_to_spec_gate`, `park_as_open_question`). Both reset stage to SPEC_DRAFTED so validate must re-run.
- Frontend: project page `frontend/app/projects/[id]/page.tsx` has 3 tabs `spec | resolve | results` (`useState<"spec"|"resolve"|"results">`). The **Resolve tab renders BOTH `DialoguePanel.tsx` (guided) and `SpecChatPanel.tsx` (free-form)** side by side (page.tsx ~L538-575), using `api.getDialogue/startDialogue/answerDialogue/prepareDialogue/skipDialogue/endDialogue` and `api.getSpecChat/sendSpecChat/endSpecChat`. `SuggestedAnswers.tsx` renders option chips (click fills textarea; `option` sent only if text still matches label). Spec tab: `SpecEditor`, `DiagramPanel` (structural mermaid + CVPA color preview via `POST /projects/{id}/cvpa`), `FindingsPanel`, `EditRequestPanel`, `EditHistory`.

## 5. Execution / Run feature

- `WC/interfaces/executor.py::WorkflowExecutor` (abstract: `health/start/describe/signal/terminate/shutdown`; dataclasses `ExecutorHealth, WorkflowInputField, SignalDescriptor, RunnableWorkflow, RunEvent, RunStatus`). Impls: `WC/execution/temporal.py::TemporalExecutor` (ONLY module importing `temporalio`, lazily; optional extra `pip install .[run]`), `execution/fake.py::FakeExecutor` (tests).
- `execution/bundles.py` — `bundle_dir(root, project_id, slug)`, `materialize_bundle` (API never writes code to disk at approve; run materializes `<generated_root>/<project_id>/<slug>/` on first run, preserving hand edits), `describe_runnable`, `worker_honors_address`, `input_fields_of/signals_of(design)`.
- `execution/workers.py::WorkerPool` — Option A: spawns `python worker.py` subprocess per (bundle_dir, task_queue), reused, captures output, readiness wait.
- `execution/runs.py::RunRegistry` — in-memory run index (Temporal is the durable record).
- Routes: `GET /projects/{id}/runnable`, `POST /projects/{id}/runs {slug, input}`, `GET /projects/{id}/runs`, `GET /runs/{run_id}` (state running/completed/failed/compensated/…, events, current_step), `POST /runs/{run_id}/signal {name, args}`, `DELETE /runs/{run_id}`. `GET /health` reports `temporal: {reachable}`. Wired in `api/dependencies.py::get_executor`.
- Frontend `RunPanel.tsx` (inside `ResultsView.tsx`): workflow chip, input form pre-filled from generated sample values, Run button, status/step trail, signal buttons; polls `api.getRun`. Temporal dev server: `temporal server start-dev --port 7243 --ui-port 8243` (demo runbook), `WORKFLOW_COMPILER_TEMPORAL_ADDRESS`.

## 6. Codegen

- `WC/codegen/temporal/generator.py::TemporalPythonCodeGenerator.generate(design)` (1308 lines; walks plan IR → run body via `_RunBodyEmitter`; saga compensations, signals, queries, timers, branches, parallel, triggers, stepwise gating). Templates (`templates/*.jinja`): `README.md, activities.py, shared.py, starter.py, test_stepthrough.py, triggers.py, worker.py, workflow.py`. `project_generator.py::generate_project_files` adds project-root `contracts.py` + `README.md` (deployment topology).
- Bundle = `<slug>/{shared.py, activities.py (stubs), workflow.py, worker.py, starter.py (sample input), test_stepthrough.py, README.md, triggers.py (if source of triggers)}` + root `contracts.py, README.md`. Stored on `WorkflowState.temporal_code` (`TemporalCodeBundle.files: [GeneratedFile{path, content, language}]`); served by `GET /projects/{id}/files`; zipped client-side (JSZip in `ResultsView`).
- **Tests generated?** Only `test_stepthrough.py` (a runtime step-through harness under `WorkflowEnvironment.start_time_skipping()` printing queries) — no unit tests per activity, and **no test-case DOCUMENT** (no test plan/markdown/docx) is generated anywhere.
- **Diagrams**: `WC/graph/mermaid.py` (`to_mermaid`, `to_mermaid_with_cvpa`) per workflow; `ProjectCompiler.build_diagrams` → `ProjectResponse.diagrams`; CLI writes `diagram.mmd` next to bundles. No cross-workflow "system flow" diagram exists (only the textual trigger topology in project `README.md`). `feat/live-diagram` adds live run-state coloring of the existing mermaid (see §11), still per-workflow.

## 7. API route inventory (`WC/api/app.py`, 1567 lines) + jobs

| Method | Path | Purpose |
|---|---|---|
| GET | /health | liveness + temporal reachability |
| POST | /auth/register, /auth/login, /auth/logout | local accounts, cookie session |
| GET/PUT | /auth/me | user + preferences (baseline_hours overrides) |
| GET | /settings/defaults | org baseline hours |
| GET | /providers/local/models | list local gateway models |
| POST | /approve, /reject | classic per-workflow graph gate (manual override) |
| GET | /workflow/{id}, /workflows | stored WorkflowState |
| POST | /projects/compile | text → project (spec gate) |
| POST | /projects/compile-upload | multipart file → project |
| GET | /metrics/summary | time saved aggregate |
| GET | /projects | summaries |
| GET/PATCH | /projects/{id} | load / rename |
| GET | /projects/{id}/files | generated bundle files (flat tree) |
| PUT | /projects/{id}/spec | fold edited spec markdown (no LLM) |
| POST | /projects/{id}/edit, /edit/preview | edit-request document apply / dry-run |
| POST | /projects/{id}/validate | sync validate |
| POST | /projects/{id}/approve | sync approve-spec → codegen |
| GET/POST/DELETE | /projects/{id}/dialogue (+/answer, /skip) | guided dialogue |
| GET/POST/DELETE | /projects/{id}/chat | free-form spec chat |
| POST | /projects/{id}/jobs | start background job (in `test`/route list as `start_job`; kind validate|approve) |
| GET | /jobs, /jobs/{id}; POST /jobs/{id}/cancel | job polling |
| POST | /projects/{id}/cvpa | CVPA color preview |
| GET | /projects/{id}/runnable | runnable workflows + input schema + signals |
| POST/GET | /projects/{id}/runs | start / list runs |
| GET/DELETE | /runs/{id}; POST /runs/{id}/signal | run status / terminate / signal |

`WC/api/jobs.py`: `JobKind = Literal["validate", "approve", "predraft"]`, `JobStatus = running|succeeded|failed|canceled`; `JobManager.start/get/list/cancel`; one active non-speculative job per project (409), `predraft` is speculative (exempt, auto-cancelled by user jobs). Cancel never persists partial results. In-memory. Schemas in `api/schemas.py` (JobStartRequest, JobResponse{…, project when succeeded}). Errors: `StateNotFoundError→404, ApprovalError→409, CompilationError→400`.

## 8. Frontend (`frontend/`, Next.js app router + react-query)

- Pages: `app/page.tsx` (home: paste text or upload one file, provider/model picker, `ProjectsPanel`), `app/projects/[id]/page.tsx` (713 lines; tabs spec/resolve/results), `app/login`, `app/settings`, `app/guide` (+`/guide/edits`), `app/layout.tsx`, `app/providers.tsx`.
- Components: `SpecEditor, SpecPreview, DiagramPanel, MermaidView, FindingsPanel, EditRequestPanel, EditHistory, DialoguePanel, SpecChatPanel, SuggestedAnswers, ResultsView (files list, code viewer, mermaid, Download .zip via JSZip, RunPanel), RunPanel, RunningOverlay, ProjectsPanel, TimeSaved, StructuredWidgets, Skeleton, ThemeToggle, UserMenu, NavLink`.
- `lib/api.ts` — one `api` object of ~40 methods (`health, me, login, register, logout, updateProfile, settingsDefaults, listProjects, renameProject, metricsSummary, listLocalModels, getProject, compileText, compileUpload, saveSpec, editProject, previewEdit, validate, approve, getDialogue, startDialogue, answerDialogue, prepareDialogue, skipDialogue, endDialogue, getSpecChat, sendSpecChat, endSpecChat, startJob, listJobs, getJob, cancelJob, classifyCvpa, projectFiles, getWorkflow, approveWorkflow, rejectWorkflow, runnable, startRun, listRuns, getRun, signalRun, terminateRun`); `request<T>()` wrapper, `ApiError`, `API_BASE` = `NEXT_PUBLIC_API_BASE`. `lib/types.ts` (530 lines) mirrors schemas; `lib/runs.tsx` = global job registry provider polling `GET /jobs` while anything in flight (toasts, survives navigation); `lib/auth.tsx`; `lib/spec-grammar.ts` + `specHighlight.ts` (spec md highlighting); `lib/format.ts`.
- Job flow: click Validate/Approve → `api.startJob(id, {kind,…})` → `RunningOverlay` while `runs.tsx` polls → on succeeded, `getJob` embeds project.

## 9. Storage

- `WORKFLOW_COMPILER_STATE_STORE_PATH` (default `.workflow_state/`): `<workflow_id>.json` (`storage/file.py::FileStateStore`), `projects/<project_id>.json` (`storage/project_store.py::FileProjectStore`, `ProjectStore` Protocol, `InMemoryProjectStore`), `users/<user_id>.json` (`storage/user_store.py`). Atomic JSON writes; no DB.
- Generated code: `generated_root` (default `./generated`) → `<project_id>/<slug>/{bundle}` + `<project_id>/{contracts.py, README.md}` (CLI `--out-dir` writes at approve; API writes only on first Run via `materialize_bundle`). Legacy single-workflow dirs `generated/<slug>/` from the classic CLI.
- Prompt templates are package data; no other persistence.

## 10. Tests

- `tests/` — 43 test modules, **560 test functions**, all offline. Grouped: agents (`test_*_agent.py`), pipeline (`test_compiler.py`, `test_project_compiler.py`, `test_integration.py`), spec layer (`test_spec_layer.py`, `test_edit_*.py`, `test_patch_enum_coercion.py`), dialogue (`test_dialogue.py`, `test_dialogue_prepared.py`, `test_spec_chat.py`), API (`test_api*.py` incl. `test_api_dialogue`, `test_api_spec_chat`, `test_api_jobs`, `test_api_runs`, `test_api_auth`), codegen (`test_temporal_codegen.py`, `test_trigger_codegen.py`, `test_codegen_starter.py`, `test_codegen_workflow_input.py`, `test_temporal_ir_runtime.py` — needs temporalio), execution (`test_execution_bundles.py`), ingestion (`test_ingestion.py`, reportlab for PDF fixtures), llm (`test_llm.py`), misc.
- Pattern: `conftest.py` fixtures `sample_document`, `fresh_state`; tests build `MockProvider(responses=[...])`/queued structured outputs (unqueued → scripted demo defaults when built via factory), `InMemoryStateStore`/`InMemoryProjectStore`, `FakeExecutor`; API tests use `TestClient` with dependency overrides (`get_compiler`, `get_project_compiler`, `get_executor`, user store). Browser acceptance scripts (not pytest) live in `demo/capture2/*.mjs`.

## 11. Branch deltas

- **demo/dialogue-plus-run vs master** (92 files, +15073/-125): everything from `feat/spec-dialogue` + `feat/run-workflows`: guided dialogue (`agents/dialogue.py`, `dialogue/{engine,agenda,spec_ops}.py`, `models/dialogue.py`, 2 prompts, `DialoguePanel`, `SuggestedAnswers`, predraft job kind), free-form spec chat (`agents/spec_chat.py`, `dialogue/chat.py`, `models/spec_chat.py`, prompt, `SpecChatPanel`), `spec/wiring.py` (TriggerOp/XrefOp), Run feature (`interfaces/executor.py`, `execution/*`, `/runs` routes, `RunPanel`, `temporalio` optional extra), codegen fixes (WorkflowInput fields, signal names, enum patch coercion, sample input in starter), docs (`DEMO_RUNBOOK`, `DIALOGUE_OPTIONS_HANDOFF`, `RUN_WORKFLOWS_HANDOFF`, `RUN_FEATURE_DESIGN`, `PIPELINE_HANDOFF`, `PIPELINE_RUN_LOG`, `SESSION_CLAIMS`), demo acceptance scripts.
- **feat/live-diagram** (1 commit 3c92f91 on top of demo, frontend-only, 5 files +307): `lib/runHighlights.ts` (maps run events → mermaid node ids by normalized token match), `MermaidView.tsx` applies run-done/active/waiting/failed CSS classes to rendered SVG nodes, `ResultsView.tsx` folds run events into node→status map + legend, `RunPanel.tsx` reports polled run upward and is keyed by slug, `globals.css` styles. Verified live against Temporal dev server. Not merged into demo yet — clean fast-forward candidate.

## 12. Existing document-generation abilities

- **None for business docs.** The app produces: spec Markdown (`spec/renderer.py`, strict grammar; `overview.md` via `render_overview`), Mermaid `.mmd`, generated Python bundle + per-bundle `README.md` + project `README.md` (topology) + `contracts.py`. No impact-analysis, design doc, epics/user stories, or test-case documents.
- `python-docx>=1.1` IS a runtime dependency (pyproject `dependencies`) but used only for READING (`ingestion/docx_parser.py`); no `.docx` writing code anywhere. `pypdf` read-only; `reportlab` dev-only for test fixtures. Jinja2 present (codegen) — usable for md/html doc templates. So writing `.docx` needs no new dependency; writing PDF would.

## Extension hot-spots (summary)
- New LLM agent: `prompts/templates/*.md` + class using `llm.structured` + `ProjectCompiler` method + `app.py` route + `schemas.py` + `api.ts` method + `types.ts`.
- Long jobs: add a `JobKind` in `api/jobs.py` and a branch in the `/projects/{id}/jobs` handler; frontend `runs.tsx` polls generically.
- New artifact type stored per project: add optional field to `CompilationProject` (JSON store tolerates), surface via `ProjectResponse` or a new `GET /projects/{id}/<artifact>`.
- New tab: `page.tsx` tab union + segment button + panel component.
- Multi-doc: new upload route + model field; segmentation prompt `discover_workflows.md` already reasons over one large text.
