# Digest: KG-Context / "Context Hub" (worktree `KG-Context-bm-devansh`)

Source: `C:\Users\devag\Documents\Code (local)\KG-Context-bm-devansh` (branch `benchmark-merge-devansh`, HEAD 0447cad).
Sibling worktrees: `KG-Context` = branch `conforming-to-large-repo` (6d46557, docs-only benchmark-plan revisions on top of `main` b697481) and `KG-Context-bm-tammy` = `benchmark-merge-tammy` (16cac26). All three share `contexthub/bootstrap/`, `model/`, `retrieval/` almost verbatim; the branches diverge in `contexthub/agent/*` (tool delivery / orchestration designs), `benchmark/`, and `sources/`. Tammy's branch additionally has `bootstrap/graphpath.py`, `bootstrap/manifest.py`, `logs.py`; devansh's has `bootstrap/catalogs.py`, `bootstrap/idlinks.py`, `identity.py` (already merged into `main`? no: `main...HEAD` shows they were added on this line). For KG-init reuse, this worktree is the most complete ingest.

---

## 1. What it is

**Purpose.** "Token-efficient knowledge-graph context retrieval": index a repo (code + business docs) into a typed graph (`graph.json`), then answer a prompt with a *context packet* = token-budgeted slice of the graph dereferenced back to real file content (BM25 anchor → BFS traverse → Gaussian banding → fetch). Explicitly **not** embedding-based; explicitly **runs no model itself** — all LLM calls go to an OpenAI-compatible `/v1` URL.

**Stack.** Python ≥3.11 (machine has 3.12.10), stdlib-heavy. Package `context-hub` v2.0.0 (`pyproject.toml`, setuptools; ships only `contexthub*`; `context-hub = "cli:main"` console script — but `cli.py` sits at repo root and is NOT in the wheel, so the console script is broken unless installed `-e` from the repo). Frontend `chat-ui/` = React + Vite + zustand (not shipped).

**Dependencies.**
- Core (required): `PyYAML>=6.0`, `python-docx>=1.1`, `openpyxl>=3.1`. That is all — no graph DB, no embeddings, no vector store, no networkx.
- Extras: `neo4j` (export only, `contexthub/viz/export.py`), `mcp>=1.0` (MCP stdio server), `api`/`gateway`/`agent` = `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `httpx>=0.27`; `dev` = pytest.
- Graph store: **plain JSON** (`<repo>/.contexthub/graph.json`) loaded into an in-memory dataclass `Graph` with adjacency lists. Hub catalog/users/chats: **SQLite** at `~/.contexthub/hub.db`.
- LLM (optional, only for enrichment wave 2 and for chat/agent): stdlib `urllib` client (`bootstrap/llm.py`) against any OpenAI-compatible endpoint. Presets: openai, nvidia, groq, ollama, vllm, lmstudio, openserver/local (`http://127.0.0.1:8080/v1` — i.e. the DGX Spark gateway shape).

**Env keys** (values redacted). Root `.env` (gitignored, auto-loaded by `cli.py::_load_dotenv`, never overrides real env): `LLM_PROVIDER, LLM_MODEL, NVIDIA_API_KEY, LLM_MODELS, CONTEXTHUB_AGENT_FIXTURE_MANIFEST, GROQ_API_KEY, CONTEXTHUB_LLM_FAILOVER, CONTEXTHUB_LLM_MODEL_GROQ, CONTEXTHUB_COMPOSED_TOOLS`.
Recognised by code (`LlmConfig.from_env`, precedence left→right): provider `CONTEXTHUB_LLM_PROVIDER|LLM_PROVIDER`; url `CONTEXTHUB_LLM_API_URL|LLM_API_BASE|OPENAI_BASE_URL|NVIDIA_BASE_URL|LLM_API_URL|preset`; key `CONTEXTHUB_LLM_API_KEY|<preset key var>|OPENAI_API_KEY|NVIDIA_API_KEY|LLM_API_KEY`; model `CONTEXTHUB_LLM_MODEL|OPENAI_MODEL|NVIDIA_MODEL|LLM_MODEL` (empty → auto-pick first id from `/v1/models`). Servers: `GATEWAY_PORT(8080) CONTEXTHUB_GATEWAY_HOST/CORS/STORE, CONTEXTHUB_HOST, PORT|CONTEXTHUB_PORT(8091), CONTEXTHUB_CONFIG_DIR(~/.contexthub), CONTEXTHUB_HUB_DB, CONTEXTHUB_CORS_ORIGINS, CONTEXTHUB_ADMIN_EMAIL/PASSWORD, CONTEXTHUB_ALLOW_DEFAULT_ADMIN, CONTEXTHUB_ALLOW_REGISTER, CONTEXTHUB_LEGACY_SINGLE_GRAPH, CONTEXTHUB_BROWSE_ROOTS, CONTEXTHUB_GRAPH, CONTEXTHUB_REPO_ROOT, CONTEXTHUB_CODEBASE_ROOT, CONTEXTHUB_DEFAULT_BUDGET, CONTEXTHUB_NO_UI, CONTEXTHUB_TOOLSOURCES, CONTEXTHUB_TWO_STAGE_TOOLS, CONTEXTHUB_ORCHESTRATOR`. Template: `examples/configs/env.example`; reference table: `repo_info/04-configuration.md`.

