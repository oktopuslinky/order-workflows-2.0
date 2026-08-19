# KG change pipeline — handoff

**Current phase:** Phase 5 **complete** (2026-08-19) — **the plan's five phases are done**; this is
the final state file. Start with `RUNBOOK.md` (*Demo script* + Phase 5 results), then this file
("What exists after Phase 5", "Ids / facts", "Open issues"), then `KG_CHANGE_PIPELINE_PLAN.md`
for the contract. Follow-up work (if any) is the "Open issues" backlog — model-quality items,
not missing features.

**Worktree:** `C:\Users\devag\Documents\Code (local)\order-workflows-kg`, branch
`feat/kg-change-pipeline` (from `demo/dialogue-plus-run` @ `0a6e84d`). Own `.venv` (Python 3.12,
`pip install -e ".[dev]"`), `.env` copied from the demo worktree, `frontend/node_modules`. Live
servers for this worktree run on **127.0.0.1:8010 / :3010** (RUNBOOK bring-up; the demo worktree
holds 8000/3000; do not use `--reload` while jobs run). Demo account `kgdemo@example.com` /
`kgdemo-pass-2026`.

## What exists after Phase 0 (knowledge bases)

Backend (`src/workflow_compiler/`):

| Path | Role |
|---|---|
| `kg/contexthub/` | Vendored Context Hub subset @ `0447cad`; local edits in `kg/contexthub/VENDORED.md`. mypy `ignore_errors`; ruff style rules relaxed for this dir only. |
| `kg/models.py` | `KnowledgeBase{…, catalog{epics,stories,test_cases,requirements,documents}}`, `KgPacket/KgSection/KgFileRef`, `KgImpactRow`, `KgSearchHit`, `KgGraphSummary`, `KbFile`. **`catalog.documents`** (new in Phase 1) = document ids regexed from `.contexthub/extracts/*.txt` (`BRD-ORD-001`, `TDD-ORD-001`, `TP-ORD-001`), computed live in `KgService.catalog()`. |
| `kg/store.py` | `KnowledgeBaseStore` protocol, `FileKnowledgeBaseStore` (`<state>/knowledge_bases/<id>.json` + `<id>/{corpus,.contexthub}`), `InMemoryKnowledgeBaseStore(root)`; `validate_kb_id`. |
| `kg/ingest.py` | `extract_zip` (zip-slip/symlink rejection, caps, top-level folder stripped), `copy_tree`, `zip_folder`. |
| `kg/llm_bridge.py` | `ProviderJsonClient(provider, loop)` for the vendored enrich/cluster code. |
| `kg/service.py` | `KgService(store, provider_factory)`: `create_from_zip/path`, `index`, `reindex`, `get`, `list_all`, `delete`, `retrieve`, `search`, `impact`, `catalog`, `graph_summary`, `list_files`, `read_file`; mtime-keyed graph cache. |
| `api/jobs.py` | `Job.scope_id`/`scope_kind` (`project` \| `knowledge_base` \| `change_request`), `JobProgress`, `JobKind = validate \| approve \| predraft \| kb_ingest \| cr_questions \| cr_draft \| cr_revise`. |
| `api/dependencies.py` | `provider_for_selection`, `kb_provider_factory` (default `nemotron`), `get_kg_service()`, **`get_change_service(kg=Depends(get_kg_service))`**. |
| `cli/kb.py`, `config.py` | `kb init\|list\|show\|ask\|impact\|search\|delete`; `kg_enrich_default`, `kg_retrieve_budget`, `kg_max_upload_mb`, **`change_kg_budget=9000`**. |

Frontend: `app/knowledge/page.tsx`, `app/knowledge/[id]/page.tsx`, `components/KbStatusPill.tsx`,
`lib/runs.tsx` (job poller; now also `change_request` jobs). Examples: `examples/knowledge_bases/order-lifecycle/`
(+ `.zip`), `examples/change_requests/BCR-001-partial-shipment-support.docx`, `scripts/make_kb_zip.py`.

## What exists after Phase 1 (change requests + wizard)

