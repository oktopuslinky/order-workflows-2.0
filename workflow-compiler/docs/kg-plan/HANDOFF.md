# KG change pipeline — handoff

**Current phase:** Phase 0 **complete** (2026-08-17). Next: Phase 1 (change request + guided
wizard) — read `KG_CHANGE_PIPELINE_PLAN.md` §0 + Phase 1, then this file, then `RUNBOOK.md`.

**Worktree:** `C:\Users\devag\Documents\Code (local)\order-workflows-kg`, branch
`feat/kg-change-pipeline` (from `demo/dialogue-plus-run` @ `0a6e84d`). It now has its own
`.venv` (Python 3.12, `pip install -e ".[dev]"`), a `.env` copied from the demo worktree, and
`frontend/node_modules`. Live servers for this worktree run on **127.0.0.1:8010 / :3010** (see
RUNBOOK bring-up — the demo worktree holds 8000/3000).

## What exists after Phase 0

Backend (`src/workflow_compiler/`):

| Path | Role |
|---|---|
| `kg/contexthub/` | Vendored Context Hub subset (`model`, `bootstrap`, `retrieval`, `identity.py`, `paths.py`) @ `0447cad`; 10 local edits listed in `kg/contexthub/VENDORED.md` (injectable JSON-chat client + progress hook, POSIX ids, `.pdf` via `workflow_compiler.ingestion`, `BR`/`BCR` id families, utf-8 store). mypy `ignore_errors`; ruff style rules relaxed for this dir only. |
| `kg/models.py` | `KnowledgeBase{kb_id,name,owner_id,root_dir,source,status,error,stats{nodes,edges,by_type,edges_by_type,files},indexed_at,llm_enriched,provider_used,model_used,catalog{epics,stories,test_cases,requirements},warnings,…}`, `KgPacket/KgSection/KgFileRef`, `KgImpactRow`, `KgSearchHit`, `KgGraphSummary`, `KbFile`. |
| `kg/store.py` | `KnowledgeBaseStore` protocol, `FileKnowledgeBaseStore` (`<state>/knowledge_bases/<id>.json` + `<id>/{corpus,.contexthub}`), `InMemoryKnowledgeBaseStore(root)`; `validate_kb_id` (`[A-Za-z0-9_-]+`, invalid → `StateNotFoundError`). |
| `kg/ingest.py` | `extract_zip` (zip-slip/symlink rejection, size+count caps, single top-level folder stripped), `copy_tree`, `zip_folder`; `CorpusIngestError(CompilationError)`. |
| `kg/llm_bridge.py` | `ProviderJsonClient(provider, loop)` — sync `chat_json` for the vendored enrich/cluster code, completions scheduled onto the calling loop, fence-tolerant JSON parse, retries. |
| `kg/service.py` | `KgService(store, provider_factory)`: `create_from_zip/path`, `index(kb_id, enrich, provider, model, progress)`, `reindex`, `get`, `list_all`, `delete`, `retrieve`, `search`, `impact`, `catalog`, `graph_summary`, `list_files`, `read_file`; mtime-keyed graph cache. |
| `api/jobs.py` | `Job.scope_id`/`scope_kind` (`project` \| `knowledge_base`), `JobProgress`, `JobKind += kb_ingest`; `project_id` alias kept; `start(scope_id=…, scope_kind=…, progress=…)`, `list(scope_id, scope_kind)`, `active_for_scope`. |
| `api/dependencies.py` | `provider_for_selection(name, model)` (shared by compile + KB), `kb_provider_factory` (default `nemotron`), `get_kg_service()`. |
| `api/app.py` | `/knowledge-bases` routes (create=202+job, list, get, delete, reindex, retrieve, impact, search, files, graph/summary); `GET /jobs?scope_id=&scope_kind=`; `_job_response` carries scope + progress. |
| `api/schemas.py` | `KnowledgeBaseResponse` (+`job`), `KbReindexRequest`, `KbRetrieveRequest/Response`, `KbImpactResponse`, `KbSearchResponse`, `KbFile(List)Response`, `KbGraphSummaryResponse`, `JobProgressSchema`. |
| `cli/kb.py` | `workflow-compiler kb init|list|show|ask|impact|search|delete` (registered in `cli/main.py`). |
| `config.py` | `kg_enrich_default=True`, `kg_retrieve_budget=4000`, `kg_max_upload_mb=50`. |

