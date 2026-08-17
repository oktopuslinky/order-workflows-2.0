"""Business-id numbering from the knowledge base's catalog (deterministic).

The drafting model never picks ids. The engine reads
:class:`~workflow_compiler.kg.models.KbCatalog` — the ids that already exist in
the corpus — and mints the next free ones: ``EPIC-002`` after ``EPIC-001``
(``EPIC-001-A`` counts as 1), ``US-008`` after ``US-001..007``, ``TC-18`` after
``TC-17``, ``TDD-ORD-002`` after ``TDD-ORD-001``. Widths follow the existing
ids so new ones sort next to old ones.
"""

from __future__ import annotations

import re

from workflow_compiler.kg.models import KbCatalog
from workflow_compiler.models.change import AssignedIds

_NUMBERED = re.compile(r"^([A-Z]+(?:-[A-Z]+)*)-(\d+)")


def _next_id(existing: list[str], prefix: str, *, default_width: int = 3) -> str:
    """``prefix-NNN`` one past the highest number seen for ``prefix``."""
    best = 0
    width = default_width
    for value in existing:
        match = _NUMBERED.match(value.strip())
        if not match or match.group(1) != prefix:
            continue
        number = match.group(2)
        best = max(best, int(number))
        width = len(number)
    return f"{prefix}-{best + 1:0{width}d}"


def next_epic_id(catalog: KbCatalog) -> str:
    return _next_id(catalog.epics, "EPIC")


def next_story_id(catalog: KbCatalog, *, offset: int = 0) -> str:
    base = _next_id(catalog.stories, "US")
    match = _NUMBERED.match(base)
    assert match is not None
    number = int(match.group(2)) + offset
    return f"US-{number:0{len(match.group(2))}d}"


def story_ids(catalog: KbCatalog, count: int, *, already: list[str] | None = None) -> list[str]:
    """``count`` consecutive story ids after the catalog's (and ``already``'s) last."""
    known = list(catalog.stories) + list(already or [])
    first = _next_id(known, "US")
    match = _NUMBERED.match(first)
    assert match is not None
    start, width = int(match.group(2)), len(match.group(2))
    return [f"US-{start + i:0{width}d}" for i in range(count)]


def next_test_case_id(catalog: KbCatalog) -> str:
    return _next_id(catalog.test_cases, "TC", default_width=2)


def next_document_id(catalog: KbCatalog, family: str, *, fallback_family: str = "TDD-ORD") -> str:
    """Next id in a document family (``TDD-ORD`` → ``TDD-ORD-002``).

    ``family`` is the ``PREFIX-CODE`` part; when the catalog knows no document
    of that family the id starts at 001 (``TDD-ORD-001`` for a fresh corpus).
    """
    fam = family or fallback_family
    return _next_id(catalog.documents, fam)


def prior_document_id(catalog: KbCatalog, family: str) -> str | None:
    """The highest existing id of ``family`` (the document being superseded)."""
    best: tuple[int, str] | None = None
    for value in catalog.documents:
        match = _NUMBERED.match(value)
        if match and match.group(1) == family:
            n = int(match.group(2))
            if best is None or n > best[0]:
                best = (n, value)
    return best[1] if best else None


def tdd_family(catalog: KbCatalog, target_hint: str | None) -> str:
    """Pick the TDD family: the one named in the BCR (``TDD-ORD-001``) or the catalog's."""
    if target_hint:
        match = re.search(r"\b(TDD-[A-Z]{2,6})-\d+\b", target_hint)
        if match:
            return match.group(1)
    for value in catalog.documents:
        match = _NUMBERED.match(value)
        if match and match.group(1).startswith("TDD-"):
            return match.group(1)
    return "TDD-ORD"


def assign_ids(catalog: KbCatalog, *, target_hint: str | None = None) -> AssignedIds:
    """Reserve the epic and TDD ids (stories are minted when the story map exists)."""
    family = tdd_family(catalog, target_hint)
    prior_epic = None
    epics = sorted(catalog.epics)
    if epics:
        # The plain highest-numbered epic (EPIC-001, not EPIC-001-A).
        plain = [e for e in epics if re.fullmatch(r"EPIC-\d+", e)]
        prior_epic = (plain or epics)[-1]
    return AssignedIds(
        epic_id=next_epic_id(catalog),
        tdd_id=next_document_id(catalog, family),
        next_test_case=next_test_case_id(catalog),
        prior_epic_id=prior_epic,
        prior_tdd_id=prior_document_id(catalog, family),
    )
