"""Shared identity resolution — component id ↔ code path ↔ display name.

One entity is routinely named three ways in a corpus like ``sources/``::

    CMP-OrderService   docs / components.yaml     component id
    Order Service      components.yaml ``name:``  display name
    order_service      codebase/<dir>             code path

Both the graph builder (``bootstrap.ingest``) and the fixture adapters
(``agent.adapters.mock``) have to treat those as the same thing, so the logic
lives here rather than in either of them.

Two layers, tried in order:

1. **Alias match.** Every candidate key contributes normalized forms — the key
   squashed to alphanumerics, plus the same with a leading ``CMP-``-style
   prefix removed. An exact hit wins outright. This is what preserves *word
   order*, which token scoring has already discarded: ``catalog service`` and
   ``service catalog`` both tokenize to ``["catalog"]`` (``service`` is a
   stopword), so no tokenizer change can tell ``CMP-CatalogService`` from
   ``CMP-ServiceCatalog``. Squashing keeps them distinct.

2. **Token scoring.** The original forgiving fallback, for prose that is not an
   identifier at all ("the order service", "order"). A tie returns the tied
   candidates rather than guessing — callers report the ambiguity.

Nothing here reads a repository or assumes an identifier scheme: alias forms
are derived from whatever keys the caller passes. ``ComponentMap`` accepts
explicit crosswalk entries for corpora whose names genuinely diverge.

See docs/handoff-sources-onboarding.md §2.4 and §7 for the decision record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

# Generic words that must never decide a match on their own — "service" is in
# every service name, so a query like "the service" would match everything.
STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "that", "this", "these",
    "those", "are", "was", "were", "does", "did", "has", "have", "had",
    "what", "why", "how", "when", "where", "which", "who", "please", "show",
    "about", "all", "any", "our", "your", "not", "now", "recent", "latest",
    "service", "services", "system", "systems",
})

# A short leading namespace on an identifier: CMP-, API-, US-, SVC-. Stripped
# to produce a second alias form so `CMP-OrderService` and `order_service`
# reach the same entity.
_ID_PREFIX = re.compile(r"^[a-z]{2,6}-")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

CROSSWALK_FILENAMES = ("code_crosswalk.yaml", "code_crosswalk.yml")


def norm(value: Any) -> str:
    """Lowercase and trim. The cheapest normalization, used for substring work."""
    return str(value or "").strip().lower()


def squash(value: Any) -> str:
    """Collapse to bare alphanumerics: ``CMP-Order_Service`` → ``cmporderservice``.

    This is the alias key. Separator style and casing stop mattering, but word
    *order* is preserved — which is the whole point (see the module docstring).
    """
    return _NON_ALNUM.sub("", norm(value))


def _significant(token: str) -> bool:
    return len(token) > 2 and token not in STOPWORDS


def tokens(value: Any) -> list[str]:
    """Significant tokens, split on whitespace **and** ``-``/``_``.

    Splitting on separators is what lets a code-path argument reach a
    component-id key: without it ``CMP-OrderService`` is one opaque token and
    can never match anything written another way.

    One exception, and it matters: a word containing a **digit** is kept whole.
    ``REL-NI-4.8.0`` split into fragments loses every character that
    distinguishes it from ``REL-NI-4.8.1`` — the short pieces fall below the
    length floor and only ``rel`` survives. Version and serial identifiers are
    only meaningful entire; word-shaped names are the ones worth splitting.
    """
    out: list[str] = []
    for word in norm(value).split():
        if any(ch.isdigit() for ch in word):
            if _significant(word):
                out.append(word)
            continue
        out.extend(f for f in _NON_ALNUM.split(word) if _significant(f))
    return out


def matches(haystack: Any, needle: Any) -> bool:
    """Containment match over significant tokens. Forgiving about word order and
    casing, but every significant token must appear — a single generic word can
    no longer match every record."""
    toks = tokens(needle)
    if not toks:
        return True
    hay = norm(haystack)
    return all(tok in hay for tok in toks)


def alias_forms(value: Any) -> list[str]:
    """Normalized alias forms for one identifier, most specific first.

    ``CMP-OrderService`` → ``["cmporderservice", "orderservice"]``. The
    prefix-stripped form is what bridges namespaces; the full form is tried
    first so an exact identifier never loses to a stripped near-miss.
    """
    full = squash(value)
    if not full:
        return []
    forms = [full]
    stripped = _ID_PREFIX.sub("", norm(value), count=1)
    bare = squash(stripped)
    if bare and bare != full:
        forms.append(bare)
    return forms


def alias_index(
    keys: Iterable[Any], extra: Mapping[str, str] | None = None
) -> dict[str, set[str]]:
    """Map every alias form to the key(s) that claim it.

    ``extra`` adds explicit alias → key pairs (e.g. code paths and display
    names from a crosswalk) for corpora where the names genuinely diverge and
    cannot be derived from the key alone.
    """
    index: dict[str, set[str]] = {}
    for key in keys:
        for form in alias_forms(key):
            index.setdefault(form, set()).add(str(key))
    for alias, key in (extra or {}).items():
        form = squash(alias)
        if form:
            index.setdefault(form, set()).add(str(key))
    return index


def best_key(
    keys: Any, needle: Any, *, aliases: Mapping[str, str] | None = None
) -> tuple[str | None, list[str]]:
    """Pick the key that best matches ``needle``.

    Returns ``(best, ambiguous)``: ``best`` when one key wins outright,
    otherwise the tied candidates so the caller reports them instead of
    guessing. Keys starting with ``_`` (index sidecars) are skipped.
    """
    candidates = [str(k) for k in keys if not str(k).startswith("_")]
    if not candidates:
        return None, []

    # 1. Alias match — exact, order-preserving, and decisive.
    index = alias_index(candidates, aliases)
    for form in alias_forms(needle):
        hits = index.get(form)
        if not hits:
            continue
        if len(hits) == 1:
            return next(iter(hits)), []
        return None, sorted(hits)

    # 2. Token scoring — the forgiving fallback for prose.
    toks = tokens(needle)
    if not toks:
        return None, []
    scored: list[tuple[int, str]] = []
    for key in candidates:
        hay = norm(key)
        score = sum(1 for t in toks if t in hay)
        if score:
            scored.append((score, key))
    if not scored:
        return None, []
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    top = scored[0][0]
    tied = [k for s, k in scored if s == top]
    if len(tied) == 1:
        return tied[0], []
    return None, tied


# --------------------------------------------------------------------------- #
# code_crosswalk.yaml — the declared component id ↔ code path bridge
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CrosswalkEntry:
    """One declared mapping between a code directory and a component id."""

    code_path: str
    component_id: str


def parse_crosswalk(text: str) -> list[CrosswalkEntry]:
    """Parse a ``code_crosswalk.yaml`` body into entries.

    Shape: ``{"crosswalk": [{"code_path": ..., "component_id": ...}, ...]}``;
    a bare top-level list is accepted too. Malformed or half-filled entries are
    skipped rather than raising — a corpus file must never break an ingest.
    """
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except Exception:
        return []
    rows = data.get("crosswalk") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    entries: list[CrosswalkEntry] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code_path = str(row.get("code_path") or "").strip()
        component_id = str(row.get("component_id") or "").strip()
        if not code_path or not component_id:
            continue
        pair = (code_path, component_id)
        if pair in seen:
            continue
        seen.add(pair)
        entries.append(CrosswalkEntry(code_path=code_path, component_id=component_id))
    return entries


def find_crosswalk(root: Path) -> Path | None:
    """Locate the crosswalk file at a repository root, if one exists."""
    for name in CROSSWALK_FILENAMES:
        candidate = Path(root) / name
        if candidate.is_file():
            return candidate
    return None


class ComponentMap:
    """Bidirectional component id ↔ code path lookup, plus derived aliases.

    Deliberately partial: a code directory with no crosswalk row resolves to
    ``None``. ``sources/codebase/inventory_service/`` is exactly that — an
    undocumented service kept as a drift-detection signal — and guessing a
    component id for it would destroy the signal.
    """

    def __init__(
        self,
        entries: Iterable[CrosswalkEntry],
        *,
        display_names: Mapping[str, str] | None = None,
    ) -> None:
        self.entries: list[CrosswalkEntry] = list(entries)
        self.display_names: dict[str, str] = dict(display_names or {})
        self._by_code_path: dict[str, str] = {}
        self._by_component: dict[str, str] = {}
        for entry in self.entries:
            self._by_code_path.setdefault(squash(entry.code_path), entry.component_id)
            self._by_component.setdefault(squash(entry.component_id), entry.code_path)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def component_for_code_path(self, path: Any) -> str | None:
        """Component id for a code directory, or a file path inside one.

        ``order_service``, ``codebase/order_service`` and
        ``codebase/order_service/app.py`` all resolve; ``inventory_service``
        resolves to ``None``, deliberately.
        """
        raw = str(path or "").replace("\\", "/")
        if not raw:
            return None
        segments = [s for s in raw.split("/") if s and s not in (".", "..")]
        # Longest-suffix first is wrong here — a crosswalk row names one
        # directory, so match directory segments, deepest first.
        for segment in reversed(segments):
            hit = self._by_code_path.get(squash(segment))
            if hit:
                return hit
        return None

    def code_path_for_component(self, component_id: Any) -> str | None:
        return self._by_component.get(squash(component_id))

    def aliases(self) -> dict[str, str]:
        """Alias → component id, for feeding :func:`best_key`.

        Covers the code path and (when known) the display name; the component
        id's own forms are derived from the key itself and need no entry.
        """
        out: dict[str, str] = {}
        for entry in self.entries:
            out[entry.code_path] = entry.component_id
        for component_id, name in self.display_names.items():
            if name:
                out[name] = component_id
        return out