| Path | Role |
|---|---|
| `models/change.py` | `ChangeRequest{cr_id, kb_id, kb_name, owner_id, title, document_text, source_filename, bcr_meta{doc_id,status,requested_by,date_raised,target_workflow}, requirements[{id,text}], impact_seed_terms, impact_table[ImpactTableRow], ids: AssignedIds{epic_id, story_ids, tdd_id, next_test_case, prior_epic_id, prior_tdd_id}, wizard: WizardSession{steps[4], cursor, provider, model, started_at}, artifacts: ChangeArtifacts{impact,epic,stories,tdd: Artifact{kind, markdown, version, status empty\|drafted\|approved, history[ArtifactVersion{version, markdown, source llm_draft\|llm_revision\|human_edit, note, at}], sources[SourceRef{path,spans}], coverage, approved_at}}, project_ids, stage created\|in_progress\|complete, warnings}`; `WizardStep{kind, status pending\|asking\|drafting\|drafted\|approved, questions[WizardQuestion{text, why, options[SuggestedOption], status, answer, chosen_option, followups, followup_options, note}], notes, turns[ChatTurn], error, started_at, drafted_at, approved_at}`; doc models `ImpactDoc / EpicDoc / StoriesDoc(StoryDoc) / TddDoc(TddSection)` + `TDD_SECTIONS` (14 keys/numbers/titles); LLM schemas `DraftedWizardQuestions, AnswerNote, ImpactDraft, ImpactCoverageDraft, EpicDraft, StoriesDraft, TddDraft, Revision{sections[RevisedSection{heading, markdown}], summary}`. |
| `change/bcr.py` | Deterministic BCR reading: `parse_meta`, `parse_requirements` (`ID \| text` rows or `ID — text` lines), `parse_title`, `seed_terms` (paths → basenames, snake_case identifiers, `TDD §4.3`, UPPER_SNAKE states, US/TC/EPIC/BR ids, CamelCase), `title_from_filename`. |
| `change/ids.py` | `assign_ids(catalog, target_hint)` → EPIC-002 / TDD-ORD-002 (family from the BCR's `TDD-ORD-001` hint or the catalog) / TC-18 / prior ids; `story_ids(catalog, n, already=…)` → US-008…; widths follow existing ids. |
| `change/render.py` ⇄ `change/parse.py` | Markdown renderers/parsers for the four artifacts (round trip tested). Titles `# Impact Analysis — BCR-001 — Title`, `# EPIC-002 — Title`, `# User Stories — EPIC-002 — Title` with `## US-008: Title` per story (`### Story / Acceptance Criteria / Notes`, meta lines `**Epic/Status/Story Points/Implements:**`), `# TDD-ORD-002 — Subtitle` with `## N. Title` / `## 4. Workflow Design` → `### 4.x Title`, each with `### Existing` / `### Proposed` (`####` under 4.x); `**Label:** value` metadata lines (blank-line separated); `> coverage note`; `## Appendix A — Knowledge-graph traversal (deterministic)` (impact only); `## Sources` footer ``- `path` — lines a-b``. `parse_artifact(kind, md)`; `ArtifactParseError` when the title heading is missing. |
| `change/engine.py` | `ChangeWizardEngine(agent, kg, per_query_budget=1000, total_budget=9000, impact_hops=2, max_impact_rows=120)`: `initialize` (ids + impact traversal), `start`/`start_step` (questions), `answer` (one follow-up max), `skip`, `draft(kind, progress)` (impact = draft + **coverage pass** over un-mentioned traversal candidates; epic = story-map ids from catalog; stories = batches of 3 from the epic's story map; tdd = 4 chunks of `TDD_SECTIONS`), `revise` (section-scoped: `splice_sections` + table-merge guard, appendix/Sources protected), `edit`, `approve` (cursor advances; all approved → `complete`), `brief(cr, kind)` (BCR + requirements + assigned ids + **cumulative** decisions + KG impact table with node ids + **business-id glossary** + de-duplicated KG excerpts + prior artifacts), `id_glossary`, `brief_lite`. `WizardStateError(ApprovalError)` → 409. Later steps cannot be drafted before the previous one is approved; earlier steps can be re-drafted (needs re-approval). |
| `change/service.py` | `ChangeRequestService(store, kg, provider_factory, kg_budget, per_query_budget)`: `create(kb_id, data\|text, filename, title, owner_id, provider, model)`, `get`, `list_all`, `delete`, `start`, `start_questions`, `answer`, `skip`, `draft`, `revise`, `edit`, `approve`, `artifact(cr_id, kind, version)`. Provider/model stored on `cr.wizard`; the engine is built per call. |
| `storage/change_store.py` | `ChangeRequestStore` protocol, `FileChangeRequestStore` (`<state>/change_requests/<id>.json`), `InMemoryChangeRequestStore`, `validate_cr_id`. |
| `agents/change_analyst.py` | `ChangeAnalystAgent(llm)`: `draft_questions`, `interpret_answer`, `draft_impact`, `draft_impact_coverage`, `draft_epic`, `draft_stories`, `draft_tdd_sections`, `revise`. Prompts `prompts/templates/change_{questions,answer,impact,impact_coverage,epic,stories,tdd,revise}.md`. |
| `api/app.py` + `api/schemas.py` | Routes `POST/GET /change-requests`, `GET/DELETE /change-requests/{id}`, `GET …/wizard`, `POST …/wizard/start\|answer\|skip\|draft\|revise`, `GET/PUT …/artifacts/{kind}`, `POST …/artifacts/{kind}/approve`; schemas `ChangeRequestResponse{change_request, current_step, question, question_options, job}`, `ChangeRequestSummary/ListResponse`, `Wizard{Start,Answer,Draft,Revise}Request`, `ArtifactUpdateRequest`, `ArtifactResponse`. Approve auto-starts the next step's `cr_questions` job. |
| `cli/cr.py` | `cr create\|list\|show\|draft [--auto] [--out]\|approve\|export [--version]\|delete`. |
| Frontend | `app/changes/page.tsx` (list + new), `app/changes/[id]/page.tsx` (stepper + chat + artifact panel), `components/{ChangeStagePill,ChangeStepper,ChangeChat,ArtifactPanel}.tsx`; `lib/api.ts`/`lib/types.ts` additions; nav **Changes**. |
| Tests | `tests/test_change_wizard.py` (BCR parsing, ids, round trips, store, engine flow with `ScriptedAnalyst`, splice guards), `tests/test_api_change_requests.py`, `tests/test_cli_cr.py`, `tests/test_change_fixtures.py`; fixtures `tests/fixtures/change_artifacts/{BCR-001-impact-analysis,EPIC-002,US-008-015-stories,TDD-ORD-002}.md` (live Nemotron output, approved). |
| Docs | `docs/HOW_IT_WORKS.md` §8d + §9.2/§9.3 rows, `docs/architecture.md` (change-request diagram), `README.md`, `CLAUDE.md`, `docs/kg-plan/RUNBOOK.md` (Phase 1 section). |

## What exists after Phase 2 (document export)

| Path | Role |
|---|---|
| `docs_export/docx_writer.py` | `DocxWriter` (python-docx) in the reference look: 22 pt bold `2F5496` title, 14 pt `444444` subtitle, `rule()` (bottom-bordered paragraph), `meta(label, value)`, `heading(text, 1..3)`, `paragraph`/`note`/`callout`, `bullet` (• numbering), `numbered` (real decimal numbering, restarts at 1), `checklist_item` (☑  /☐  ), `code_block`, `table(columns, rows)` (2F5496 header, tblHeader, FFFFFF body, 9500 dxa), `sources`, `bytes()`. Body font Times New Roman 10 pt (Word's fallback for the reference files). `parse_inline` → `Span`s (`` `code` `` → Consolas `AA3377`, `**bold**`, `*italic*`). |
| `docs_export/markdown_to_docx.py` | `parse_blocks` / `render_blocks` / `render_markdown(writer, md, heading_offset)` for our artifact grammar (headings, paragraphs, bullets, `1.` lists, checklists, pipe tables with `<br>`/`\|`, code fences, `>` notes, `**Label:** value`); `markdown_document(md, doc_type)` whole-document fallback. |
| `docs_export/xlsx_writer.py` | `TestCaseRow` (9 columns), `TestCaseSummary`, `TC_COLUMNS`, `TC_TYPES` (reference vocabulary order), `write_test_case_matrix(rows, summary) -> bytes` (sheets **Test Cases** + **Summary**, literal totals), `read_test_case_rows(bytes)` (first sheet whose header starts with `TC ID`). **Phase 4 renders the updated matrix with this writer.** |
| `docs_export/artifacts.py` | `export_impact/epic/story/stories/tdd(doc, *, label, approved)`, `export_test_case_preview(doc, existing, …)`, `preview_test_case_rows`, filenames (`impact_filename`, `epic_filename`, `story_filename`, `tdd_filename`, `stories_zip_filename`, `test_case_preview_filename`, `markdown_filename`; `-DRAFT` suffix when not approved), `export_label(artifact)`, `slugify`, `zip_bytes`, **`export_artifact(cr, kind, fmt) -> ArtifactExport{filename, media_type, data}`** (`docx` \| `md` \| `xlsx`; stories docx = zip of per-story documents; xlsx only for impact; `ValueError` on empty artifact / bad format). |
| `docs_export/bundle.py` | `export_change_request(cr, existing_test_cases=()) -> bytes` zip (`Impact-Analysis-BCR-001.docx`, `EPIC-002-<slug>.docx`, `US-00N-<slug>.docx` ×N, `TDD-ORD-002-<slug>.docx`, `TC-preview-BCR-001.xlsx`, `markdown/*.md`, `MANIFEST.txt`), `bundle_entries`, `manifest_lines`, `bundle_filename`. |
| `docs_export/package.py` | `stabilise_package(bytes)` — fixed zip-member timestamps + `dcterms:created/modified` so docx/xlsx are byte-deterministic. |
| `change/service.py` | `existing_test_cases(cr)` (every `*.xlsx` in the KB corpus through `read_test_case_rows`, never raises), `export(cr_id, kind, fmt)`, `export_bundle(cr_id)`; `kg/service.py::KgService.read_bytes(kb_id, rel_path)`. |
| `api/app.py` | `GET /change-requests/{id}/artifacts/{kind}/export?format=docx\|md\|xlsx`, `GET /change-requests/{id}/export.zip` (attachment, `Content-Disposition` CORS-exposed). |
| `cli/cr.py` | `cr export <cr-id> [STEP] --format md\|docx\|xlsx\|zip [--version N (md only)] [--out PATH]`. |
| Frontend | `components/ExportButtons.tsx` (`ArtifactExportButtons` on the artifact panel: `.docx` `.md` (+ `.xlsx` for impact); `ExportAllButton` in the wizard header), `lib/api.ts` `download()`/`saveDownload()`, `exportChangeArtifact`, `exportChangeRequestZip`. |
| Tests / fixtures | `tests/test_docs_export.py` (15), `tests/fixtures/change_artifacts/reference_headings.json` (digest §5 encoded), `tests/fixtures/change_artifacts/TDD-ORD-002.docx` (= `examples/change_requests/TDD-ORD-002.docx`, asserted identical to the render of `TDD-ORD-002.md`), API/CLI export tests. |
| Docs | `docs/HOW_IT_WORKS.md` §8e + CLI/route rows, `docs/architecture.md` (export diagram), `README.md`, `CLAUDE.md`, `RUNBOOK.md` Phase 2, screenshots `docs/kg-plan/screenshots/phase2-*.png`. |

Locked in Phase 2 (user decisions): unapproved artifacts **export, clearly labelled** (`DRAFT vN — not
approved` in subtitle + `Export:` meta line + `-DRAFT` filename); the KG appendix and Sources are
**always** in the docx; the stories `docx` export is **a zip of per-story documents**; the TC preview
**merges the KB's original matrix rows when available and falls back to impact-only rows**.

## What exists after Phase 3 (KG-grounded projects + change spec)

| Path | Role |
|---|---|
| `models/change_spec.py` | `ChangeSpec{components[ComponentChange{name, kind module\|activity\|workflow\|type\|signal\|query\|test\|diagram\|doc, path (KG node id / corpus file), existing, proposed, change_type modify\|add\|remove\|verify, requirement_ids, provenance}], assumptions[SpecItem], open_questions[SpecItem], sources[str], version}` (+ `component(name, kind)`, `unresolved_questions()`), `CHANGES_SLUG = "__changes__"`; LLM plans `ChangeSpecDraft/ComponentDraft`, `ChangeAnswerPlan/ComponentUpdate`. |
| `models/project.py` | `CompilationProject += kb_id, change_request_id, change_spec, grounding: ProjectGrounding{kb_name, change_request_title, sources, coverage, low_confidence, requirement_ids}`; `models/state.py` `WorkflowState.kg_context`. |
| `kg/grounding.py` | `KgGrounder(kg, kb_id, kb_name, budget=3000, max_hops=2)`: `context_for(text, budget) -> GroundingResult{block, sources, coverage, low_confidence, total_tokens, seeds}` (cached per text; never raises), `block_for`, `render(packet)`, `sources_seen`, `min_coverage`, `any_low_confidence`; `grounding_query(text)` (seed_terms first, then prose); block header *"KNOWLEDGE-GRAPH CONTEXT — prefer these real names / paths"*. `KgService.resolve_ref(kb_id, ref)` (node id / file path or suffix / `fn:` symbol / `fn:<file>:<method>` when the file defines it). |
| `prompts/` | `optional:` front-matter list (`Prompt.optional`, renderer defaults to `""`); `{{ kg_context }}` in `discover_workflows` (+ TDD hint), `discover_workflow`, `extract_facts`, `design_temporal`; new `extract_change_spec.md`, `interpret_change_answer.md`, `draft_change_questions.md`. |
| `agents/change_spec.py` | `ChangeSpecAgent(llm)`: `extract(document_text, kg_context, impact_table, seed_components, requirement_ids, sources)`, `to_spec` (kind/change coercion by word **and name**, dedupe, requirement filter, provenance, **every seed kept**, basename matching), `draft_questions`, `interpret_answer`; `change/spec_seed.py::seed_components(cr)` (impact `AffectedItem` rows + TDD Existing/Proposed texts). |
| `spec/change_renderer.py` ⇄ `spec/change_ingest.py` | `changes.md` grammar (`# Change Spec`, `## Grounding` ro, `## Components` `### name — kind, change [marker]` + `- path:`/`- requirements:` + `#### Existing`/`#### Proposed`, `## Assumptions`, `## Open Questions` (`- [ ] (ref) text [marker]` + `Answer:`), `## Sources` ro); `render_change_spec(spec, kb_id, kb_name, change_request_id, change_request_title)`, `ingest_change_markdown(spec\|None, md) -> ChangeIngestResult{spec, changes, warnings}` (identity round trip incl. provenance; merge by `kind:name`); `coerce_kind(value, name)`, `coerce_change_type`. |
| `spec/change_validator.py` | `validate_change_spec(spec, kg, kb_id, requirement_ids)` — empty Proposed → BLOCKING; unresolvable path → WARNING + `KgService.search` suggestions; unknown requirement id → WARNING; findings `workflow=__changes__`. |
| `dialogue/` | `change_ops.py` (`apply_component_updates`, `park_change_question`, `replace_change_spec`); `agenda.py` counts the change spec (`change_spec_has_anything_to_ask`, fingerprint); `engine.py` `DialogueEngine(change_agent=)`, `_answer_change` / `_dispose_change` / `_park_change`. |
| `project_compiler.py` | ctor `kg_service=`, `from_settings` builds a read-only `KgService`; `compile_document(..., grounder=None, change_request=None)` (grounded segmentation/facts, `_extract_change_spec`, `_record_grounding`); `grounder_for(project)`; `render_changes`, `spec_markdown` (all files incl. `__changes__`), `_fold_changes`, `_validate_changes`; `validate_specs`/`update_specs`/`approve_spec` handle `markdown_by_slug["__changes__"]`; approve refuses on BLOCKING change findings unless `accept_incomplete`; approve re-grounds each seeded state (`state.kg_context`); `write_spec_files`/`read_spec_files` include `changes.md`; overview lists it. |
| `api/` | `ProjectCompileRequest += kb_id, change_request_id`; `compile-upload` form fields `kb_id`, `change_request_id`; `_grounding_for` (CR implies KB; 422 mismatch; 409 unready KB); `_finish_compile` (owner, nickname, save, `ChangeRequestService.link_project`); `POST /change-requests/{id}/send-to-workflow` (`SendToWorkflowRequest{provider, model, nickname}`, 409 unless TDD approved, provider = wizard's else `KB_DEFAULT_PROVIDER`); `get_compiler_selector` dependency (tests override); every `spec_markdown` in responses = `ProjectCompiler.spec_markdown`. |
| `cli/main.py` | `compile … --kb <id> [--change-request <id>]` (links `project_ids`), `_project_compiler` wires `kg_service`, `_print_project` lists `changes.md`. |
| Frontend | `lib/types.ts` (`CHANGES_SLUG`, `ChangeSpec`, `ProjectGrounding`, project fields), `lib/api.ts` (`compileText/compileUpload(kbId, changeRequestId)`, `sendToWorkflow`), `app/page.tsx` KB selector, `app/changes/[id]/page.tsx` **Send to workflow GUI** + linked projects, `app/projects/[id]/page.tsx` (`GroundingBadge`, `ChangeSpecSummary`, `changes.md` under *Change spec*, diagram note, widgets hidden for changes), `components/SpecEditor.tsx` `grammar="spec"\|"changes"`, `lib/changesHighlight.ts`, `globals.css` `.cm-changes-*`, `SPEC_GUIDE.md` + guide page section *changes.md*, `spec-grammar.ts` strips markers in the Open-questions widget. |
| Tests | `tests/test_change_spec.py` (13), `tests/test_api_grounded_projects.py` (4); `MockProvider` demo defaults for `ChangeSpecDraft` / `ChangeAnswerPlan`. |
| Docs | `docs/HOW_IT_WORKS.md` §8f + CLI flags + route rows, `docs/architecture.md` (phase-3 diagram), `README.md` (phase 3), `CLAUDE.md`, `RUNBOOK.md` Phase 3, screenshots `docs/kg-plan/screenshots/phase3-*.png`. |

Locked in Phase 3 (user decisions, memory `kg-phase3-decisions`): send-to-workflow is **synchronous**;
the Resolve dialogue gives **full Q&A** on `changes.md`; a BLOCKING `changes.md` finding **refuses
approve unless `accept_incomplete`**; the change spec is extracted **whenever a KB is set**.

## What exists after Phase 4 (post-approval change outputs)

| Path | Role |
|---|---|
| `change_outputs/models.py` | `ChangeOutputs{diagrams[UpdatedDiagram{name, kind state\|sequence\|architecture\|state-partial\|workflow, original, updated, notes, source_path, checks}], code: CodeChangeBundle{files[ChangedFile{path, status modified\|added\|removed\|unchanged, original, updated, unified_diff, checks{ast_ok, ast_error, ruff_ok?, ruff_output, repaired, truncated}, reason, notes}], order, import_root, code_root}, tests_doc: TestDocUpdate{test_cases[TestCaseRow], changed_ids, new_ids, test_plan_addendum_md, linked_tdd, linked_epic, test_plan_id, change_request_id, matrix_source, notes}, system_flow_md, provenance, warnings, timings, stages{name: StageRecord{status, error, seconds, finished_at, provider, model}}, generated_at}` (content models keep whitespace verbatim); `STAGES = (diagrams, code, tests_doc)`; LLM plans `DiagramUpdatePlan/DiagramDraft`, `TestCaseUpdatePlan/TestCaseDraft/TestCaseUpdate/TestPlanAddendumDraft` (tolerant: stray non-object list items dropped). Stored on `CompilationProject.change_outputs`. |
| `change_outputs/code.py` | Deterministic code stage: `plan_rewrites(spec, texts) -> RewritePlan{order, unchanged, reasons, components_by_file, imports, import_root, code_root}` (component `path`/`name` → corpus `.py` via node ids / suffixes, case-insensitive; empty-path activity/signal/query/type → activities/workflow/types module, never `__init__`; + every file importing a rewritten module; topological order, ties by category types 0 → activities 1 → workflow 2 → worker 3 → starter 4 → tests 5), `resolve_component_file`, `resolve_import` (`src.shared.types` ↔ `existing_Codebase/shared/types.py`), `import_root_of`, `extract_code`/`continue_code` (fence protocol), `check_syntax`, `ruff_check` (F,E9), `unified_diff`, `signature_summary`, `defined_names`/`exported_names`, `missing_symbols`, `missing_imports` (sibling coherence), `dataclass_problems`, `KNOWN_IMPORTS` + `corpus_exports` + `auto_import`, `undefined_names`. |
| `change_outputs/diagrams.py` | `plan_diagrams(spec, corpus_files) -> [DiagramRequest]` (every `.mmd` + spec-added companions), `mermaid_header`, `states_in`, `balanced`, `expected_states(spec, original_states)` (multi-segment UPPER_SNAKE tokens from type/diagram/workflow/module components), `check_diagram`, `diagram_kind_of`, `assemble_system_flow(original_md, diagrams, workflow_diagrams, change_title)` (original numbered H2s → spec diagram section (D10) → new companions). |
| `change_outputs/tests_doc.py` | `next_tc_ids`, `normalise_type/automated`, `merge_test_cases(existing, new, updates, start_hint, change_note) -> (rows, changed_ids, new_ids)` (updates never drop; notes appended; duplicate titles skipped), `render_addendum` (numbered H2 markdown, `**Label:** value` meta), `parse_addendum_meta`, `export_addendum_docx` (title *Test Plan — Addendum*, reference look), `export_matrix_xlsx` (Phase 2 writer + Summary), `addendum_filename`, `linked_ids_from_text`. |
| `change_outputs/engine.py` | `ChangeOutputsEngine(agent, kg, load_state=, build_diagrams=, grounder=, provider_name=, model_name=)`: `run(project, stages, progress, persist)` — `_prepare` (corpus files, `changes.md` render, `design_summary(designs)`, spec excerpt, TDD excerpt 24 k chars, KG grounding block + sources), `_run_diagrams` (plan → agent → `check_diagram` → one repair round → workflow diagrams → flow doc), `_run_code` (texts → `plan_rewrites` → per file: prompt with sibling signatures → `rewrite_file` → syntax / dataclass / symbols / sibling-import / ruff checks → one `repair_file` → `auto_import` → diff; persists after every file), `_run_tests_doc` (matrix via `read_test_case_rows`, TP docx text, rewritten tests outline, catalog ids → agent → merge → addendum); `ChangeOutputsError` after all stages when any failed; `change_label_of(project)`. |
| `change_outputs/export.py` | `export_zip(outputs, project_id, label)` (README layout `src/`, `tests/`, `docs/diagrams/mermaid/*.mmd`, `docs/diagrams/system-flow-diagram.md`, `docs/test-cases/<matrix>.xlsx` + `<TP>-addendum-<BCR>.docx/.md`, `changes.patch`, `CHANGES.md`; byte-stable), `export_entries`, `changes_index`, `combined_patch`, `zip_code_path`, `export_filename`. |
| `agents/change_outputs.py` | `ChangeOutputsAgent(llm, file_max_tokens=8192)`: `update_diagrams(...) -> DiagramUpdatePlan` (structured), `rewrite_file(...) -> RewriteResult{code, found, truncated, closed}` (`complete` + fence + ≤2 continuations), `repair_file(path, code, error) -> FencedCode`, `update_test_cases(...) -> TestCaseUpdatePlan`. Prompts `update_diagrams.md` (companion = composite `state PARTIALLY_* { … }`), `rewrite_source_file.md`, `continue_source_file.md`, `repair_source_file.md`, `update_test_cases.md`. |
| `project_compiler.py` | `generate_change_outputs(project_id, stages=None\|["all"\|…], progress, persist, project=, change_label=)` (needs `kb_id` + compiled workflow; saves after each stage/file; records `stage_timings["change_outputs"]`), `change_outputs_engine(project)`, `approve_spec(..., change_outputs=False)` (inline chain for the CLI), `_provider_label`; `compile_document` records `grounding.change_request_label = cr.bcr_meta.doc_id`. `models/project.py`: `CompilationProject.change_outputs`, `ProjectGrounding.change_request_label`. |
| `api/` | `JobKind += change_outputs`; `POST /projects/{id}/jobs` (approve) chains `_start_change_outputs` via `after` **on the cloud default provider** (`KB_DEFAULT_PROVIDER` through `get_compiler_selector`) once the project is `completed`; `GET /projects/{id}/change-outputs` → `ChangeOutputsResponse{project_id, outputs, job, available}`; `POST …/change-outputs/regenerate` `ChangeOutputsRegenerateRequest{stage: all\|diagrams\|code\|tests_doc, provider?, model?}` (202 / 409 / 422); `GET …/change-outputs/export.zip`; `GET …/change-outputs/files/{test-cases.xlsx\|test-plan-addendum.docx\|test-plan-addendum.md\|system-flow-diagram.md\|changes.patch}`; `_change_label` reads the CR's `bcr_meta.doc_id` for projects compiled before the label was stored; job progress `message/done/total` per stage. |
| `cli/main.py` | `approve-spec … --change-outputs` (bundle unpacked under `<out-dir>/<project-id>/change-outputs/`), `change-outputs <project-id> [--stage all\|diagrams\|code\|tests_doc] [--out-dir] [--provider] [--model] [--timeout 400]` (exit 1 when a stage failed, outputs still written), `_write_change_outputs`, `_print_change_outputs`. |
| `llm/providers/mock.py` | demo defaults for `DiagramUpdatePlan` and `TestCaseUpdatePlan`; `complete` returns `mock-response` (→ files `unchanged` with a warning) unless completions are queued. |
| Frontend | `components/ChangeOutputsView.tsx` (stage pills, Regenerate `<select>` + button, Download all, warnings, Sources; `DiagramsPanel` (chips, Updated/Original, checks, source), `CodePanel` (file list + status/ast/ruff pills, `UnifiedDiff` from `unified_diff`, `SplitDiff` via `diff.diffLines`, updated file, `changes.patch`), `TestCasesPanel` (table with new/updated tones, only-changed filter, `.xlsx` / addendum `.docx`, addendum markdown)); `ResultsView.tsx` **Workflows \| Change outputs** switch for grounded projects; `lib/types.ts` (`ChangeOutputs…`, `JobKind += change_outputs`), `lib/api.ts` (`changeOutputs`, `regenerateChangeOutputs`, `exportChangeOutputsZip`, `changeOutputFile`), `lib/runs.tsx` (label/toast/invalidation), `app/projects/[id]/page.tsx` (no overlay for the change_outputs job), `globals.css` `.diff-add/.diff-del`; dependency `diff@^8` (+ `@types/diff`). |
| Tests | `tests/test_change_outputs.py` (16), `tests/test_api_change_outputs.py` (2, incl. CLI). |
| Docs | `docs/HOW_IT_WORKS.md` §8g + CLI/route rows, `docs/architecture.md` (phase-4 diagram), `README.md`, `CLAUDE.md`, `RUNBOOK.md` Phase 4, screenshots `docs/kg-plan/screenshots/phase4-*.png`. |

Locked in Phase 4 (user decisions, memory `kg-phase4-decisions`): rewrite set = change-spec files **+
import dependents**; export zip in the **README layout** (`src/`, `tests/`, `docs/`); TP deliverable =
**addendum docx** (original untouched); live verification = regenerate on `d64a03d8…` **and** one
fresh Send-to-workflow → gate → approve → chained outputs; file rewrites via **fenced `complete()`**
with continuation + one repair round; chaining = **separate follow-on job**; Results UI =
**Workflows | Change outputs** sub-view switch.

## What exists after Phase 5 (hardening, docs, demo)

| Path | Role |
|---|---|
| `storage/ids.py` | **Store-boundary guards shared by every file store**: `is_safe_id` / `validate_store_id` (`[A-Za-z0-9_-]{1,128}` → else `StateNotFoundError`), `validate_slug` (bundle / spec dirs), `stored_version(path)` (JSON `version`, legacy = 0), `next_version(current, expected, label, key)` (CAS arithmetic → `StaleWriteError`). Wired into `storage/{file,project_store,user_store,change_store}.py`, `kg/store.py` (`validate_kb_id` / `validate_cr_id` now delegate) and `execution/bundles.py::bundle_dir`. |
| `exceptions.py` | `StaleWriteError(WorkflowCompilerError)` — mapped to **409** by `api/app.py::_guard`. |
| `models/project.py`, `kg/models.py`, `models/change.py` | `version: int = 0` on `CompilationProject`, `KnowledgeBase`, `ChangeRequest` — the store bumps it on **every** save; `save(obj, *, expected_version=None)` on every store protocol + implementation (file and in-memory). CAS is **opt-in** (decision, memory `kg-phase5-decisions`): no token = last-write-wins. |
| `project_compiler.py`, `change/service.py` | `update_specs(..., expected_version=)`, `save_project(project, expected_version=)`, `ChangeRequestService.edit(..., expected_version=)` / `_save(cr, expected_version=)`; ctor knobs `change_outputs_repair_rounds` / `change_outputs_smoke` / `change_outputs_smoke_python` (from `Settings` in `from_settings`), passed to `ChangeOutputsEngine`. |
| `api/app.py`, `api/schemas.py` | `expected_version?` on `SpecUpdateRequest`, `RenameProjectRequest`, `ArtifactUpdateRequest`; `If-Match` header (`"N"`, `W/"N"`, `N`, `*` = skip, non-integer → 400) via `_expected_version`; `ETag: "N"` on `GET /projects/{id}`, `/knowledge-bases/{id}`, `/change-requests/{id}` and on the write responses; `version` on `ProjectSummary` / `KnowledgeBaseResponse`; scrypt `hash_password` / `verify_password` in `asyncio.to_thread`; the change-outputs export zip name prefers the BCR business id. |
| `docs_export/artifacts.py::safe_filename_part` | `[A-Za-z0-9._-]` reduction for document/model-derived filename parts; used by `change_outputs/export.py::export_filename`, `tests_doc.py::addendum_filename`, `docs_export/bundle.py::bundle_filename`. |
| `change_outputs/code.py` | `normalise_style(original, updated) -> (text, changed)` (keep-style: PEP 585/604 generics + `from typing import` trim, two blank lines between top-level blocks, EOF newline — only when the original followed the rule; re-parsed), `describe_syntax_error(code, err)` (offending line ±3 with numbers + the *def-inside-a-list* hint), `late_annotation_names(code)` (names in `@workflow.query/signal/run` / `@activity.defn` annotations defined only below the class or only under `TYPE_CHECKING` — Temporal evaluates hints at import). |
| `change_outputs/smoke.py` | `run_smoke(bundle, python="", timeout=180) -> SmokeResult` (export layout in a temp dir → one child interpreter: `py_compile` every file, import every module in bundle order → JSON verdict; never raises: `skipped` with a note when the interpreter cannot start), `bundle_layout`, `module_names`. |
| `change_outputs/models.py` | `FileChecks += repair_rounds, problems[], style_normalised`; `SmokeResult{status passed\|failed\|skipped, python, compiled, compile_errors, modules, imported, import_errors, seconds, note}`; `CodeChangeBundle.smoke`. |
| `change_outputs/engine.py` | ctor `repair_rounds=2, smoke=True, smoke_python=""`; `_diagnose(code, required, rewritten, texts, closed)` runs every deterministic check (syntax with context, dataclass, symbols, sibling imports incl. nested `with`/`try` blocks, late annotations, ruff) and renders **all** failing verdicts (numbered) for the repair prompt; `_run_code` loops repair rounds (`FileChecks.problems` records each), auto-imports after each round, applies `normalise_style`, records warnings per outcome, then `run_smoke` → `bundle.smoke` (+ warning) and persists. |
| `prompts/templates/rewrite_source_file.md` | rule 8 pins the Temporal Python SDK surface (`@activity.defn` takes no `retry_policy`; `RetryPolicy` on `execute_activity`; no new `str`-Enum result fields; test-double / `WorkflowEnvironment` forms; helpers must exist with the signature the tests use). |
| `config.py`, `metrics.py` | `change_outputs_repair_rounds` (2), `change_outputs_smoke` (True), `change_outputs_smoke_python` (""), `baseline_hours["change_outputs"] = 16.0`; `metrics.py` buckets `stage_timings["change_outputs"]` (label *Change outputs (diagrams, code diff, test docs)*). |
| `scripts/reset_demo_state.py` | dry-run-by-default reset of KBs / CRs / projects (+ workflow states), `--yes` (backup zip first), `--keep <id>`, `--only`, `--generated`, `--no-backup`. |
| Frontend | `lib/api.ts` (`saveSpec` / `renameProject` / `updateChangeArtifact` take `expectedVersion`), `lib/types.ts` (`version?`, `FileChecks` fields, `SmokeResult`, `CodeChangeBundle.smoke`), `app/projects/[id]/page.tsx` (sends the version, 409 → *Reload the latest version*), `components/ProjectsPanel.tsx`, `components/ArtifactPanel.tsx` (`crVersion`, 409 hint), `components/ChangeOutputsView.tsx` (`SmokeCard`, `repaired ×N` / `style kept` pills, repair-verdict list, 409 hint on Regenerate), `app/guide/page.tsx` + `SPEC_GUIDE.md` (*Change outputs* + CAS section). |
| Tests | `tests/test_hardening.py` (11), `tests/test_api_change_requests.py::test_artifact_put_honours_expected_version`, `tests/test_change_outputs.py` (+8: `normalise_style`, smoke verdicts, second repair round + smoke, `repair_rounds=0`, time-saved bucket, `describe_syntax_error`, nested-import coherence, `late_annotation_names`). |
| Docs | `docs/HOW_IT_WORKS.md` (§8c–§8g *Change pipeline map* banner, §7.3 store guards + CAS, §8g repair rounds / keep-style / smoke / config, route rows with `ETag` / `expected_version` / `If-Match`), `docs/architecture.md` (*The business-change pipeline end to end* — component + sequence diagrams, hardening note), `README.md` (*Business change pipeline — end to end*), `CLAUDE.md` (architecture essentials consolidated into one five-engine bullet + a store-guards/CAS bullet), `docs/kg-plan/RUNBOOK.md` (*Demo script* section + Phase 5 results), this file. |

Locked in Phase 5 (user decisions, memory `kg-phase5-decisions`): CAS **opt-in**; the demo pass runs
from a **fresh KB + CR**; the reset recipe is **document-only** (nothing deleted this session);
`feat/live-diagram` is merged **only if every gate is green** (it is a real 3-way merge).

## Ids / facts a follow-up will need

- **Phase 5 demo pass (fresh, on this machine, `.workflow_state/`)**: KB
  `4fc250d8b4cf4f3bbcb0fdcba0ec95fc` (*Order lifecycle (Existing_KG) — Phase 5 demo*, 394 nodes,
  3 files skipped by enrichment — *Reindex + enrich* fills them), CR `61087a8b847c4d67b0f708378fff4c2a`
  (BCR-001, complete, `project_ids = [41cec612…]`), project **`41cec612-b4b5-45c9-94d0-4678de821283`**
  (COMPLETED without `accept_incomplete`; `change_outputs` all three stages done, code stage re-run
  once with the nested-import fix — see RUNBOOK Phase 5 for the smoke / pytest verdicts).
- **Reference state kept from earlier phases**: KB `86d9919378bd4ebe8329f8ff950a2a27`, CR
  `dfad0d257db847919029f11dbef3c47d`, projects `d64a03d8…` (code stage re-run in Phase 5 with the
  second repair round + smoke) and `76bdad1c…`. Nothing was deleted (decision); the reset recipe is
  `scripts/reset_demo_state.py` (dry run by default).
- **Drivers / logs**: `%LOCALAPPDATA%\Temp\claude\…\13185e58-…\scratchpad\pw\phase5.mjs` (+ `kb_ask.mjs`,
  `state.json` cookies, `*.log`), `…\c9a65f4d-…\scratchpad\{live_regen*.log,json, p5_run1/, p5_demo/}`
  (bundles + `pytest.log`), scratch venvs `tvenv` (py 3.12, temporalio 1.20) / `tvenv311`.
- **Servers**: this worktree on `127.0.0.1:8010` / `:3010`; on Windows start them with
  `Start-Process` (a shell that exits kills its children); the demo worktree holds 8000/3000.

## Ids / facts Phase 5 needed (kept for reference)

- **Live projects with change outputs** (`.workflow_state/projects/`): `d64a03d8-939d-425a-b649-8816dce80ff3`
  (three code re-runs, see RUNBOOK Phase 4) and **`76bdad1c-558d-4454-b4e6-27fe38e5006b`** (fresh
  send → gate → approve → chained outputs; diagrams re-run after the plan fix; label `BCR-001`).
  Both hold `change_outputs` with all three stages `done`; `cr.project_ids` of `dfad0d25…` now lists
  `f64d88c4…, d64a03d8…, 76bdad1c…`.
- Bundles / logs of every live run: `%LOCALAPPDATA%\Temp\claude\…\13185e58-…\scratchpad\{run1,run2,run3,fresh}` and
  `live_regen*.log`; scratch venvs `tvenv` (py 3.12, temporalio 1.20) / `tvenv311` for running generated tests.
- The corpus's own tests fail 4/4 in a fresh venv (str-Enum decode through temporalio's default
  converter) — any "generated tests pass" claim must be measured against that baseline.

## Ids / facts Phase 4 needed (kept for reference)

- **Live projects** (`.workflow_state/projects/`, this machine): `d64a03d8-939d-425a-b649-8816dce80ff3`
  — sent from CR `dfad0d257db847919029f11dbef3c47d`, **COMPLETED** (approved with `accept_incomplete`,
  graph health 0.95, workflow state `0b5e0676-0eff-4ced-a7c0-35f313e1adc3` with `temporal_design`,
  7 generated files and `kg_context`), `change_spec` v2 with 39 components incl. KG node ids
  (`mod:existing_Codebase/workflows/order_workflow.py`, `fn:existing_Codebase/shared/types.py:OrderState`,
  `doc:Business_Docs/diagrams/mermaid/order-state-machine.mmd`, …) — the natural Phase 4 input;
  `9fd540d5-c345-4bd1-a7ed-5d2d6625c909` (home-page upload, KB only, spec drafted);
  `f64d88c4-b6e7-4529-9471-4dbc56f2c61b` (first send, 10-component change spec, spec drafted).
- `project.change_spec.components[*].path` is a KG node id or corpus path — resolve with
  `KgService.resolve_ref` / `read_file`; `project.grounding.sources` lists the spans the prompts saw;
  `project.kb_id` / `change_request_id` are set on every grounded project; `ProjectCompiler.grounder_for(project)`
  gives a ready grounder for the diagram / code-rewrite prompts.
- The workflow spec's `state_transitions` for a TDD are descriptive (R9) and were deleted at the gate
  in the live run — Phase 4's diagram stage should take states from the change spec + the original
  `.mmd`, not from the spec graph.
- The KB corpus files Phase 4 rewrites: `existing_Codebase/{shared/types.py, activities/order_activities.py,
  workflows/order_workflow.py, worker.py, starter.py}`, `tests/test_order_workflow.py`,
  `Business_Docs/diagrams/mermaid/{order-state-machine,order-sequence,system-architecture}.mmd`,
  `Business_Docs/diagrams/system-flow-diagram.md`, `Business_Docs/test-cases/TC-order-workflow.xlsx`,
  TP docx; catalog `next_test_case` = TC-18 (CR `ids`).
- Live KB `86d9919378bd4ebe8329f8ff950a2a27`; CR `dfad0d257db847919029f11dbef3c47d`
  (`project_ids` = `[f64d88c4…, d64a03d8…]`).

## Ids / facts Phase 3 needed (kept for reference)

- **Phase 3 input:** `examples/change_requests/TDD-ORD-002.docx` (identical to
  `tests/fixtures/change_artifacts/TDD-ORD-002.docx`) — upload it via the home page with the KB
  selected, and once via the future "Send to workflow GUI" button. Its text (Word) starts with the
  22 pt "Technical Design Document (TDD)" title, then the metadata block (`Document ID: TDD-ORD-002`,
  `Linked EPIC: EPIC-002`, `Supersedes: TDD-ORD-001`, …, `Export: Approved v2 (2026-08-18)`), then
  `1. Overview` … `8. Open Items / Future Work` each with `Existing` / `Proposed` (Heading 3), a
  `Diagrams Needed` section and a `Sources` section — the existing `.docx` ingestion
  (`workflow_compiler.ingestion`) reads it as plain paragraphs, so the segmentation prompt will see
  "Existing"/"Proposed" as ordinary lines. The markdown twin is `TDD-ORD-002.md` (same content, `###
  Existing`/`### Proposed`) if md ingress is easier for the change-spec extractor.
- Live KB `86d9919378bd4ebe8329f8ff950a2a27`; live CR `dfad0d257db847919029f11dbef3c47d` (all four
  artifacts approved; `ids`: EPIC-002, US-008…US-015, TDD-ORD-002, next TC TC-18) — both under
  `.workflow_state/` on this machine; the CR page's Export buttons and `cr export` produce the files
  in the RUNBOOK's Phase 2 table.
- The impact analysis' `AffectedItem` rows (kind/ref/change_type/rationale/kg_ref) are the natural
  seed of Phase 3's `ChangeSpec.components` (`parse_impact(cr.artifacts.impact.markdown).affected`);
  `TddDoc.sections[*].existing/proposed` per `TDD_SECTIONS` key are the existing-vs-proposed text.
- Provider factory / KgService / ChangeRequestService wiring is unchanged from Phase 1 (below).


- Live KB `86d9919378bd4ebe8329f8ff950a2a27` (enriched, 401 nodes); live CR
  `dfad0d257db847919029f11dbef3c47d` (BCR-001, stage `complete`, all four artifacts approved) and a
  CLI validation CR `2c598c9ee4684eb4be13d6df3ae03e5f` — both under `.workflow_state/change_requests/`
  on this machine. The fixtures under `tests/fixtures/change_artifacts/` are the Phase 2 inputs.
- Artifact markdown grammar (for the docx converter): see `change/render.py` — the H1 is
  `<Doc type/ID> — <subtitle>`, metadata lines are `**Label:** value`, sections H2 (`## N. Title` for
  impact/TDD, unnumbered for EPIC, `## US-00N: Title` per story with H3 subsections), tables are pipe
  tables with `<br>` for line breaks and `\|` for pipes, checklists `- [ ]`/`- [x]`, TDD parts are
  `### Existing` / `### Proposed` (H4 under 4.x), the Sources footer is a bullet list of backticked
  paths. `change/parse.py` yields the structured docs (`ImpactDoc`, `EpicDoc`, `StoriesDoc`, `TddDoc`)
  — the docx/xlsx writers should consume those, not re-parse markdown themselves.
- Reference docx conventions: `research/reference-repo-digest.md` §5 (22 pt bold doc type, 14 pt
  subtitle, bold `Label: value` block, Heading 1/2, List Paragraph bullets, `2F5496` header shading,
  `☑ `/`☐ ` checklists, Consolas inline code; numbered headings for BRD/TDD/TP/BCR, unnumbered for
  EPIC, H2-only for US docs).
- (from Phase 1) Provider factory `(provider_name | None, model | None) -> BaseLLMProvider`; the API's is
  `api/dependencies.py::kb_provider_factory` (also used by `get_change_service`), the CLI's wraps
  `_build_provider`.

## Open issues / notes

- (Phase 5) **Still no generated test suite ran green — but the demo project's final bundle imports
  end to end (smoke 11/11)**; failures are now *reported before the download*: the bundle smoke test
  (compile + import in a child interpreter) named the exact module each time and pytest in `tvenv`
  confirmed it (RUNBOOK Phase 5: per test 0 pass · 4 fail · 2 hang — two baseline-class str-Enum
  failures, two generated-test slips, two hangs where the test signals the order-level
  `delivery_confirmed` while the workflow waits per group). Remaining model-quality items:
  a syntax slip a long test module can keep after two repair rounds (the verdict now carries the
  lines + a hint — measure on the next run), and Nemotron sometimes rewriting an existing diagram
  coarser than the original (flagged by the required-states check, original kept). Ideas not
  built: a third, *test-only* repair round that also runs the smoke import per file; a "restore
  original" button per file/diagram; running the smoke in `tvenv` by default
  (`change_outputs_smoke_python`).
- (Phase 5) The `change_spec` step buckets under *discovery* in the time-saved card (its
  `stage_timings` key is `change_spec`; only `change_outputs` got its own key by request).
- (Phase 5) A change spec can name a *new* diagram file (`updated-system-architecture.mmd`); the
  validator WARNs (not in the KB) and the diagram stage asks the model for it as a companion — the
  model may return nothing (flagged). Fine for review; a hand edit of `changes.md` removes it.
- (Phase 5) `regenerate` while another job runs still answers 409 by design (one run per project);
  the UI now says so next to the button.

- (Phase 3) `validate` still strips the human `- triggers:` metadata line (pre-existing OPEN defect,
  memory `llm-timeout-and-trigger-stripping-defects`); the live approve needed `accept_incomplete`.
- (Phase 3) A TDD's State Transitions become orphan state nodes in the graph (health 0.25) although
  R9 marks them descriptive — deleted at the gate in the live run; candidate fix: skip state nodes
  once R9 is confirmed.
- (Phase 3) The Approve-overrides card is only visible while the buffers are dirty; after a clean
  validate the override cannot be ticked in the UI (sent through `POST /projects/{id}/jobs` here).
- (Phase 3) Opening the Resolve tab starts `predraft`; clicking *Start resolving* before it finishes
  drafts the agenda a second time (11.8 min for 7 questions live).
- (Phase 3) `WorkflowFacts` has no signal/query category — `get_status` lives only in `changes.md`
  (and reaches the Temporal design through the grounded prompt); `complete_order` is named
  `consolidate_complete` by the Phase-1 TDD.
- (Phase 3) `order-sequence.mmd` / `system-architecture.mmd` are not in `changes.md` because neither
  the TDD nor the approved impact analysis names them; Phase 4 regenerates all three by decision D10
  regardless.

- Nemotron sometimes re-asks a decision already recorded (the brief lists cumulative decisions and
  the prompt forbids it, but it is not enforced deterministically). Answer consistently or skip.
- Revisions: the model still elides long tables — the table-merge guard means a revision can add
  rows but never delete them; deleting is a hand edit. Whole-document `Revision.markdown` is still
  accepted as a fallback when the model returns no sections.
- The KG appendix in the impact analysis lists node *names* (no ids) — the brief's traversal table
  has ids; the docx export may want the appendix as an optional annex.
- The frontend hides Edit/Revise for approved artifacts; the API allows editing an approved artifact
  (it flips back to `drafted` and must be re-approved). Exports render the *latest* version and label
  it `DRAFT vN — not approved` until re-approved (decision recorded above).
- Export cosmetics still open (none blocking): story filenames truncate long titles at 40 chars
  (`US-008-split-order-into-shipment-groups-based.docx`); the Summary sheet uses literal totals
  instead of `COUNTIF`; the KG appendix table (86 rows) makes the impact docx 3–4 pages longer than
  the reference BCR — kept by decision.
- `npm run lint` has 2 pre-existing `react-hooks/set-state-in-effect` findings (`RunPanel`,
  `SpecChatPanel`) untouched by Phases 0–2.
- The 2026-08-14 audit P0s (id sanitisation) are handled for both new stores; CAS-on-save remains
  for Phase 5.

## Phase log
- **Phase 5 — 2026-08-19 — done.** Commits on `feat/kg-change-pipeline`: store-boundary guards +
  opt-in CAS + scrypt off the loop (+ tests) → repair rounds / smoke test / keep-style / prompt pin /
  baseline key (+ frontend CAS) → frontend smoke card + guide → reset script → docs (HOW_IT_WORKS,
  architecture, README, CLAUDE.md) → syntax verdict context → export label → nested-import coherence
  → mermaid error suppression → late-annotation check → `feat/live-diagram` merged (3-way, frontend
  only, additive conflicts) → smoke-warning prefix → RUNBOOK demo script + Phase 5 results + HANDOFF. Gates: pytest **718
  passed** (699 + 19 new), ruff clean, mypy strict clean (191 files), `npm run build` clean; live on
  Nemotron: code re-run on `d64a03d8…` (1233 s) + one full demo pass (+ three code re-runs on the demo
  project, the last with a passing bundle smoke) KB → CR → wizard → export →
  send → gate → approve → chained outputs on `4fc250d8… / 61087a8b… / 41cec612…` with screenshots
  `docs/kg-plan/screenshots/phase5-*.png`; generated-test results recorded honestly.
- **Phase 4 — 2026-08-19 — done.** Commits on `feat/kg-change-pipeline`: WIP (models / code / diagrams /
  tests_doc / engine / export, agent + prompts, `generate_change_outputs`, job kind + routes) → CLI +
  mock defaults + tests → frontend Change outputs view + per-file downloads → docs → deterministic
  auto-import + no `__init__` targets → BCR label on the grounding record → sibling-import coherence
  → dataclass check → tolerant plans → cloud default for the chained job + corpus-aware auto-import →
  RUNBOOK / HANDOFF. Gates: pytest 699 passed (681 + 18 new), ruff clean, mypy strict clean (189
  files), `npm run build` clean; live runs on Nemotron: regenerate on `d64a03d8…` (1453 s), fresh
  send → gate → approve → chained outputs on `76bdad1c…`, three code re-runs; screenshots in RUNBOOK.
- **Phase 0 — 2026-08-17 — done.** Commits: plan docs → vendoring → kg core → API/CLI/examples →
  frontend → mypy-clean + docs → runbook/handoff. Gates: pytest 620 passed, ruff clean, mypy strict
  clean, `npm run build` clean; live UI upload + Nemotron enrichment recorded in RUNBOOK.
- **Phase 1 — 2026-08-18 — done.** Commits on `feat/kg-change-pipeline`: backend core (models, bcr,
  ids, render/parse, agent + prompts, engine, service, store) → API routes + jobs + CLI + tests →
  retrieval tuning + docs → impact coverage pass → business-id glossary → frontend → cumulative
  decisions → TDD depth prompt → section-scoped revision + table-merge guard → fixtures + runbook +
  handoff. Gates: pytest 646 passed (620 + 26 new), ruff clean, mypy strict clean (166 files), `npm run
  build` clean; live browser run on Nemotron recorded in RUNBOOK with screenshots; BCR-001 artifacts
  saved as fixtures.
- **Phase 2 — 2026-08-18 — done.** Commits: docs_export core + API + CLI + tests → frontend Export
  buttons → reference-look polish + CORS filename + TDD-ORD-002.docx fixture + docs → RUNBOOK →
  handoff. Gates: pytest 664 passed (646 + 18 new), ruff clean, mypy strict clean (173 files), `npm
  run build` clean; live UI export of CR `dfad0d25…` + Word/Excel side-by-side screenshots in RUNBOOK.
- **Phase 3 — 2026-08-18 — done.** Commits: WIP (model/renderer/ingest/validator/grounder/agent/prompts)
  → ProjectCompiler wiring + `__changes__` dialogue + API/CLI + tests → frontend → docs → seed-keeping
  + per-signal/query prompt → kind-by-name → `resolve_ref` methods → RUNBOOK/HANDOFF. Gates: pytest
  681 passed (664 + 17 new), ruff clean, mypy strict clean (181 files), `npm run build` clean; live
  runs on Nemotron: home-page upload with KB (338 s), Send to workflow GUI (223 s / 212 s), validate →
  resolve → approve to COMPLETED on `d64a03d8…`, screenshots in RUNBOOK.