**Docs.** `README.md` (current), `SHIP.md` (repo layout / what ships), `repo_info/00..07-*.md` (authoritative maintained map: concepts, architecture, tools, setup, config, known-issues, ingestion+viz, call graph), `docs/*.md` (many are legacy/handoffs: `architecture-flow.md` legacy, `agent-runtime-demo.md`, `kg-service-demo.md`, `handoff-sources-onboarding.md`, `benchmark-merge-plan.md`, `mcp-architecture.md`, `tool-delivery-modes.md`, ...).

---

## 2. KG initialization (how a graph is built)

### Entry points
- CLI: `python cli.py init <repo> [--out DIR] [--merge <curated-domains-dir>] [--no-functions] [--no-chunks] [--no-llm] [--llm-api-url U] [--llm-api-key K] [--llm-model M]` → `cli.py::cmd_init` → `contexthub.bootstrap.pipeline.init_repo(...)`. Without `<repo>` it opens an interactive/tk picker (`workspace.select_repo`; set `CONTEXTHUB_NO_UI=1` and pass path / `--no-prompt`).
- Other cli subcommands: `ingest` (legacy, no manifest), `build` (curated YAML only), `stats`, `ask`, `context`, `chain`, `workflow`, `journey`, `impact`, `html`, `export` (neo4j), `mcp tools|serve`, `api serve`, `gateway serve`, `fixtures import`, `repos`, `interactive`.
- Hub HTTP: `POST /v1/kgs` (register `{name, repo_path, slug?}`) then `POST /v1/kgs/{id}/index` (`{force_apply?, force_material?}`) → `hub/api.py::_run_index` → `init_repo(Path(kg["repo_path"]), verbose=False)` (no LLM config passed → **Hub-triggered index never runs LLM enrichment**; output always `<repo>/.contexthub/`).
- Python: `from contexthub.bootstrap import init_repo, ingest, load, save` (`contexthub/bootstrap/__init__.py`).

### Pipeline (`contexthub/bootstrap/pipeline.py`)
```python
@dataclass
class InitResult: graph: Graph; graph_path: Path; manifest_path: Path; manifest: dict

def init_repo(repo_path: Path, out_dir: Path | None = None, *,
              merge_domains_dir: Path | None = None, include_functions=True,
              max_defs_per_module=60, include_chunks=True, max_chunks_per_file=40,
              llm_config: LlmConfig | None = None, verbose=False) -> InitResult
```
Steps: `out = out_dir or repo/.contexthub` → **Wave 1** `ingest(repo, cache_dir=out/"extracts", ...)` → **Wave 2 (optional)** `enrich_graph(graph, repo, llm_config, contexthub_dir=out)` → **Wave 3 (optional)** `build(domains_dir=merge_domains_dir)` + `_merge_graphs` (union by node id / (type,src,dst)) → `graph.build_index()`, `retrieval.index.invalidate_cache()` → `save(graph, out/"graph.json")` → write `out/"manifest.json"` `{version:"1.0", indexed_at, git_commit, repo:{path,name,commit}, stats:{nodes,edges,domains}, graph:"graph.json", options:{...,llm_enrich}}`.

