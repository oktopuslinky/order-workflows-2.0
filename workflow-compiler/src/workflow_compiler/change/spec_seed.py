"""Deterministic change-spec seed from an approved change request (no LLM).

Phase 3's ``ChangeSpecAgent`` starts from the change request's parsed impact
analysis (its ``AffectedItem`` rows) and the TDD's per-section Existing /
Proposed texts; this module builds those seed :class:`ComponentChange` rows.
"""

from __future__ import annotations

import re

from workflow_compiler.change.parse import ArtifactParseError, parse_impact, parse_tdd
from workflow_compiler.models import ComponentChange, Provenance
from workflow_compiler.models.change import ChangeRequest, TddDoc
from workflow_compiler.spec.change_ingest import coerce_change_type, coerce_kind

_PATHISH = re.compile(r"^[\w./-]+\.\w+$")
_MAX_SNIPPET = 600


def _snippet(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _MAX_SNIPPET else text[: _MAX_SNIPPET - 1].rstrip() + "…"


def _section_texts(tdd: TddDoc | None, name: str) -> tuple[str, str]:
    """(existing, proposed) from the first TDD section that mentions ``name``."""
    if tdd is None:
        return "", ""
    needle = name.strip().lower()
    tail = re.split(r"[/:]", needle)[-1]
    for section in tdd.sections:
        haystack = (section.existing + "\n" + section.proposed).lower()
        if needle in haystack or (tail and tail in haystack):
            return _snippet(section.existing), _snippet(section.proposed)
    return "", ""


def seed_components(cr: ChangeRequest) -> list[ComponentChange]:
    """Seed rows from the CR's impact analysis (+ TDD texts); empty when unparsable."""
    impact_md = cr.artifacts.impact.markdown
    if not impact_md.strip():
        return []
    try:
        impact = parse_impact(impact_md)
    except ArtifactParseError:
        return []
    tdd: TddDoc | None = None
    if cr.artifacts.tdd.markdown.strip():
        try:
            tdd = parse_tdd(cr.artifacts.tdd.markdown)
        except ArtifactParseError:
            tdd = None
    seeds: list[ComponentChange] = []
    seen: set[str] = set()
    for item in impact.affected:
        name = item.ref.strip().strip("`")
        if not name:
            continue
        kind = coerce_kind(item.kind)
        key = f"{kind.value}:{name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        path = item.kg_ref.strip() or (name if _PATHISH.match(name) else "")
        existing, proposed = _section_texts(tdd, name)
        seeds.append(
            ComponentChange(
                name=name,
                kind=kind,
                path=path,
                existing=existing,
                proposed=proposed or item.rationale.strip(),
                change_type=coerce_change_type(item.change_type),
                provenance=Provenance.DOCUMENT_GROUNDED,
            )
        )
    return seeds


__all__ = ["seed_components"]
