"""KgGrounder — turn a piece of document text into a knowledge-graph prompt block.

The spec pipeline's prompts (segmentation, discovery, fact extraction, Temporal
design) carry an optional ``{{ kg_context }}`` placeholder. When a project is
compiled with a knowledge base, :class:`KgGrounder` retrieves a context packet
for the text about to be analysed and renders it as a self-contained block that
tells the model to **prefer the real names and paths** the corpus uses. When no
grounder is set the placeholder renders to nothing and every prompt is exactly
what it was before Phase 3 — the grounder is purely additive.

Only :class:`~workflow_compiler.kg.service.KgService` is used (the one KG
surface); the vendored Context Hub code is never imported here.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from workflow_compiler.change.bcr import seed_terms
from workflow_compiler.kg.models import KgPacket
from workflow_compiler.kg.service import KgService

#: Default token budget for one grounding packet (a discovery/facts prompt on a
#: ~10 KB segment plus a 3 000-token packet still fits comfortably).
DEFAULT_GROUNDING_BUDGET = 3000

#: Characters of the analysed text folded into the retrieval query (after the
#: identifiers). BM25 anchoring works on terms, so the query is identifiers
#: first, then a slice of prose for the anchor's tie-breakers.
_QUERY_PROSE_CHARS = 1200

_BLOCK_HEAD = (
    "KNOWLEDGE-GRAPH CONTEXT — prefer these real names / paths\n"
    "The following excerpts come from the organisation's knowledge base{kb} — its "
    "existing code, tests, diagrams and business documents. When the document below "
    "names an activity, workflow, state, type, signal, query, system, module or test "
    "that also appears here, use EXACTLY the name / path used here (e.g. the Python "
    "identifier `provision_order`, the state `PARTIALLY_DISPATCHED`, the module "
    "`workflows/order_workflow.py`); do not paraphrase or invent alternatives for "
    "things named here. Treat this context as background: it tells you what already "
    "exists — the document is still the source of truth for what the workflow does.\n"
    "--- KNOWLEDGE GRAPH CONTEXT ---\n"
)
_BLOCK_TAIL = "--- END KNOWLEDGE GRAPH CONTEXT ---\n\n"

_WS = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class GroundingResult:
    """One rendered grounding block plus its visible provenance."""

    block: str
    sources: list[str] = field(default_factory=list)
    coverage: float = 1.0
    low_confidence: bool = False
    total_tokens: int = 0
    seeds: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """True when retrieval found nothing worth prepending."""
        return not self.block


def source_lines(packet: KgPacket) -> list[str]:
    """``path — lines a-b, c-d`` per dereferenced file, in packet order."""
    lines: list[str] = []
    for ref in packet.files:
        spans = ", ".join(f"{a}-{b}" for a, b in ref.spans)
        lines.append(f"{ref.path} — lines {spans}" if spans else ref.path)
    return lines


def grounding_query(text: str, *, max_chars: int = _QUERY_PROSE_CHARS) -> str:
    """Build the retrieval query for ``text``: identifiers first, then a prose slice.

    Deterministic; reuses the change-request seed extractor so the same paths,
    snake_case / CamelCase identifiers, UPPER_SNAKE states and business ids that
    seed impact analysis anchor the grounding packet.
    """
    terms = seed_terms(text, [])
    prose = _WS.sub(" ", text.strip())[:max_chars]
    return (" ".join(terms) + "\n" + prose).strip()


class KgGrounder:
    """Retrieve knowledge-graph context for text and render it as a prompt block.

    Bound to one knowledge base. Results are cached per (text, budget) so the
    discovery and fact-extraction prompts of the same segment share one
    retrieval, and repeated review passes never re-query the graph.
    """

    def __init__(
        self,
        kg: KgService,
        kb_id: str,
        *,
        kb_name: str = "",
        budget: int = DEFAULT_GROUNDING_BUDGET,
        max_hops: int = 2,
    ) -> None:
        """Bind to ``kb_id`` on ``kg`` with a default token ``budget`` per packet."""
        self._kg = kg
        self._kb_id = kb_id
        self._kb_name = kb_name
        self._budget = budget
        self._max_hops = max_hops
        self._cache: dict[str, GroundingResult] = {}
        #: Every distinct source line seen so far, in first-seen order (the
        #: project's visible grounding record is assembled from this).
        self.sources_seen: dict[str, None] = {}
        self.min_coverage: float | None = None
        self.any_low_confidence: bool = False

    @property
    def kb_id(self) -> str:
        """The bound knowledge base id."""
        return self._kb_id

    @property
    def kb_name(self) -> str:
        """The bound knowledge base display name ('' when unknown)."""
        return self._kb_name

    @property
    def kg(self) -> KgService:
        """The knowledge-graph service this grounder queries."""
        return self._kg

    async def context_for(self, text: str, budget: int | None = None) -> GroundingResult:
        """The grounding block for ``text`` (cached), or an empty result.

        Never raises into the pipeline: a retrieval failure yields an empty
        block, so a broken graph degrades to an ungrounded compile rather than
        a failed one (the caller records the warning).
        """
        used = budget or self._budget
        key = hashlib.sha256(f"{used}\x00{text}".encode()).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            packet = await self._kg.retrieve(
                self._kb_id, grounding_query(text), budget=used, max_hops=self._max_hops
            )
        except Exception:
            result = GroundingResult(block="")
            self._cache[key] = result
            return result
        result = self.render(packet)
        for line in result.sources:
            self.sources_seen.setdefault(line, None)
        if self.min_coverage is None or result.coverage < self.min_coverage:
            self.min_coverage = result.coverage
        self.any_low_confidence = self.any_low_confidence or result.low_confidence
        self._cache[key] = result
        return result

    async def block_for(self, text: str, budget: int | None = None) -> str | None:
        """Convenience: the block string, or ``None`` when nothing was retrieved."""
        result = await self.context_for(text, budget)
        return None if result.empty else result.block

    def render(self, packet: KgPacket) -> GroundingResult:
        """Render a retrieved packet as the prompt block (pure)."""
        body = packet.rendered.strip()
        if not body:
            return GroundingResult(block="", coverage=packet.coverage, seeds=list(packet.seeds))
        kb = f' "{self._kb_name}"' if self._kb_name else ""
        block = _BLOCK_HEAD.format(kb=kb) + body + "\n" + _BLOCK_TAIL
        return GroundingResult(
            block=block,
            sources=source_lines(packet),
            coverage=packet.coverage,
            low_confidence=packet.low_confidence,
            total_tokens=packet.total_tokens,
            seeds=list(packet.seeds),
        )


__all__ = [
    "DEFAULT_GROUNDING_BUDGET",
    "GroundingResult",
    "KgGrounder",
    "grounding_query",
    "source_lines",
]