### Wave 1 — static ingest (`contexthub/bootstrap/ingest.py`, 1079 lines, no LLM)
```python
def ingest(root: Path, *, verbose=False, include_functions=True, max_defs_per_module=60,
           include_chunks=True, max_chunks_per_file=40, include_docs=True,
           respect_gitignore=True, cache_dir: Path | None = None,
           include_id_links=True, id_link_options: idlinks.IdLinkOptions | None = None,
           include_catalogs=True) -> Graph
```
1. **Walk** (`_walk`): `os.walk` with pruning; honours `.gitignore` (simple fnmatch); skips `IGNORE_DIRS` (.git, node_modules, .venv, dist, build, `.contexthub`, `archive`, tmp, ...), root-only `fixtures/`, `expected/`; `SKIP_EXTENSIONS` (images, archives, **.pdf**, .lock, .min.js, .db...); `GENERATED_MARKERS` text; `MAX_FILE_BYTES=1_000_000`.
2. **Service discovery** (`_discover_services`): dirs containing a manifest (`MANIFESTS` = package.json, pyproject.toml, go.mod, ...) become `Service` nodes (`svc:<rel>`); fallback: second-level dirs under `SERVICE_HINT_DIRS` (services/, apps/, packages/, codebase/...); fallback: the root itself. `Node.domain` = nearest service name (**"domain" = package, not business domain**).
3. **Per file**:
   - Code (`LANG_BY_EXT`: .py .js .jsx .ts .tsx .go .java .rb .rs .php .cs .kt .scala .vue .svelte .swift .m .mm .h .cpp .c .sql) → `Module` node `mod:<rel>` (CONTAINS from service). Defs: Python via **`ast`** (`_python_defs`), everything else regex (`_RE_DEFS`, `_RE_ARROW`) → `Function`/`Class` nodes `fn:<rel>:<name>` (cap 60/module), `IMPORTS` edges module→module (`_resolve_import`), plus derived `Service -DEPENDS_ON-> Service`.
   - Docs (`formats.INDEXABLE_DOC_EXTENSIONS` = .md .rst .adoc .txt .csv .tsv .yaml .yml .json **.mmd .mermaid .docx .xlsx .xls** .html .htm .xml) → `Document` node `doc:<rel>` with `DOCUMENTED_BY` from service and `CONTAINS` from repo. Text via `formats.extract_text(path)` (docx paragraphs+tables via python-docx; xlsx rows via openpyxl; csv/yaml normalised). OpenAPI yaml/json → `Endpoint` (`ep:`) + `Schema` (`schema:`) nodes (`_parse_openapi`, `_attach_endpoint_and_schema_nodes`) with IMPLEMENTS/USES_SCHEMA. Config files → `Config` (`cfg:`) + `READS_CONFIG`.
   - Extract cache: full text written to `.contexthub/extracts/<rel with __>.txt` (`_write_extract`) — this is what enrichment and chunk fetch read for binary formats.
4. **Chunking** (`bootstrap/chunking.py`): `chunk_file(path, text, *, target_lines=60, max_chunks=40) -> list[TextSpan]`; Python by AST symbol spans (`chunk_python`), docs by markdown headings / 60-line windows with 8-line overlap (`chunk_document`). Each span → `Chunk` node `chk:<rel>:NNN` with metadata `{path, repo_path, file, extract_path, start_line, end_line, chunk_index, kind, parent_id, extension, language?, symbol?}`, edges `CONTAINS` (parent→chunk), `NEXT` (chunk→chunk), `RELATES_TO` (fn→chunk when symbol matches). **Chunks are pointers (line ranges), not content.**
5. **Structured passes** (order is load-bearing): `_attach_component_nodes` (reads `code_crosswalk.yaml` → `Component` nodes + `Module -IMPLEMENTS-> Component`) → `_declare_catalog_nodes` (`components.yaml`, `terms.yaml` via `catalogs.parse_declarations`) → `_attach_id_nodes` (`idlinks.py`: regex for `CMP-|API-|US-|REQ-|TC-|EPIC-|TERM-` tokens in all extracted prose → `Component/Endpoint/UserStory/Requirement/TestCase/Epic/Term` nodes, `RELATES_TO` mention edges, `DEPENDS_ON` TC→US→REQ from `linked_to` columns; unmatched ids minted with `metadata.declared=False`) → `_attach_catalog_edges` (typed DEPENDS_ON/IMPLEMENTS from the yaml). `identity.py` normalises `CMP-OrderService` ↔ `Order Service` ↔ `order_service`.

