"""Deterministic reading of a business-change document (no LLM).

Given the plain text of a BCR (``DocumentParserFactory`` output for a
``.docx``, or raw markdown/text), extract:

* the metadata block (``Document ID: BCR-001`` … ``Target Workflow: …``),
* the numbered requirements (``BCR-01-03 | The system shall …``),
* *seed terms* for the knowledge-graph impact traversal — code paths,
  identifiers, doc-section references and UPPER_SNAKE states mentioned in the
  document (mostly its "Impact on Existing Design" section),
* a title.

Everything here is regex + heuristics on purpose: the change request's own
structure is the ground truth and must not depend on a model's reading of it.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from workflow_compiler.models.change import BcrMeta, ChangeRequirement

_META_LABELS: dict[str, str] = {
    "document id": "doc_id",
    "doc id": "doc_id",
    "id": "doc_id",
    "status": "status",
    "requested by": "requested_by",
    "requester": "requested_by",
    "date raised": "date_raised",
    "date": "date_raised",
    "target workflow": "target_workflow",
    "target": "target_workflow",
}

_META_LINE = re.compile(r"^\s*\**\s*([A-Za-z][A-Za-z ]{1,24}?)\s*\**\s*:\s*\**\s*(.+?)\s*\**\s*$")
_REQ_ROW = re.compile(r"^\s*\|?\s*((?:BCR|BR|REQ|CR|FR)-\d+(?:-\d+)*)\s*\|\s*(.+?)\s*\|?\s*$")
_REQ_LINE = re.compile(r"^\s*\**\s*((?:BCR|BR|REQ|CR|FR)-\d+(?:-\d+)*)\s*\**\s*[:—–-]\s*(.+?)\s*$")
_DOC_ID = re.compile(r"\b(BCR-\d{2,4})\b")

_PATH = re.compile(r"\b[\w./-]+?\.(?:py|mmd|md|docx|xlsx|yaml|yml|json|txt)\b")
_IDENT = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_UPPER_STATE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_BIZ_ID = re.compile(r"\b(?:US|TC|EPIC|BR|BO|TDD|TP|BRD)-[A-Z0-9-]*\d\b")
_SECTION_REF = re.compile(r"\b(TDD|TP|BRD)\s*§\s*(\d+(?:\.\d+)?)")
_CAMEL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")

#: Generic words that match the identifier regexes but say nothing about the corpus.
_STOP = frozenset(
    {
        "e_g",
        "i_e",
        "follow_up",
        "list",
        "src",
        "docs",
    }
)


def parse_meta(text: str) -> BcrMeta:
    """Read the ``Label: value`` block from the top of the document."""
    meta = BcrMeta()
    for line in text.splitlines()[:60]:
        match = _META_LINE.match(line)
        if not match:
            continue
        key = _META_LABELS.get(match.group(1).strip().lower())
        if key is None or getattr(meta, key) is not None:
            continue
        setattr(meta, key, match.group(2).strip())
    if meta.doc_id is None:
        found = _DOC_ID.search(text)
        if found:
            meta.doc_id = found.group(1)
    return meta


def parse_requirements(text: str) -> list[ChangeRequirement]:
    """Requirements are ``ID | text`` table rows or ``ID — text`` lines."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _REQ_ROW.match(line) or _REQ_LINE.match(line)
        if not match:
            continue
        rid, body = match.group(1), match.group(2).strip().strip("|").strip()
        if rid.lower().startswith("req id") or not body or rid in found:
            continue
        found[rid] = body
    return [ChangeRequirement(id=rid, text=body) for rid, body in found.items()]


def parse_title(text: str, *, fallback: str) -> str:
    """The subtitle line (second non-empty line) of a BCR, else the first heading."""
    lines = [ln.strip().lstrip("#").strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return fallback
    if len(lines) >= 2 and lines[0].lower().startswith("business change request"):
        return lines[1]
    for line in lines:
        if not _META_LINE.match(line) and len(line) < 140:
            return line
    return fallback


def seed_terms(text: str, requirements: list[ChangeRequirement]) -> list[str]:
    """Deterministic impact seeds: paths, identifiers, ids, section refs, states.

    Ordered by first appearance, de-duplicated, capped so the traversal stays
    readable. Paths keep only their basename-ish tail (``types.py``,
    ``order_workflow.py``) because the corpus layout differs from the BCR's
    ``src/…`` references (reference digest §6.1).
    """
    seen: dict[str, None] = {}

    def add(term: str) -> None:
        term = term.strip()
        if term and term.lower() not in _STOP and term not in seen:
            seen[term] = None

    for match in _PATH.finditer(text):
        raw = match.group(0)
        name = PurePosixPath(raw).name
        add(name)
    for match in _SECTION_REF.finditer(text):
        add(f"{match.group(1)} §{match.group(2)}")
    for match in _BIZ_ID.finditer(text):
        add(match.group(0))
    for match in _IDENT.finditer(text):
        add(match.group(0))
    for match in _UPPER_STATE.finditer(text):
        add(match.group(0))
    for match in _CAMEL.finditer(text):
        add(match.group(0))
    for req in requirements:
        for match in _IDENT.finditer(req.text):
            add(match.group(0))
    return list(seen)[:60]


def title_from_filename(filename: str | None) -> str:
    if not filename:
        return "Change request"
    stem = filename.rsplit(".", 1)[0]
    stem = re.sub(r"^(?:BCR|CR)-\d+-?", "", stem)
    return stem.replace("-", " ").replace("_", " ").strip().capitalize() or "Change request"
