# Vendored: Context Hub (`contexthub`) subset

| | |
|---|---|
| **Source** | `C:\Users\devag\Documents\Code (local)\KG-Context-bm-devansh` (worktree of the KG-Context repo) |
| **Commit** | `0447cad` |
| **Vendored on** | 2026-08-17 |
| **Subset** | `model/`, `bootstrap/` (`pipeline, ingest, chunking, formats, store, enrich, cluster, llm, catalogs, idlinks, build`), `retrieval/` (`index, hub, context, fetcher, impact`), `identity.py`, `paths.py` |
| **Not vendored** | `interface/`, `hub/`, `agent/`, `viz/`, `workspace*.py`, root `cli.py`, examples, tests |
| **Type-checking** | excluded from `mypy --strict` (`[[tool.mypy.overrides]]` in `pyproject.toml`); ruff runs with the style rules relaxed for this directory only |

The typed façade the rest of workflow-compiler uses is `workflow_compiler.kg.service.KgService`;
never import this subpackage from outside `workflow_compiler.kg`.

## Local edits (search for `workflow-compiler edit`)

1. **`__init__.py`** — exports only `bootstrap`, `model`, `retrieval` (upstream also imports `interface`).
2. **`paths.py`** — `REPO_ROOT` is the package dir; `EXAMPLES_DIR`/`TELECOM_*` are non-existent
   package-local defaults (only used as defaults by `bootstrap/build.py`); `DEFAULT_GRAPH_PATH`
   is cwd-relative `.contexthub/graph.json` instead of `<repo>/graph.json`. Callers always pass
   explicit paths.
3. **`bootstrap/llm.py`** — adds the `JsonChatClient` Protocol (`chat_json(messages, *, label,
   retries) -> dict`). `LlmClient` is unchanged and satisfies it.
4. **`bootstrap/enrich.py`** — `enrich_graph(..., config: LlmConfig | None, *, client=None,
   on_progress=None)`: an injected client replaces `LlmClient(config)`; `on_progress(node_id,
   done, total)` is called per file and once before clustering. The client is passed down to
   `cluster_processes`.
5. **`bootstrap/cluster.py`** — `cluster_processes(..., config: LlmConfig | None, *, client=None)`
   mirrors (4).
6. **`bootstrap/pipeline.py`** — `init_repo(..., llm_client=None, on_progress=None)`; enrichment
   runs when either `llm_config` or `llm_client` is given; `manifest.options.llm_enrich` reflects both.
7. **`bootstrap/ingest.py`** — `.pdf` removed from `SKIP_EXTENSIONS`; new `_normalise_posix(graph)`
   runs at the end of `ingest()` so node ids (`mod:existing_Codebase/workflows/order_workflow.py`),
   module/chunk names and `path`/`repo_path`/`file`/`extract_path`/`declared_in` metadata use
   `/` on every OS (upstream produced `\` inside ids on Windows).
8. **`bootstrap/formats.py`** — `.pdf` is an indexable document; `_extract_pdf` routes it through
   `workflow_compiler.ingestion.DocumentParserFactory` (pypdf).

Everything else is byte-identical to upstream at the pinned commit. To re-vendor: copy the
subset, re-apply the edits above (they are small and commented), re-run `pytest tests/test_kg_*.py`.