### Wave 2 — LLM enrichment (`bootstrap/enrich.py`, `bootstrap/cluster.py`, `bootstrap/llm.py`)
```python
def enrich_graph(graph: Graph, repo_root: Path, config: LlmConfig, *,
                 contexthub_dir: Path | None = None, verbose=False) -> Graph
def cluster_processes(graph: Graph, config: LlmConfig, *, cache_dir: Path, verbose=False) -> Graph
@dataclass class LlmConfig: api_url: str; api_key: str; model=""; provider="openai"; temperature=0.1; max_tokens=1024; timeout_seconds=180
    @classmethod from_env(*, api_url=None, api_key=None, model=None, provider=None) -> LlmConfig | None
class LlmClient(config).chat_json(messages, *, label="", retries=3) -> dict   # stdlib urllib, JSON-fence tolerant
```
Per `Document`/`Module` node: text from extract cache, clipped to `LLM_INPUT_CHARS=2_800`, one chat call with system prompt `_SYSTEM` asking for JSON `{summary, topics[3-8], entities[], doc_type: code|api_spec|brd|tdd|aid|test|config|sequence|data|other}`; cached at `.contexthub/llm_cache/<node>_<sha256>.json`. Writes `node.summary`, `metadata.topics/entities/doc_type/llm_enriched`; creates `topic:<slug>` and `entity:<slug>` nodes (typed **`DataArtifact`**, `metadata.kind = topic|entity`), `Repository -CONTAINS->` them and `file -RELATES_TO-> topic/entity` (`Confidence.INFERRED, Source.LLM`). Then `cluster_processes`: batched LLM call groups all file nodes into business processes → `svc:proc:<slug>` `Service` nodes with `CONTAINS` + `DEPENDS_ON`. No entity/relation extraction beyond that — no triples, no per-chunk extraction.

### Wave 3 — curated merge (`bootstrap/build.py`)
`build(domains_dir, *, journeys_dir=None, shared_dir=None) -> Graph` from `*.domain.yaml` / `*.journey.yaml` (`examples/telecom/`, `examples/synthetic-telecom/curated/`): Domain→Subdomain→Stage hierarchy, PRECEDES/TRIGGERS/REALIZES/USES_SCHEMA/DOCUMENTED_BY/OWNED_BY, journeys (NEXT), data-flow (PRODUCES/CONSUMES/FLOWS_TO). This is the only way to get real business-domain nodes.

### Storage / schema (`contexthub/model/schema.py`, `bootstrap/store.py`)
- `save(graph, path) -> Path` / `load(path) -> Graph`; JSON `{"nodes":[{id,type,name,domain,summary,summary_tokens,documentation,metadata}], "edges":[{type,src,dst,attributes,confidence,source,weight}]}`. Default location `<repo>/.contexthub/graph.json` (+ `manifest.json`, `extracts/`, `llm_cache/`); `paths.DEFAULT_GRAPH_PATH` = `<KG-Context repo>/graph.json` for legacy commands.
- `Node(id, type: NodeType, name, domain=None, summary="", summary_tokens=0, documentation=[], metadata={}, cache={})`; `Edge(type: EdgeType, src, dst, attributes={}, confidence=CONFIRMED|INFERRED, source=STATIC|PARSED|LLM, weight=1.0)`; `Graph(nodes: dict, edges: list)` with `add_node/add_edge/build_index/incident/neighbors`.
- `NodeType`: Domain, Subdomain, Stage, DataArtifact, Journey, Service, Component, Endpoint, Schema, Document, Config, Team, Requirement, UserStory, TestCase, Epic, Term, Repository, Module, Function, Class, Chunk.
- `EdgeType`: CONTAINS, PRECEDES, TRIGGERS, FLOWS_TO, NEXT, PRODUCES, CONSUMES, REALIZES, CALLS, IMPLEMENTS, USES_SCHEMA, DEPENDS_ON, READS_CONFIG, DOCUMENTED_BY, RELATES_TO, OWNED_BY, IMPORTS. Groupings `WORKFLOW_EDGE_TYPES / CODE_EDGE_TYPES / IMPACT_EDGE_TYPES`; `POINTER_METADATA_KEYS`.

---

## 3. Query / retrieval API