Frontend (`frontend/`): `app/knowledge/page.tsx` (upload form: zip drop, name, provider picker,
enrichment toggle; list with status pills + live progress), `app/knowledge/[id]/page.tsx` (header
+ reindex/delete, Graph stats by type, Catalog ids, Corpus files browser, **Ask the graph**
(coverage/seeds/sources/rendered packet), **Impact** table), `components/KbStatusPill.tsx`;
`lib/types.ts` + `lib/api.ts` KB additions; `lib/runs.tsx` understands `knowledge_base` jobs
(toast → `/knowledge/{id}`); nav link **Knowledge**.

Examples/scripts: `examples/knowledge_bases/order-lifecycle/` (verbatim `Existing_KG`),
`examples/knowledge_bases/order-lifecycle.zip`, `examples/change_requests/BCR-001-partial-shipment-support.docx`,
`scripts/make_kb_zip.py`. Tests: `tests/test_kg_ingest.py`, `tests/test_kg_service.py`,
`tests/test_api_knowledge_bases.py`, `tests/test_cli_kb.py`, fixture `tests/fixtures/kb_mini/`.

Docs updated: `docs/HOW_IT_WORKS.md` (§8c, §9.2 kb table, §9.3 routes), `docs/architecture.md`
(KB component diagram), `README.md` (Knowledge bases section), `CLAUDE.md` (architecture
paragraph), `docs/kg-plan/RUNBOOK.md`.

## Ids / facts Phase 1 will need

- Live KB (this machine, `.workflow_state/knowledge_bases/`): see RUNBOOK Phase 0 results for the
  kb_id, node counts and catalog. Catalog on the real corpus: epics `EPIC-001` (+`EPIC-001-A`
  minted from a section id), stories `US-001..007`, test cases `TC-01..17` (TC-08/13 are absent in
  the source), requirements `BR-01..10` + `BCR-001`. So Phase 1 numbers **EPIC-002**, **US-008…**,
  **TC-18…**, `TDD-ORD-002`.
- Node id shapes: `mod:existing_Codebase/workflows/order_workflow.py`,
  `fn:existing_Codebase/activities/order_activities.py:dispatch_order`,
  `doc:Business_Docs/epics/EPIC-001-order-lifecycle-management.docx`, `US-003`, `TC-05`, `BR-02`,
  `chunk:<path>:<start>-<end>`; enrichment adds `topic:*` / `entity:*` (`DataArtifact`) and
  `process:*` (`Service`).
- `KgService.retrieve(kb_id, prompt, budget)` returns `KgPacket.rendered` (prompt-ready) plus
  `files[].path/spans` for the "Sources" footer; `impact(kb_id, seeds)` for the deterministic
  affected-node table (seeds = node ids or terms like `complete_order`).
- Provider factory signature `(provider_name | None, model | None) -> BaseLLMProvider`; the API's
  is `api/dependencies.py::kb_provider_factory`; the CLI's wraps `_build_provider`.

## Open issues / notes

- Enrichment quality on Nemotron: strict-JSON per file works (fence-tolerant parse); files that
  fail all retries are skipped and counted in `kb.warnings` ("Enrichment: N file(s) skipped").
- `read_file` returns extracted text for docx/xlsx/pdf (not the binary) — fine for the UI and for
  Phase 1's BCR parsing (`DocumentParserFactory` is the right tool for the BCR docx itself).
- The `JobManager` on the module-level FastAPI `app` is shared across test modules — API tests must
  filter by scope/kb id rather than asserting an empty job list.
- The 2026-08-14 audit P0s (id sanitisation) are handled for the new store; the CAS-on-save item
  remains for Phase 5.

## Phase log
- **Phase 0 — 2026-08-17 — done.** Commits on `feat/kg-change-pipeline`: plan docs → vendoring →
  kg core → API/CLI/examples → frontend → mypy-clean + docs → runbook/handoff. Gates: pytest 620
  passed, ruff clean, mypy strict clean, `npm run build` clean; live UI upload + Nemotron
  enrichment recorded in RUNBOOK.
