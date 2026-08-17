"""Declared catalogs — ``components.yaml`` and ``terms.yaml`` as typed edges.

A corpus like ``sources/`` ships two small YAML files that are *already* an
edge list, written by hand::

    components.yaml : depends_on: [CMP-ProductService, CMP-CatalogService, ...]
                      exposes:    [API-placeOrder, API-getOrder, ...]
    terms.yaml      : enforced_by: [CMP-OrderService]

Until now ingest read them the way it reads any YAML — ``yaml.safe_load`` then
``yaml.dump``, a normalization round-trip that returns a **string**. So the
graph got a 4KB text blob where the file had said something directional.

The id extractor (``idlinks.py``) recovers the *ids* from that blob, but not
the *semantics*: it can only see that ``components.yaml`` mentions both
``CMP-OrderService`` and ``CMP-ProductService``, which it records as two
lateral ``RELATES_TO`` edges from the document. That is strictly weaker than
what the file says. Measured on ``sources/`` before this module existed: all
11 Component nodes and all 10 Term nodes had **zero outgoing edges**.

This module reads the declarations back out. Direction and type come from the
field name, never from proximity — see :data:`RELATION_SEMANTICS`.

The parser is deliberately generic over the field names, because the
*convention* (a list of ids under a named key) is what generalizes; a corpus
using ``calls:`` or ``notifies:`` gets the same treatment without a code
change. Files that do not exist, do not parse, or use a shape this does not
recognize yield nothing — a corpus file must never break an ingest.

See docs/handoff-sources-onboarding.md §2.6 and §10 for the decision record.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..model.schema import EdgeType

COMPONENT_FILENAMES: tuple[str, ...] = ("components.yaml", "components.yml")
TERM_FILENAMES: tuple[str, ...] = ("terms.yaml", "terms.yml")

#: Top-level key holding the rows, tried in order. A bare top-level list works too.
COMPONENT_COLLECTIONS: tuple[str, ...] = ("components", "component")
TERM_COLLECTIONS: tuple[str, ...] = ("terms", "term", "glossary")

#: Fields carrying the human-readable body, most specific first.
COMPONENT_TEXT_FIELDS: tuple[str, ...] = ("description", "summary", "definition")
TERM_TEXT_FIELDS: tuple[str, ...] = ("definition", "description", "summary")

# What a list-of-ids field *means*. This is the whole point of the module: the
# field name is the only place the direction and the type actually live.
#
# `exposes` reuses IMPLEMENTS rather than minting an EXPOSES edge type: the
# relation is the same shape ingest already records as `Service --IMPLEMENTS-->
# Endpoint` when it parses an OpenAPI file, and IMPLEMENTS is already in
# CODE_EDGE_TYPES, so impact traversal picks it up for free.
#
# `enforced_by` points Term -> Component: the term depends on the component to
# enforce it. That keeps every edge here pointing away from the thing being
# declared, which is what makes a single generic emitter correct.
RELATION_SEMANTICS: dict[str, tuple[EdgeType, str]] = {
    "depends_on": (EdgeType.DEPENDS_ON, "depends_on"),
    "exposes": (EdgeType.IMPLEMENTS, "exposes"),
    "enforced_by": (EdgeType.DEPENDS_ON, "enforced_by"),
    "calls": (EdgeType.CALLS, "calls"),
    "notifies": (EdgeType.DEPENDS_ON, "notifies"),
    "consumes": (EdgeType.CONSUMES, "consumes"),
    "produces": (EdgeType.PRODUCES, "produces"),
}

# Row keys that are metadata about the declaration itself, not references to
# other entities. Everything else that holds a list of scalars is a relation.
_IDENTITY_FIELDS = frozenset({"id", "key", "identifier", "name", "title"})


@dataclass(frozen=True)
class Declaration:
    """One declared entity and the ids it points at.

    ``links`` is keyed by the *original* field name so the emitter can look up
    :data:`RELATION_SEMANTICS` and report an unrecognized field honestly rather
    than silently flattening it.
    """

    id: str
    name: str
    text: str
    links: Mapping[str, tuple[str, ...]]
    source_file: str = ""

    def relations(self) -> list[tuple[str, EdgeType, str, str]]:
        """``(field, edge_type, reason, target_id)`` for every recognized link."""
        out: list[tuple[str, EdgeType, str, str]] = []
        for field_name, targets in self.links.items():
            semantic = RELATION_SEMANTICS.get(field_name)
            if semantic is None:
                continue
            etype, reason = semantic
            for target in targets:
                if target and target != self.id:
                    out.append((field_name, etype, reason, target))
        return out


def _first_text(row: Mapping[str, Any], fields: Sequence[str]) -> str:
    for field_name in fields:
        value = row.get(field_name)
        if isinstance(value, str) and value.strip():
            # YAML folded scalars (`>`) arrive with hard newlines; collapse them
            # so the summary is one line, like every other summary in the graph.
            return " ".join(value.split())
    return ""


def _id_list(value: Any) -> tuple[str, ...]:
    """A list of scalar ids, or ``()`` if this field is not one.

    A nested mapping or list-of-mappings is structure this module has no
    opinion about, so it is left alone rather than stringified.
    """
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            text = str(item).strip()
            if text:
                out.append(text)
        else:
            return ()
    return tuple(dict.fromkeys(out))


def parse_declarations(
    text: str,
    *,
    collections: Sequence[str],
    text_fields: Sequence[str],
    source_file: str = "",
) -> list[Declaration]:
    """Parse a declared-catalog YAML body into :class:`Declaration` rows.

    Accepts ``{<collection>: [row, ...]}`` or a bare top-level list. A row
    without an id is skipped; a duplicate id keeps the first spelling, matching
    how the crosswalk parser resolves the same conflict.
    """
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except Exception:
        return []

    rows: Any = None
    if isinstance(data, dict):
        for key in collections:
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    elif isinstance(data, list):
        rows = data
    if not isinstance(rows, list):
        return []

    out: list[Declaration] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = ""
        for key in ("id", "key", "identifier"):
            value = row.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                identifier = str(value).strip()
                break
        if not identifier or identifier.casefold() in seen:
            continue
        seen.add(identifier.casefold())

        links: dict[str, tuple[str, ...]] = {}
        for field_name, value in row.items():
            name = str(field_name).strip().casefold()
            if name in _IDENTITY_FIELDS or name in text_fields:
                continue
            targets = _id_list(value)
            if targets:
                links[name] = targets

        name_value = row.get("name") or row.get("title") or identifier
        out.append(Declaration(
            id=identifier,
            name=" ".join(str(name_value).split()) or identifier,
            text=_first_text(row, text_fields),
            links=links,
            source_file=source_file,
        ))
    return out


def find_catalog(root: Path, filenames: Iterable[str]) -> Path | None:
    """Locate a declared-catalog file at a repository root, if one exists."""
    for name in filenames:
        candidate = Path(root) / name
        if candidate.is_file():
            return candidate
    return None


@dataclass
class CatalogStats:
    """What the catalogs contributed — reported by ingest."""

    components: int = 0
    terms: int = 0
    #: Nodes given a declared name/description they did not have before.
    enriched: int = 0
    #: Declarations with no pre-existing node, created here.
    created: int = 0
    typed_edges: int = 0
    #: Weaker RELATES_TO edges removed in favour of a typed edge (Phase 4.3).
    replaced_mentions: int = 0
    #: Targets naming an id that reached no node — a real dangling reference.
    unresolved: int = 0
    #: Relations whose typed edge was already present.
    duplicate: int = 0

    def summary(self) -> str:
        parts = [f"{self.typed_edges} typed edges from {self.components} components"]
        if self.terms:
            parts.append(f"{self.terms} terms")
        if self.replaced_mentions:
            parts.append(f"{self.replaced_mentions} mentions replaced")
        if self.unresolved:
            parts.append(f"{self.unresolved} unresolved")
        return ", ".join(parts)