Engine: `contexthub/retrieval/` (pure Python over the in-memory Graph).
- `index.py`: inverted-index BM25 over `node_text(node)` (id+name+summary+metadata), cached per `graph_stamp`. `get_index(graph) -> AnchorIndex`, `invalidate_cache(graph=None)`.
- `hub.py`: `anchor_scored(graph, prompt, *, k=3) -> list[(node_id, score)]`; `anchor(...) -> list[str]`; `traverse(graph, seeds, *, max_hops=2) -> (subgraph, hops)` (BFS both directions); `assemble(subgraph, hops, *, token_budget=1500) -> ContextPacket(nodes, edges, total_tokens, seeds, hops)`; `ask(graph, prompt, *, max_hops=2, token_budget=1500, k=3)`; `chain(graph, seed, *, direction="down", token_budget=2000, ...) -> ChainPacket`.
- `context.py` — **main entry**: `build_context(graph, prompt, *, repo_root=None, total_budget=4000, sigma=0.85, max_hops=2, k=3) -> ContextPacket(prompt, seeds, focus_domain, repo_root, sections: list[Section(band,node_id,tokens,path,start_line,end_line)], files: list[FileRef], total_tokens, rendered: str, band_budgets, coverage, uncovered_terms, low_confidence, refinement_rounds)`; `render_packet(packet, graph) -> str`. Algorithm: BM25 anchor → pick focus domain → BFS → bands focus/connected/rest with Gaussian budget split → `fetcher.render(node, Level.FULL|SUMMARY|LINE)` dereferences to real files (Chunk → exact line span via `read_chunk_span`; Module/Document → source/docs; keyword snippet highlighting; coverage scoring + one refinement round using `find_leaf_nodes_for_terms`).
- `fetcher.py`: `resolve_repo_root(graph, explicit)`, `read_chunk_span(repo_root, node, *, max_tokens)`, `read_source/read_docs(graph, node, repo_root, max_tokens, *, highlight_terms)`, `signature(graph, node)`, `render(graph, node, level, *, repo_root, budget=1200, highlight_terms)`. Needs the **original repo on disk** (or the `extracts/` cache) — graph alone is not enough for FULL content.

Consumers of the one engine:
1. **Python** — `store.load(path)` + `build_context(...)`; multi-graph wrapper `hub/graphs.py::retrieve_for_kg(*, kg_id, graph_path, repo_root, prompt, budget=4000, max_hops=2, sigma=0.85) -> dict` (mtime-keyed `GraphCache`); returns `{tool:"retrieve_context", prompt, seeds, focus_domain, repo_root, total_tokens, rendered, band_budgets, coverage, uncovered_terms, low_confidence, refinement_rounds, sections[], files[{path,band,tokens,node_ids,spans}]}`.
2. **Hub API** (`hub/api.py`, FastAPI, :8091, cookie sessions, SQLite): `POST /v1/kgs/{kg_id}/retrieve` body `{prompt, budget?, max_hops?, sigma?}` → the dict above. Also `GET/POST /v1/kgs`, `POST /v1/kgs/{id}/assess|index|propose-patch|fixtures/import`, `/v1/kg-proposals/*`, `/v1/fs/roots|browse`, `/v1/auth/*`, `/v1/users`, `/v1/conversations*`; agent router mounted under `/v1/agent/*` (`agent/api.py`: `/runs`, `/runs/{id}/events` SSE, `/tools`, `/composed-tools`).
3. **Legacy single-graph HTTP** (`interface/http_api.py`, `CONTEXTHUB_LEGACY_SINGLE_GRAPH=1`): `GET /health`, `GET /v1/tools`, `POST /v1/tools/{name}`, `POST /v1/retrieve {prompt,...}`, `GET /v1/stats`.
4. **MCP stdio** (`interface/mcp_server.py`, `python cli.py mcp serve --graph G --repo R --no-prompt --cli`, needs `pip install mcp`): tools `kg__retrieve_context`, `kg__graph_search`, `kg__fetch_node`, `kg__get_impact`, `kg__explain_path` (+ `kg__traverse`, `kg__graph_stats`, and an orchestrated `investigate`); wire names use `__`, `call_tool` also accepts `kg.retrieve_context` / bare names. Env `CONTEXTHUB_GRAPH`, `CONTEXTHUB_REPO_ROOT`.
5. **Agent runtime** (`agent/tools.py` `kg.*` tools + 27 mock `aifo.*`/`aifqe.*` enterprise tools taking a `ToolContext`; `agent/runtime.py` run loop; `agent/llmclient.py` httpx async client with native tools + JSON fallback).

