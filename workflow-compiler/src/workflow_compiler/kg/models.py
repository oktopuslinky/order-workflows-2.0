"""Pydantic models for knowledge bases and what the graph answers with.

The graph itself stays in Context Hub's own JSON (``.contexthub/graph.json``);
these models are the app-facing record of a knowledge base plus the typed
projections of retrieval results, so the API, CLI and later phases never touch
the vendored dataclasses directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

KnowledgeBaseStatus = Literal["ingesting", "ready", "failed"]


def _now() -> datetime:
    return datetime.now(UTC)


class KbSource(BaseModel):
    """Where the corpus came from."""

    kind: Literal["zip", "path"] = "zip"
    filename: str | None = Field(default=None, description="Uploaded zip name or source folder.")


class KbStats(BaseModel):
    """Graph size, as recorded at the last successful index."""

    nodes: int = 0
    edges: int = 0
    by_type: dict[str, int] = Field(default_factory=dict, description="Node counts by NodeType.")
    edges_by_type: dict[str, int] = Field(default_factory=dict)
    files: int = Field(default=0, description="Corpus files on disk (all extensions).")


class KbCatalog(BaseModel):
    """Business ids declared in the corpus (used later to number new artifacts)."""

    epics: list[str] = Field(default_factory=list)
    stories: list[str] = Field(default_factory=list)
    test_cases: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    documents: list[str] = Field(
        default_factory=list,
        description="Document ids found in the corpus text (BRD-ORD-001, TDD-ORD-001, TP-ORD-001 …).",
    )


class KnowledgeBase(BaseModel):
    """A persisted knowledge base: corpus on disk + Context Hub graph + metadata."""

    kb_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    owner_id: str | None = None
    root_dir: str = Field(
        default="",
        description="Absolute directory holding corpus/ and .contexthub/ (set by the store).",
    )
    source: KbSource = Field(default_factory=KbSource)
    status: KnowledgeBaseStatus = "ingesting"
    error: str | None = Field(default=None, description="Why the last index failed, if it did.")
    stats: KbStats = Field(default_factory=KbStats)
    indexed_at: datetime | None = None
    llm_enriched: bool = False
    provider_used: str | None = Field(
        default=None, description="Provider name that ran enrichment (None = static only)."
    )
    model_used: str | None = None
    catalog: KbCatalog = Field(default_factory=KbCatalog)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


class KgSection(BaseModel):
    """One dereferenced piece of the corpus inside a packet."""

    band: str
    node_id: str
    text: str
    tokens: int
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class KgFileRef(BaseModel):
    """A corpus file the packet drew from, with the line spans it used."""

    path: str
    band: str
    tokens: int = 0
    node_ids: list[str] = Field(default_factory=list)
    spans: list[tuple[int, int]] = Field(default_factory=list)


class KgPacket(BaseModel):
    """A grounded context packet for a prompt (``rendered`` goes into LLM prompts)."""

    prompt: str
    seeds: list[str] = Field(default_factory=list)
    focus_domain: str | None = None
    rendered: str = ""
    sections: list[KgSection] = Field(default_factory=list)
    files: list[KgFileRef] = Field(default_factory=list)
    total_tokens: int = 0
    band_budgets: dict[str, int] = Field(default_factory=dict)
    coverage: float = 1.0
    uncovered_terms: list[str] = Field(default_factory=list)
    low_confidence: bool = False
    refinement_rounds: int = 0


class KgImpactRow(BaseModel):
    """One node reached by the deterministic impact traversal."""

    node_id: str
    type: str
    name: str
    path: str | None = None
    hops: int
    via: str = Field(default="", description="`EDGE_TYPE ← from-node-id` that reached it.")


class KgSearchHit(BaseModel):
    """A BM25 anchor candidate for a query."""

    node_id: str
    type: str
    name: str
    path: str | None = None
    score: float


class KgNodeBrief(BaseModel):
    node_id: str
    type: str
    name: str
    degree: int


class KgGraphSummary(BaseModel):
    """Counts by type plus the best-connected nodes — the KB page's overview."""

    nodes: int
    edges: int
    by_type: dict[str, int]
    edges_by_type: dict[str, int]
    top_nodes: list[KgNodeBrief]


class KbFile(BaseModel):
    """A corpus file read back through the service (text-extracted for docx/xlsx/pdf)."""

    path: str
    size: int
    text: str
    extracted: bool = Field(
        default=False, description="True when the text was extracted from a binary format."
    )
