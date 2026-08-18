# KG change pipeline — handoff

**Current phase:** Phase 1 **complete** (2026-08-18). Next: Phase 2 (document export — `.docx` /
`.xlsx` in the manager's template style) — read `KG_CHANGE_PIPELINE_PLAN.md` §0 + Phase 2, then this
file, then `RUNBOOK.md`, then `research/reference-repo-digest.md` §5 (the docx/xlsx conventions).

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

## Ids / facts Phase 2 will need

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
- Provider factory `(provider_name | None, model | None) -> BaseLLMProvider`; the API's is
  `api/dependencies.py::kb_provider_factory` (also used by `get_change_service`), the CLI's wraps
  `_build_provider`.

## Open issues / notes

- Nemotron sometimes re-asks a decision already recorded (the brief lists cumulative decisions and
  the prompt forbids it, but it is not enforced deterministically). Answer consistently or skip.
- Revisions: the model still elides long tables — the table-merge guard means a revision can add
  rows but never delete them; deleting is a hand edit. Whole-document `Revision.markdown` is still
  accepted as a fallback when the model returns no sections.
- The KG appendix in the impact analysis lists node *names* (no ids) — the brief's traversal table
  has ids; the docx export may want the appendix as an optional annex.
- The frontend hides Edit/Revise for approved artifacts; the API allows editing an approved artifact
  (it flips back to `drafted` and must be re-approved) — Phase 2's export should only export
  approved versions (or the latest, clearly labelled).
- The 2026-08-14 audit P0s (id sanitisation) are handled for both new stores; CAS-on-save remains
  for Phase 5.

## Phase log
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