**Context assembly for the LLM**: no server-side fusion for normal chat. The browser calls `/v1/kgs/{id}/retrieve`, then prepends `kgContextSystemMessage(result)` = fixed header ("You are answering with help from a knowledge-graph context packet ... Prefer facts from this packet ... --- KNOWLEDGE GRAPH CONTEXT ---" + `rendered` + "--- END CONTEXT ---") as an extra system message to the OpenAI-compatible completion (`chat-ui/src/store/useChatStore.ts`, `lib/kgClient.ts`). Any non-UI client is ungrounded unless it does the same.

---

## 4. Chat: chat-ui, gateway, `.chat-store`

- `chat-ui/` (React/Vite/zustand, port 5174, `scripts/start-kg-chat-ui.{sh,ps1}`): components `ChatLayout, Sidebar, MessageList, ChatInput, KgContextPanel, KgSourceFiles, ExaminedFiles, AgentPanel, ProposalsPanel, ProjectPickerModal, SettingsModal, LoginPage...`; stores `useChatStore` (conversations/messages/streaming + KG retrieve), `useAuthStore`, `useAgentStore`; libs `api.ts` (LLM `/v1/chat/completions` or `/v1/responses` streaming, `/v1/models`), `kgClient.ts` (Hub KG endpoints), `conversations.ts` (Hub `/v1/conversations` CRUD + `PUT .../messages` sync), `agentClient.ts`.
- **Model gateway** (`interface/model_gateway.py`, :8080, `python cli.py gateway serve`): OpenAI-compatible proxy that holds the API key (`/v1/models`, `/v1/chat/completions`, `/v1/responses`), M3 failover chain (`CONTEXTHUB_LLM_FAILOVER`, NVIDIA→Groq), plus its **own** flat-file conversation store `ConversationStore` at `.run/conversations.json` (`CONTEXTHUB_GATEWAY_STORE`) and a stub local user.
- **Two conversation stores exist** (known issue §7): gateway flat file, and Hub SQLite (`hub/repo.py`: users, sessions, `kg_registry`, conversations, messages, `agent_memory`, proposals; `create_conversation(conn,*,user_id,title,kg_id)`, `replace_messages(...)`, `add_agent_memory(...)`, `list_agent_memory(conn, conv_id, limit=3)`).
- Memory model: a `Conversation {id,title,kgId,messages[],createdAt,updatedAt}`; each `ChatMessage {id,role,content,userPrompt?,attachments?,kgContext?: KgContextSnapshot{rendered,totalTokens,focusDomain,seeds,coverage,sectionCount,files[]},agentActivity?}`. Whole message list is re-sent to the model each turn (plain chat history); the KG packet is fetched fresh per user turn from the *latest prompt only*; agent runs get up to 3 prior `agent_memory` summaries per conversation. No summarisation/embeddings.
- `.chat-store/chat-nemotron.json` at repo root: a legacy/exported flat store `{"conversations":[{id,title,model,created_at,updated_at,messages:[]}]}` (one empty conversation) — importable via gateway `POST /v1/conversations/import`.

---

## 5. Peripheral directories

