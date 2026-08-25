"""``KgService`` — the typed façade over the vendored Context Hub engine.

Lifecycle of a knowledge base::

    create_from_zip / create_from_path   →  record saved with status "ingesting",
                                            corpus extracted to <kb>/corpus/
    index(kb_id, enrich=…)               →  init_repo(corpus, out=<kb>/.contexthub)
                                            in a worker thread; optional LLM
                                            enrichment through the app's provider;
                                            stats/catalog recorded; status "ready"
    retrieve / impact / search / catalog / graph_summary / read_file

Everything that touches the LLM goes through the injected ``provider_factory``
(``(provider_name, model) -> BaseLLMProvider``), so tests pass a factory that
returns a :class:`MockProvider` and the API passes the same per-request
selection used by ``/projects/compile``. Indexing is CPU/IO bound and runs
via ``asyncio.to_thread``; the enrichment bridge schedules completions back on
the calling loop (see :mod:`workflow_compiler.kg.llm_bridge`).
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import threading
from collections import Counter, deque
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from workflow_compiler.exceptions import CompilationError, StateNotFoundError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.kg.ingest import copy_tree, extract_zip
from workflow_compiler.kg.llm_bridge import ProviderJsonClient
from workflow_compiler.kg.models import (
    KbCatalog,
    KbFile,
    KbSource,
    KbStats,
    KgFileRef,
    KgGraphSummary,
    KgImpactRow,
    KgNodeBrief,
    KgPacket,
    KgSearchHit,
    KgSection,
    KnowledgeBase,
)
from workflow_compiler.kg.store import KnowledgeBaseStore, validate_kb_id

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[str | None, str | None], BaseLLMProvider]
ProgressCallback = Callable[[str, int, int], None]

#: Edge types the impact traversal follows (both directions). ``CONTAINS`` is
#: followed only *downwards from file-level nodes* (module → function/chunk) —
#: from a Repository/Service node it would reach everything.
_IMPACT_EDGE_TYPES = frozenset(
    {
        "DEPENDS_ON",
        "CALLS",
        "TRIGGERS",
        "IMPORTS",
        "IMPLEMENTS",
        "RELATES_TO",
        "DOCUMENTED_BY",
        "USES_SCHEMA",
        "READS_CONFIG",
        "PRODUCES",
        "CONSUMES",
        "REALIZES",
    }
)
_CONTAINER_TYPES = frozenset({"Repository", "Service", "Domain", "Subdomain"})
_BUSINESS_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,6}-\d+[A-Za-z0-9-]*$")
_TEXT_LIKE = frozenset(
    {
        ".md",
        ".txt",
        ".py",
        ".mmd",
        ".mermaid",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".tsv",
        ".html",
        ".htm",
        ".xml",
        ".rst",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".sql",
        ".sh",
        ".ps1",
        ".env",
        ".gitignore",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


#: Recorded on a knowledge base whose index job died before finishing.
INTERRUPTED_ERROR = (
    "Indexing was interrupted before it finished (the server stopped or restarted, or the "
    "job was cancelled). Press Reindex to resume; cached enrichment results are reused."
)


class KgService:
    """Create, index and query knowledge bases (see module docstring)."""

    def __init__(
        self,
        store: KnowledgeBaseStore,
        provider_factory: ProviderFactory | None = None,
        *,
        max_upload_bytes: int = 50 * 1024 * 1024,
        default_budget: int = 4000,
        enrich_call_timeout: float | None = None,
    ) -> None:
        self._store = store
        self._provider_factory = provider_factory
        self._max_upload_bytes = max_upload_bytes
        self._default_budget = default_budget
        #: Wall-clock cap per enrichment call attempt (None = unbounded); the
        #: API wires ``settings.llm_timeout`` so one stalled hosted request
        #: cannot freeze an index for longer than a normal timeout would.
        self._enrich_call_timeout = enrich_call_timeout
        self._graphs: dict[str, tuple[float, Any]] = {}
        self._graph_lock = threading.Lock()

    # ------------------------------------------------------------------ paths
    @property
    def store(self) -> KnowledgeBaseStore:
        return self._store

    def corpus_dir(self, kb_id: str) -> Path:
        return self._store.kb_dir(kb_id) / "corpus"

    def hub_dir(self, kb_id: str) -> Path:
        return self._store.kb_dir(kb_id) / ".contexthub"

    def graph_path(self, kb_id: str) -> Path:
        return self.hub_dir(kb_id) / "graph.json"

    # --------------------------------------------------------------- lifecycle
    async def create_from_zip(
        self,
        name: str,
        data: bytes,
        *,
        owner_id: str | None = None,
        filename: str | None = None,
        kb_id: str | None = None,
    ) -> KnowledgeBase:
        """Extract an uploaded zip into a new knowledge base (status ``ingesting``).

        Indexing is a separate step (:meth:`index`) so the API can run it as a
        background job while this call returns immediately.
        """
        kb = KnowledgeBase(
            name=name.strip() or (filename or "knowledge base"),
            owner_id=owner_id,
            source=KbSource(kind="zip", filename=filename),
        )
        if kb_id:
            kb.kb_id = validate_kb_id(kb_id)
        corpus = self.corpus_dir(kb.kb_id)
        if corpus.exists():
            raise CompilationError(f"Knowledge base {kb.kb_id!r} already has a corpus.")
        result = await asyncio.to_thread(
            extract_zip, data, corpus, max_bytes=self._max_upload_bytes
        )
        kb.stats.files = result.files
        if result.stripped_root:
            kb.warnings.append(f"Stripped top-level folder {result.stripped_root!r} from the zip.")
        await self._store.save(kb)
        return kb

    async def create_from_path(
        self,
        name: str,
        source: Path,
        *,
        owner_id: str | None = None,
        kb_id: str | None = None,
    ) -> KnowledgeBase:
        """Copy a local folder (CLI ingress) into a new knowledge base."""
        kb = KnowledgeBase(
            name=name.strip() or Path(source).name,
            owner_id=owner_id,
            source=KbSource(kind="path", filename=str(Path(source).resolve())),
        )
        if kb_id:
            kb.kb_id = validate_kb_id(kb_id)
        corpus = self.corpus_dir(kb.kb_id)
        if corpus.exists():
            raise CompilationError(f"Knowledge base {kb.kb_id!r} already has a corpus.")
        result = await asyncio.to_thread(
            copy_tree, Path(source), corpus, max_bytes=self._max_upload_bytes
        )
        kb.stats.files = result.files
        await self._store.save(kb)
        return kb

    async def index(
        self,
        kb_id: str,
        *,
        enrich: bool = False,
        provider: str | None = None,
        model: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> KnowledgeBase:
        """(Re)build the graph for ``kb_id``; records stats/catalog and status.

        A failure is recorded on the knowledge base (``status="failed"``,
        ``error``) and re-raised so a job reports it too. Static ingest never
        needs a provider; with ``enrich`` the ``provider_factory`` builds one
        and per-file summaries/topics/entities plus process clusters are added.
        Enrichment results are cached by content hash under ``.contexthub/llm_cache``,
        so a re-index after a failure only re-asks for what is missing.
        """
        kb = await self._store.load(kb_id)
        corpus = self.corpus_dir(kb_id)
        if not corpus.is_dir():
            raise CompilationError(f"Knowledge base {kb_id!r} has no corpus directory.")
        kb.status = "ingesting"
        kb.error = None
        kb.touch()
        await self._store.save(kb)

        client: ProviderJsonClient | None = None
        llm_provider: BaseLLMProvider | None = None
        if enrich:
            if self._provider_factory is None:
                raise CompilationError("LLM enrichment requested but no provider factory is set.")
            llm_provider = self._provider_factory(provider, model)
            client = ProviderJsonClient(
                llm_provider,
                loop=asyncio.get_running_loop(),
                call_timeout=self._enrich_call_timeout,
            )

        def _report(label: str, done: int, total: int) -> None:
            if progress is not None:
                progress(label, done, total)

        def _run() -> Any:
            from workflow_compiler.kg.contexthub.bootstrap import init_repo

            _report("static ingest", 0, 0)
            return init_repo(
                corpus,
                out_dir=self.hub_dir(kb_id),
                llm_client=client,
                on_progress=_report,
            )

        try:
            result = await asyncio.to_thread(_run)
        except asyncio.CancelledError:
            # A cancelled job (user cancel, server shutdown) must not leave the
            # record at "ingesting": nothing would ever move it on. The worker
            # thread cannot be stopped, but this coroutine never resumes, so the
            # record can only change again through a reindex.
            kb.status = "failed"
            kb.error = INTERRUPTED_ERROR
            kb.touch()
            await self._store.save(kb)
            raise
        except Exception as exc:
            kb.status = "failed"
            kb.error = str(exc) or exc.__class__.__name__
            kb.touch()
            await self._store.save(kb)
            raise
        finally:
            if llm_provider is not None:
                aclose = getattr(llm_provider, "aclose", None)
                if callable(aclose):
                    try:
                        await aclose()
                    except Exception:  # pragma: no cover - best-effort cleanup
                        logger.debug("provider aclose failed", exc_info=True)

        graph = result.graph
        self._cache_put(kb_id, graph)
        kb.stats = self._stats(graph, corpus)
        kb.catalog = self._catalog(graph, self.hub_dir(kb_id))
        kb.indexed_at = _now()
        kb.llm_enriched = bool(enrich)
        kb.provider_used = llm_provider.name if llm_provider is not None else None
        kb.model_used = model if enrich else None
        kb.status = "ready"
        kb.error = None
        kb.warnings = [w for w in kb.warnings if not w.startswith("Enrichment:")]
        if client is not None and client.failures:
            kb.warnings.append(
                f"Enrichment: {client.failures} file(s) skipped after repeated LLM failures."
            )
        if kb.stats.by_type.get("Document", 0) == 0 and kb.stats.by_type.get("Module", 0) == 0:
            kb.warnings.append("The corpus produced no Document or Module nodes.")
        kb.touch()
        await self._store.save(kb)
        return kb

    async def reindex(
        self,
        kb_id: str,
        *,
        enrich: bool = False,
        provider: str | None = None,
        model: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> KnowledgeBase:
        """Rebuild the graph from the existing corpus (keeps the enrichment cache)."""
        return await self.index(
            kb_id, enrich=enrich, provider=provider, model=model, progress=progress
        )

    async def mark_interrupted(self, kb_id: str) -> KnowledgeBase:
        """Record that the index job for ``kb_id`` died without finishing.

        Indexing runs as an in-memory job, so a server stop or restart takes
        the job with it and the record would stay at ``ingesting`` forever
        (``uvicorn --reload`` triggers exactly that: the corpus's own ``*.py``
        files are extracted under the watched directory). The API calls this
        when a knowledge base reports ``ingesting`` but the process has no job
        for it. A knowledge base that is not ``ingesting`` is returned unchanged.
        """
        kb = await self._store.load(kb_id)
        if kb.status != "ingesting":
            return kb
        kb.status = "failed"
        kb.error = INTERRUPTED_ERROR
        kb.touch()
        await self._store.save(kb)
        return kb

    async def get(self, kb_id: str) -> KnowledgeBase:
        return await self._store.load(kb_id)

    async def list_all(self) -> list[KnowledgeBase]:
        items: list[KnowledgeBase] = []
        for kb_id in await self._store.list_ids():
            try:
                items.append(await self._store.load(kb_id))
            except Exception:  # corrupt record must not hide the rest
                logger.warning("Skipping unloadable knowledge base %r", kb_id)
        return sorted(items, key=lambda k: k.created_at, reverse=True)

    async def delete(self, kb_id: str) -> None:
        validate_kb_id(kb_id)
        with self._graph_lock:
            self._graphs.pop(kb_id, None)
        await self._store.delete(kb_id)

    # ---------------------------------------------------------------- queries
    async def retrieve(
        self,
        kb_id: str,
        prompt: str,
        *,
        budget: int | None = None,
        max_hops: int = 2,
    ) -> KgPacket:
        """Anchor → traverse → dereference: a grounded packet for ``prompt``."""
        graph = await self._graph(kb_id)
        corpus = self.corpus_dir(kb_id)

        def _run() -> Any:
            from workflow_compiler.kg.contexthub.retrieval import build_context

            return build_context(
                graph,
                prompt,
                repo_root=str(corpus),
                total_budget=budget or self._default_budget,
                max_hops=max_hops,
            )

        packet = await asyncio.to_thread(_run)
        return KgPacket(
            prompt=packet.prompt,
            seeds=list(packet.seeds),
            focus_domain=packet.focus_domain,
            rendered=packet.rendered,
            sections=[
                KgSection(
                    band=s.band,
                    node_id=s.node_id,
                    text=s.text,
                    tokens=s.tokens,
                    path=s.path,
                    start_line=s.start_line,
                    end_line=s.end_line,
                )
                for s in packet.sections
            ],
            files=[
                KgFileRef(
                    path=f.path,
                    band=f.band,
                    tokens=f.tokens,
                    node_ids=list(f.node_ids),
                    spans=[(int(a), int(b)) for a, b in f.spans],
                )
                for f in packet.files
            ],
            total_tokens=packet.total_tokens,
            band_budgets=dict(packet.band_budgets),
            coverage=float(packet.coverage),
            uncovered_terms=list(packet.uncovered_terms),
            low_confidence=bool(packet.low_confidence),
            refinement_rounds=int(packet.refinement_rounds),
        )

    async def search(self, kb_id: str, query: str, *, k: int = 10) -> list[KgSearchHit]:
        """BM25 anchor candidates for ``query`` (the UI's debug box / seed resolver)."""
        graph = await self._graph(kb_id)

        def _run() -> list[tuple[str, float]]:
            from workflow_compiler.kg.contexthub.retrieval import anchor_scored

            return list(anchor_scored(graph, query, k=k))

        scored = await asyncio.to_thread(_run)
        hits: list[KgSearchHit] = []
        for node_id, score in scored:
            node = graph.nodes.get(node_id)
            if node is None:
                continue
            hits.append(
                KgSearchHit(
                    node_id=node_id,
                    type=node.type.value,
                    name=node.name,
                    path=_node_path(node),
                    score=float(score),
                )
            )
        return hits

    async def resolve_ref(self, kb_id: str, ref: str) -> str | None:
        """Resolve a component reference to a graph node id, or ``None``.

        ``ref`` may be a node id (``mod:existing_Codebase/shared/types.py``,
        ``fn:…:provision_order``), a corpus-relative file path
        (``existing_Codebase/shared/types.py``, any suffix of one), or a bare
        symbol name (``provision_order``, ``OrderState``). Matching is exact on
        node ids, then on file paths (full or trailing suffix, ``/`` normalised),
        then on the ``fn:`` symbol name; the first hit wins. Used by the change
        validator to check that a change spec points at things that exist.
        """
        needle = ref.strip().replace("\\", "/")
        if not needle:
            return None
        graph = await self._graph(kb_id)
        if needle in graph.nodes:
            return str(needle)
        suffix = "/" + needle.lstrip("/")
        by_path: str | None = None
        by_symbol: str | None = None
        for node_id, node in graph.nodes.items():
            path = _node_path(node)
            if path is not None and by_path is None:
                norm = str(path).replace("\\", "/")
                if norm == needle or norm.endswith(suffix):
                    # Prefer the file-level node (mod:/doc:) over its chunks.
                    if node.type.value in ("Module", "Document"):
                        return str(node_id)
                    by_path = str(node_id)
            if by_symbol is None and node_id.startswith("fn:") and node_id.endswith(":" + needle):
                by_symbol = str(node_id)
        if by_path or by_symbol:
            return by_path or by_symbol
        # `fn:<file>:<symbol>` for a method / nested def (only top-level defs are
        # nodes): accept it when the file exists and defines the symbol.
        if needle.startswith("fn:") and needle.count(":") >= 2:
            _prefix, file_part, symbol = needle.split(":", 2)
            symbol = symbol.rsplit(".", 1)[-1].strip()
            module_id = await self.resolve_ref(kb_id, file_part)
            if module_id is not None and symbol:
                try:
                    text = (await self.read_file(kb_id, file_part)).text
                except Exception:
                    return None
                if re.search(rf"\b(?:def|class)\s+{re.escape(symbol)}\b", text):
                    return module_id
        return None

    async def impact(
        self, kb_id: str, seeds: Iterable[str], *, max_hops: int = 2
    ) -> list[KgImpactRow]:
        """Deterministic BFS from ``seeds`` over dependency-shaped edges.

        A seed is a node id when one exists, otherwise a search term resolved to
        its best BM25 anchors (up to 3). Rows are ordered by hop count, then id,
        so the table is stable across runs; ``via`` records which edge/node
        reached each row (the first one found in that deterministic order).
        """
        graph = await self._graph(kb_id)
        resolved: list[str] = []
        for seed in seeds:
            seed = seed.strip()
            if not seed:
                continue
            if seed in graph.nodes:
                resolved.append(seed)
                continue
            for hit in await self.search(kb_id, seed, k=3):
                if hit.node_id not in resolved:
                    resolved.append(hit.node_id)
        if not resolved:
            return []

        hops: dict[str, int] = {}
        via: dict[str, str] = {}
        queue: deque[str] = deque()
        for seed in resolved:
            if seed not in hops:
                hops[seed] = 0
                via[seed] = "seed"
                queue.append(seed)
        graph.build_index()
        while queue:
            current = queue.popleft()
            depth = hops[current]
            if depth >= max_hops:
                continue
            current_node = graph.nodes[current]
            neighbours: list[tuple[str, str]] = []
            for edge, other in graph.incident(current):
                etype = edge.type.value
                if etype == "CONTAINS":
                    # Only follow containment downwards from a file-level node.
                    if edge.src != current or current_node.type.value in _CONTAINER_TYPES:
                        continue
                elif etype not in _IMPACT_EDGE_TYPES:
                    continue
                neighbours.append((other, f"{etype} ← {current}"))
            for other, label in sorted(neighbours):
                if other not in hops:
                    hops[other] = depth + 1
                    via[other] = label
                    queue.append(other)

        rows: list[KgImpactRow] = []
        for node_id in sorted(hops, key=lambda n: (hops[n], n)):
            node = graph.nodes.get(node_id)
            if node is None:
                continue
            rows.append(
                KgImpactRow(
                    node_id=node_id,
                    type=node.type.value,
                    name=node.name,
                    path=_node_path(node),
                    hops=hops[node_id],
                    via=via.get(node_id, ""),
                )
            )
        return rows

    async def catalog(self, kb_id: str) -> KbCatalog:
        """Business ids present in the graph, computed live (also stored on the KB)."""
        graph = await self._graph(kb_id)
        return await asyncio.to_thread(self._catalog, graph, self.hub_dir(kb_id))

    async def graph_summary(self, kb_id: str, *, top: int = 15) -> KgGraphSummary:
        graph = await self._graph(kb_id)
        by_type = Counter(n.type.value for n in graph.nodes.values())
        edges_by_type = Counter(e.type.value for e in graph.edges)
        degree: Counter[str] = Counter()
        for edge in graph.edges:
            degree[edge.src] += 1
            degree[edge.dst] += 1
        top_nodes = [
            KgNodeBrief(
                node_id=node_id,
                type=graph.nodes[node_id].type.value,
                name=graph.nodes[node_id].name,
                degree=count,
            )
            for node_id, count in sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))
            if node_id in graph.nodes and graph.nodes[node_id].type.value not in _CONTAINER_TYPES
        ][:top]
        return KgGraphSummary(
            nodes=len(graph.nodes),
            edges=len(graph.edges),
            by_type=dict(sorted(by_type.items())),
            edges_by_type=dict(sorted(edges_by_type.items())),
            top_nodes=top_nodes,
        )

    # ------------------------------------------------------------ corpus files
    def _resolve_corpus_path(self, kb_id: str, rel_path: str) -> Path:
        corpus = self.corpus_dir(kb_id).resolve()
        candidate = (corpus / rel_path.replace("\\", "/")).resolve()
        if candidate != corpus and corpus not in candidate.parents:
            raise StateNotFoundError(f"No file {rel_path!r} in knowledge base {kb_id!r}.")
        return candidate

    async def list_files(self, kb_id: str) -> list[str]:
        """Corpus files as POSIX paths relative to ``corpus/`` (sorted)."""
        corpus = self.corpus_dir(kb_id)
        if not corpus.is_dir():
            raise StateNotFoundError(f"No knowledge base with id {kb_id!r}.")

        def _list() -> list[str]:
            return sorted(
                p.relative_to(corpus).as_posix() for p in corpus.rglob("*") if p.is_file()
            )

        return await asyncio.to_thread(_list)

    async def read_file(self, kb_id: str, rel_path: str, *, max_bytes: int = 2_000_000) -> KbFile:
        """Read one corpus file as text (binary docs are text-extracted)."""
        validate_kb_id(kb_id)
        path = self._resolve_corpus_path(kb_id, rel_path)
        if not path.is_file():
            raise StateNotFoundError(f"No file {rel_path!r} in knowledge base {kb_id!r}.")

        def _read() -> KbFile:
            from workflow_compiler.kg.contexthub.bootstrap.formats import extract_text

            size = path.stat().st_size
            if size > max_bytes:
                raise CompilationError(f"{rel_path!r} is larger than {max_bytes} bytes.")
            suffix = path.suffix.lower()
            if suffix in _TEXT_LIKE or not suffix:
                return KbFile(
                    path=rel_path,
                    size=size,
                    text=path.read_text(encoding="utf-8", errors="replace"),
                )
            return KbFile(path=rel_path, size=size, text=extract_text(path), extracted=True)

        return await asyncio.to_thread(_read)

    async def read_bytes(self, kb_id: str, rel_path: str, *, max_bytes: int = 20_000_000) -> bytes:
        """Raw bytes of one corpus file (for binary readers such as the TC matrix xlsx)."""
        validate_kb_id(kb_id)
        path = self._resolve_corpus_path(kb_id, rel_path)
        if not path.is_file():
            raise StateNotFoundError(f"No file {rel_path!r} in knowledge base {kb_id!r}.")

        def _read() -> bytes:
            if path.stat().st_size > max_bytes:
                raise CompilationError(f"{rel_path!r} is larger than {max_bytes} bytes.")
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    # ------------------------------------------------------------ graph cache
    async def _graph(self, kb_id: str) -> Any:
        validate_kb_id(kb_id)
        path = self.graph_path(kb_id)
        if not path.is_file():
            kb = await self._store.load(kb_id)  # 404 if the KB itself is gone
            raise CompilationError(
                f"Knowledge base {kb.name!r} has no graph yet (status: {kb.status})."
            )
        mtime = path.stat().st_mtime
        with self._graph_lock:
            hit = self._graphs.get(kb_id)
            if hit is not None and hit[0] == mtime:
                return hit[1]

        def _load() -> Any:
            from workflow_compiler.kg.contexthub.bootstrap.store import load
            from workflow_compiler.kg.contexthub.retrieval import invalidate_cache

            graph = load(path)
            graph.build_index()
            invalidate_cache(graph)
            return graph

        graph = await asyncio.to_thread(_load)
        with self._graph_lock:
            self._graphs[kb_id] = (mtime, graph)
        return graph

    def _cache_put(self, kb_id: str, graph: Any) -> None:
        path = self.graph_path(kb_id)
        if path.is_file():
            with self._graph_lock:
                self._graphs[kb_id] = (path.stat().st_mtime, graph)

    def invalidate(self, kb_id: str | None = None) -> None:
        with self._graph_lock:
            if kb_id is None:
                self._graphs.clear()
            else:
                self._graphs.pop(kb_id, None)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _stats(graph: Any, corpus: Path) -> KbStats:
        files = sum(1 for p in corpus.rglob("*") if p.is_file())
        return KbStats(
            nodes=len(graph.nodes),
            edges=len(graph.edges),
            by_type=dict(sorted(Counter(n.type.value for n in graph.nodes.values()).items())),
            edges_by_type=dict(sorted(Counter(e.type.value for e in graph.edges).items())),
            files=files,
        )

    @staticmethod
    def _catalog(graph: Any, hub_dir: Path | None = None) -> KbCatalog:
        buckets: dict[str, list[str]] = {
            "Epic": [],
            "UserStory": [],
            "TestCase": [],
            "Requirement": [],
        }
        for node in graph.nodes.values():
            bucket = buckets.get(node.type.value)
            if bucket is None:
                continue
            if _BUSINESS_ID_RE.match(node.id) and "." not in node.id:
                bucket.append(node.id)
        return KbCatalog(
            epics=sorted(buckets["Epic"]),
            stories=sorted(buckets["UserStory"]),
            test_cases=sorted(buckets["TestCase"]),
            requirements=sorted(buckets["Requirement"]),
            documents=_document_ids(hub_dir) if hub_dir is not None else [],
        )


_DOC_ID_RE = re.compile(r"\b(?:BRD|TDD|TP|SDD|ADR|TS)-[A-Z]{2,6}-\d{2,4}\b")


def _document_ids(hub_dir: Path) -> list[str]:
    """Document ids (``TDD-ORD-001`` …) mentioned anywhere in the extracted corpus text.

    Document nodes are keyed by path, not by the id printed inside the file, so
    the catalog scans the ingest extracts (``.contexthub/extracts/*.txt``) —
    small, already-extracted plain text — to learn which numbered documents
    exist. Deterministic and cheap; used to number successors (``TDD-ORD-002``).
    """
    extracts = hub_dir / "extracts"
    if not extracts.is_dir():
        return []
    found: set[str] = set()
    for path in sorted(extracts.glob("*.txt")):
        try:
            found.update(_DOC_ID_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:  # pragma: no cover - unreadable extract
            continue
    return sorted(found)


def _node_path(node: Any) -> str | None:
    md = node.metadata or {}
    value = md.get("path") or md.get("repo_path") or md.get("file")
    return str(value) if value else None


def remove_kb_dir(path: Path) -> None:
    """Best-effort removal of a knowledge base directory (used on failed creates)."""
    shutil.rmtree(path, ignore_errors=True)
