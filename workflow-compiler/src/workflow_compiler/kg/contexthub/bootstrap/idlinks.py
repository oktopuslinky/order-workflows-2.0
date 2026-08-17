"""Recover the ID web that threads a corpus's prose into real nodes and edges.

Corpora like ``sources/`` are densely cross-referenced by convention rather than
by structure — seven id families (``CMP-``, ``API-``, ``US-``, ``REQ-``,
``TC-``, ``EPIC-``, ``TERM-``) appear in every format, in running text::

    openapi_order_service.yaml : "Implements US-102. Calls API-voidInvoice."
    user_stories_orders.csv    : linked_to=REQ-001-003
    components.yaml            : exposes:[API-placeOrder]

That signal is deterministic and high-precision, and until now it reached the
graph only as characters inside a Document blob.

**One node per id, not one edge per pair.** The obvious reading — link every
pair of artifacts that share an id — is quadratic in the worst place: measured
on ``sources/`` it yields 6,882 edges against a 474-edge graph, which is the
"near-complete and therefore useless" failure mode. Promoting the id itself to
a node costs 955 edges instead, and gives the id an identity that retrieval,
impact traversal and the AIFQE traceability spine can all address directly.

**Reuse before minting.** An id that already has a node in the graph binds to
it rather than growing a duplicate: ``CMP-*`` to the Component nodes the
crosswalk declared, ``API-*`` to the Endpoint nodes ``_parse_openapi`` built
from ``operationId``. So ``components.yaml exposes: API-placeOrder`` and the
OpenAPI operation ``placeOrder`` become the *same node*, not two artifacts that
happen to share a token. Ids with no existing node are minted and marked
``declared: False`` — that flag is the drift signal: ``API-getInvoice`` is
called by two design docs and specified by no OpenAPI file.

Direction comes from structure, never from prose. ``linked_to`` columns in the
backlog exports give a real ``TC → US → REQ`` chain; a mention gives only
``RELATES_TO``.

See docs/handoff-sources-onboarding.md §2.7 and §9 for the decision record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..model.schema import EdgeType, NodeType

# The default families. Configurable because the convention, not the specific
# prefixes, is what generalizes — another corpus may use SVC-/FEAT-/BUG-.
DEFAULT_ID_PREFIXES: tuple[str, ...] = ("CMP", "API", "US", "REQ", "TC", "EPIC", "TERM")

# Prefix → the type a *minted* node gets. A prefix with no entry still yields
# mention edges; it just has no strong opinion about what the id is, and falls
# back to DATA_ARTIFACT.
NODE_TYPE_BY_PREFIX: dict[str, NodeType] = {
    "CMP": NodeType.COMPONENT,
    "API": NodeType.ENDPOINT,
    "REQ": NodeType.REQUIREMENT,
    "US": NodeType.USER_STORY,
    "TC": NodeType.TEST_CASE,
    "EPIC": NodeType.EPIC,
    "TERM": NodeType.TERM,
}

# What a `linked_to` reference *means*, by the prefixes at each end. Only the
# pairs a backlog actually produces are named; anything else is still a real
# declared dependency, just an unlabelled one.
DEFAULT_LINK_SEMANTICS: dict[tuple[str, str], tuple[EdgeType, str]] = {
    ("TC", "US"): (EdgeType.DEPENDS_ON, "verifies"),
    ("TC", "REQ"): (EdgeType.DEPENDS_ON, "verifies"),
    ("US", "REQ"): (EdgeType.DEPENDS_ON, "satisfies"),
    ("US", "EPIC"): (EdgeType.DEPENDS_ON, "belongs_to"),
    ("EPIC", "US"): (EdgeType.CONTAINS, "backlog"),
}
FALLBACK_LINK: tuple[EdgeType, str] = (EdgeType.DEPENDS_ON, "linked_to")

# Trailing punctuation is swallowed by the id pattern because `.` and `-` are
# legal *inside* an id (`REQ-001-002`, `REL-NI-4.8.0`). Stripping it at the end
# is not cosmetic: on `sources/` it collapses 280 apparent ids to 184, because
# `CMP-BillingService.` at the end of a sentence would otherwise be a distinct
# entity from `CMP-BillingService` — in 21 files.
_TRAILING_PUNCT = re.compile(r"[.\-_]+$")

# Column headers that carry a declared reference to another backlog item.
LINKED_TO_HEADERS = frozenset({
    "linked_to", "linked to", "linkedto", "links_to", "link_to",
    "traces_to", "covers", "verifies",
})
_ID_HEADERS = frozenset({"id", "key", "identifier"})


@dataclass
class IdLinkOptions:
    """Extraction settings, including the §4.3 noise guards.

    The guards exist because an unconstrained id extractor degrades toward a
    complete graph. In the id-as-node model a *widespread* id is informative
    rather than noisy (``CMP-BillingService`` in 44 of 88 files is the real
    shape of the corpus), so ``max_file_ratio`` is a backstop against
    boilerplate — a token in essentially every file distinguishes nothing —
    while the per-node caps are what actually bound growth.
    """

    prefixes: tuple[str, ...] = DEFAULT_ID_PREFIXES
    #: Minimum length of the part after the prefix. Rejects `TC-1`, keeps `API-01`.
    min_local_len: int = 2
    #: Drop ids appearing in more than this fraction of scanned artifacts.
    max_file_ratio: float = 0.9
    #: Cap artifacts linked to one id node (keeps the id, sheds the long tail).
    max_links_per_id: int = 64
    #: Cap distinct ids linked from one artifact. Set well above real document
    #: density (``sources/`` peaks at 70 for a change record that lists every
    #: affected API; the median artifact has 8) so this only ever fires on
    #: something pathological — a generated index of the whole id space, say.
    #: A legitimately dense document is signal, not noise.
    max_ids_per_artifact: int = 128
    link_semantics: dict[tuple[str, str], tuple[EdgeType, str]] = field(
        default_factory=lambda: dict(DEFAULT_LINK_SEMANTICS)
    )


def compile_pattern(prefixes: tuple[str, ...] = DEFAULT_ID_PREFIXES) -> re.Pattern[str]:
    """Case-sensitive `PREFIX-Local` matcher.

    Case-sensitivity is a noise guard in itself: lowercase ``us-east-1`` and
    ``tc-`` fragments in config and prose are not backlog ids. The convention
    these corpora use is uppercase, without exception.
    """
    # Longest-first so `EPIC` is not shadowed by a hypothetical `EP` prefix.
    alt = "|".join(sorted((re.escape(p) for p in prefixes), key=len, reverse=True))
    return re.compile(rf"\b({alt})-([A-Za-z0-9][A-Za-z0-9_.-]*)")


def prefix_of(identifier: str) -> str:
    return identifier.split("-", 1)[0]


def find_ids(
    text: str,
    pattern: re.Pattern[str],
    *,
    min_local_len: int = 2,
) -> list[str]:
    """Every distinct id in ``text``, in first-appearance order."""
    seen: dict[str, str] = {}
    for match in pattern.finditer(text):
        local = _TRAILING_PUNCT.sub("", match.group(2))
        if len(local) < min_local_len or not any(c.isalnum() for c in local):
            continue
        identifier = f"{match.group(1)}-{local}"
        # Fold case variants onto the first spelling seen so `API-placeOrder`
        # and `API-placeorder` cannot become two entities.
        seen.setdefault(identifier.casefold(), identifier)
    return list(seen.values())


def parse_linked_rows(
    text: str,
    pattern: re.Pattern[str],
    *,
    min_local_len: int = 2,
) -> list[tuple[str, str]]:
    """Declared ``(source_id, target_id)`` pairs from a tabular extract.

    Both CSV and XLSX reach us as ``formats.py`` renders them — one row per
    line, cells joined by `` | `` — so a single parser covers both. A row is
    only read when its cell count matches its header exactly, which is what
    keeps a stray `|` inside free text from shifting every column.
    """
    header: list[str] | None = None
    id_idx = link_idx = -1
    pairs: list[tuple[str, str]] = []

    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        lowered = [c.casefold() for c in cells]

        candidate_id = next((i for i, c in enumerate(lowered) if c in _ID_HEADERS), -1)
        candidate_link = next((i for i, c in enumerate(lowered) if c in LINKED_TO_HEADERS), -1)
        if candidate_id >= 0 and candidate_link >= 0:
            header, id_idx, link_idx = cells, candidate_id, candidate_link
            continue

        if header is None or len(cells) != len(header):
            continue
        row_ids = find_ids(cells[id_idx], pattern, min_local_len=min_local_len)
        if not row_ids:
            continue
        source = row_ids[0]
        for target in find_ids(cells[link_idx], pattern, min_local_len=min_local_len):
            if target != source:
                pairs.append((source, target))
    return pairs


@dataclass
class IdScanStats:
    """What the scan found and what the guards removed — reported by ingest."""

    artifacts: int = 0
    ids_found: int = 0
    ids_kept: int = 0
    dropped_too_common: int = 0
    dropped_artifact_cap: int = 0
    dropped_link_cap: int = 0
    declared_links: int = 0
    #: Ids with no pre-existing node, given one here (`declared: False`).
    minted_nodes: int = 0
    #: Directed edges from a `linked_to` column.
    link_edges: int = 0
    #: Lateral artifact → id edges.
    mention_edges: int = 0

    def summary(self) -> str:
        return (
            f"{self.ids_kept} ids ({self.minted_nodes} minted), "
            f"{self.mention_edges} mention + {self.link_edges} declared edges"
        )


class IdIndex:
    """Accumulates id mentions and declared links while files stream past.

    Scanning during ingest's existing file loops keeps the extracted text out
    of memory — only the id sets survive, which is what makes this affordable
    on a repo far larger than ``sources/``.
    """

    def __init__(self, options: IdLinkOptions | None = None) -> None:
        self.options = options or IdLinkOptions()
        self.pattern = compile_pattern(self.options.prefixes)
        self.mentions: dict[str, set[str]] = {}
        self.links: dict[tuple[str, str], None] = {}
        self.stats = IdScanStats()
        self._artifacts: set[str] = set()

    def scan(self, node_id: str, text: str, *, tabular: bool = False) -> None:
        if not text:
            return
        self._artifacts.add(node_id)
        opts = self.options
        ids = find_ids(text, self.pattern, min_local_len=opts.min_local_len)
        if len(ids) > opts.max_ids_per_artifact:
            self.stats.dropped_artifact_cap += len(ids) - opts.max_ids_per_artifact
            # First-appearance order, not alphabetical: `sorted()` would always
            # discard the alphabetically-last prefixes, silently starving `US-`
            # and `TERM-` of edges whenever the cap bites. `find_ids` already
            # returns document order, which is stable across runs and carries
            # no prefix bias.
            ids = ids[: opts.max_ids_per_artifact]
        for identifier in ids:
            self.mentions.setdefault(identifier, set()).add(node_id)
        if tabular:
            for pair in parse_linked_rows(text, self.pattern, min_local_len=opts.min_local_len):
                self.links.setdefault(pair, None)

    def finalize(self) -> dict[str, set[str]]:
        """Apply the corpus-wide guards; return the surviving id → artifacts map."""
        opts = self.options
        self.stats.artifacts = len(self._artifacts)
        self.stats.ids_found = len(self.mentions)
        self.stats.declared_links = len(self.links)
        ceiling = max(1, int(len(self._artifacts) * opts.max_file_ratio))

        kept: dict[str, set[str]] = {}
        for identifier, artifacts in self.mentions.items():
            if len(artifacts) > ceiling:
                self.stats.dropped_too_common += 1
                continue
            if len(artifacts) > opts.max_links_per_id:
                self.stats.dropped_link_cap += len(artifacts) - opts.max_links_per_id
                artifacts = set(sorted(artifacts)[: opts.max_links_per_id])
            kept[identifier] = artifacts
        self.stats.ids_kept = len(kept)
        return kept