- `benchmark/` — the benchmark-merge work (plan `docs/benchmark-merge-plan.md`): `cases.yaml`, `cli.py`, `metrics.py`, `records.py`, `report.py`, `spec.py`, `compare.py`, `adapters/{devansh,tammy}.py`, `RUNBOOK.md` (pinned run conditions: `nvidia/nemotron-3-nano-30b-a3b`, strict mode, MCP transport, 3 repeats), `devansh/{headline,control}/` results (`runs.jsonl`, `metrics.json`, `REPORT.md`). Measures agent tool-delivery designs, not KG quality.
- `testing/` — `unit/` (37 files: `test_ingest_walk, test_id_links, test_catalogs, test_component_crosswalk, test_context_files, test_hub, test_mcp_ab_parity, ...`), `contract/` (frontend/manifest/registry contracts), `eval/` (golden-question harness, `CONTEXTHUB_EVAL_LIVE=1` for live LLM), `fixtures/echo_mcp_server.py`. Run `python -m pytest testing/unit -q`.
- `examples/` — `small-repo/` (docs/bdr/checkout.md, docs/tdd/checkout-tdd.md, src/main.py, payment.py, api/orders.py — 5-file offline smoke test), `synthetic-telecom/` (curated reference dataset: `example_codebase/` + `example_docs/` {adr, aid, brd, tdd, requirements incl. .docx/.csv, test incl. .xlsx, sequence .mmd, runbooks, incidents, kg-seed}, `curated/` domain YAML, `fixtures/` aifo/aifqe JSON, `expected/golden-questions.yaml`; needs a junction dir with both siblings to index as one graph), `telecom/` (14 curated domain YAML for `--merge`), `configs/env.example`, `prompts/coding_queries.txt`.
- `sources/` — second, uncurated demo corpus: `codebase/` (12 services) + 76 flat root docs (BRD/AID/TDD .docx, OpenAPI .yaml, seq .mmd, epics/user_stories .csv, test_cases .xlsx, `components.yaml`, `terms.yaml`, `code_crosswalk.yaml`) + `fixtures/`, `expected/`. **This is exactly a docs+code ingestion like ours** (`python cli.py init sources --no-llm --no-prompt`).
- `repo_info/` — maintained repo map (00-concepts … 07-call-graph). Read `05-known-issues.md` and `06-ingestion-and-visualization.md` first.
- `scripts/` — start scripts (`start-gateway`, `start-kg-api`, `start-kg-chat-ui` in .sh/.ps1), `benchmark_retrieval.py`, `eval_goldset.py`, `diagnose_retrieval.py`, `derive_fixtures.py`, `identity_spike.py`.
- Also at root: `.run/` (target-repo junctions, bench, sources-eval-extracts), `.logs/`, `Dockerfile`, `docker-compose.yml`, `repo-kg/`, `tools/`.

---

## 6. Reuse assessment (embedding KG init + query in workflow-compiler)

**Cleanest path: import the package.** `contexthub/bootstrap` + `model` + `retrieval` are pure Python, stdlib + PyYAML/python-docx/openpyxl, no globals except two caches (`retrieval.index._INDEX_CACHE`, `hub.graphs._CACHE`) and `paths.REPO_ROOT` (only used for `examples/` and legacy default graph path). Options in order of preference:
1. `pip install -e "C:/.../KG-Context-bm-devansh"` (or `pip install .`; extras not needed for init/query) → in workflow-compiler:
   ```python
   from contexthub.bootstrap.pipeline import init_repo
   from contexthub.bootstrap.llm import LlmConfig
   from contexthub.bootstrap.store import load
   from contexthub.retrieval.context import build_context
   res = init_repo(Path(project_dir), out_dir=Path(project_dir)/".contexthub",
                   llm_config=LlmConfig(api_url="http://192.168.1.184:8080/v1", api_key="", model="...", provider="local"))  # or None for static-only
   g = load(res.graph_path); packet = build_context(g, prompt, repo_root=project_dir, total_budget=4000)
   packet.rendered  # → prepend as system message
   ```
   For a FastAPI host, reuse `hub/graphs.py::retrieve_for_kg` (thread-safe cache) or copy its 40 lines. Vendoring only `contexthub/{model,bootstrap,retrieval,paths.py,identity.py}` (~5k lines) is also feasible — `bootstrap` imports `..retrieval.index` and `..identity`; `retrieval` imports `..model` only.
2. Subprocess CLI: `python <KG>/cli.py init <dir> --no-prompt [--no-llm]` (set `CONTEXTHUB_NO_UI=1`), then read `.contexthub/graph.json`. Works today (that is how the existing `.contexthub` in order-workflows-demo was produced) but pulls the whole tree incl. agent/tk workspace code and the repo `.env`.
3. HTTP service: run `python cli.py api serve` (:8091) and call `POST /v1/kgs` + `/index` + `/retrieve` — brings auth/cookies, SQLite at `~/.contexthub/hub.db`, and the index endpoint cannot enable LLM enrichment.
4. MCP stdio server — good for agents/Claude Code, awkward from FastAPI.

**Constraints**: Python ≥3.11 (`X | None`, dataclasses w/ slots-free; workflow-compiler already on 3.12). Heavy deps: none (fastapi/uvicorn/httpx only for servers; `mcp` only for MCP). Hard-coded paths: `paths.py` (`REPO_ROOT/examples`, `REPO_ROOT/graph.json` default), `~/.contexthub/{config.json,hub.db}`, `.run/conversations.json`; `IGNORE_DIRS` contains `archive`, `tmp`, `temp`, `bin`, `out`, `env` — check nothing in workflow-compiler's docs lives under those names (e.g. a `bin/` or `env/` doc folder would be skipped). `_load_dotenv` reads the KG repo's own `.env` when going through `cli.py`; direct import does not.

**`.contexthub` convention** and what is already in `order-workflows-demo/.contexthub`: `graph.json` (12.8 MB, 8052 nodes / 15651 edges: Chunk 6050, Function 1024, Class 416, Module 290, Document 264, Service 4, Config 3, Repository 1; edges CONTAINS 8046, NEXT 5499, RELATES_TO 1224, IMPORTS 612, DOCUMENTED_BY 264), `manifest.json` (indexed 2026-07-31, `llm_enrich:false`, `repo.path` = **`...\order-workflows-iterative-2.0`**, commit 1a0c002a2b5b — i.e. the graph was built for the *sibling repo* and the folder was copied; pointer paths are relative so they may still dereference, but `manifest.repo.path` and the MCP `toolsources.json` (`--repo ...iterative-2.0`, `--graph ...iterative-2.0\.contexthub\graph.json`, python from a hermes venv, `KG-Context\cli.py`) point at the other checkout), `extracts/` (551 cached text files, incl. `.playwright-mcp` snapshots and `.claude/settings.local.json` — the walker indexed dot-dirs that are not in `IGNORE_DIRS`), `composed_tools.json` (agent composed tool `find_dependents` over `kg.graph_search`), `toolsources.json` (MCP provider `kg` allow-list of the 5 `kg__*` tools). It is stale relative to the demo branch and has no LLM enrichment; regenerate rather than trust.

---

## 7. Gotchas

- `.pdf` is **skipped** (`SKIP_EXTENSIONS`); docx/xlsx need python-docx/openpyxl (silently return "" if missing). `.mmd` is read as plain text (no mermaid parsing).
- `Node.domain` = nearest package/service dir, not a business domain; on a single-package repo the Gaussian bands collapse to a flat dump. Real business domains only via `--merge` curated YAML (`examples/telecom/domains/_TEMPLATE.domain.yaml`).
- Chunk nodes are line-range pointers; edit/move the repo and they drift/fail. Graph is a build artifact, gitignored, goes stale silently; `hub/material.py::assess_repo_changes` only *advises*. Long-lived processes cache graphs (`GraphCache`) and BM25 (`_INDEX_CACHE`) — call `invalidate` / restart after re-index.
- LLM enrichment: per-file call, 2.8k-char clip, `max_tokens=1024`, `temperature=0.1`, timeout 180 s, 3 retries; expects strict JSON (fence-tolerant). Reasoning models (gpt-5/o-series/gpt-oss) get `max_completion_tokens` and no temperature (`uses_restricted_params`). Cache keyed by content hash under `.contexthub/llm_cache/`. Hub `/index` never enables it. Cluster pass is one batched call over the whole file manifest — can exceed small local-model context.
- Retrieval is keyword/BM25 — no embeddings; synonyms/paraphrase miss. `coverage`/`low_confidence` fields tell you when the anchor failed.
- Grounding is client-side in chat-ui only; gateway/API completions are ungrounded unless you prepend the packet yourself. Two auth+conversation implementations (gateway vs hub).
- Non-Python code: defs by regex only. Caps: 60 defs/module, 40 chunks/file, 1 MB/file, silently truncated.
- Anthropic has no preset (not OpenAI-compatible); exercised: OpenAI, NVIDIA, Ollama, vLLM, Groq, local gateway.
- Security defaults for laptop only: seeded `admin@contexthub.local/admin`, `fsbrowse` serves any path unless `CONTEXTHUB_BROWSE_ROOTS`, CORS `*` on Hub. A prior `NVIDIA_API_KEY` leaked into a transcript (rotate if live).
- `console_scripts context-hub = cli:main` references root `cli.py`, which is excluded from the wheel — only works with editable install from the repo.
- Interactive tk repo picker fires when `init` gets no path; always pass a path and `CONTEXTHUB_NO_UI=1` in automation. `PYTHONUTF8=1` for redirected CLI output on Windows (arrows/box chars in verbose prints).
- Windows path separators end up inside node ids (`doc:workflow-compiler\README.md`) — ids are OS-specific; don't build a graph on Windows and dereference on Linux.
