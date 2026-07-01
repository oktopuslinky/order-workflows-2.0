"""Split an (edited) master document back into per-workflow ideal documents.

Contract with the master format (see :mod:`master_assemble`): the **only** H1
(``# ``) headings are per-workflow section titles, so a human adds a workflow by
adding a ``# Name`` section. Everything before the first H1 is preamble (the index
and editing instructions) and is discarded. Helper sub-blocks the author should not
compile (``### Open questions``, ``### Readiness gaps``) are stripped from each
section, leaving a clean ideal-format document per workflow.
"""

from __future__ import annotations

import re

_H1 = re.compile(r"^# (?P<title>.+?)\s*$")
_HELPER_HEADINGS = {"guidance", "open questions", "readiness gaps", "notes"}


def slugify(name: str) -> str:
    """Return a filesystem-safe snake_case slug for a workflow name."""
    words = re.findall(r"[A-Za-z0-9]+", name.lower())
    return "_".join(words) or "workflow"


def _strip_helpers(lines: list[str]) -> str:
    """Drop known helper (``###``) blocks; keep the ideal ``##`` sections."""
    out: list[str] = []
    skip = False
    for line in lines:
        if line.startswith("### "):
            title = line[4:].strip().lower()
            skip = title in _HELPER_HEADINGS
            if skip:
                continue
        elif line.startswith("## ") or line.startswith("# "):
            skip = False
        if not skip:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def split_master(master_text: str) -> list[tuple[str, str]]:
    """Split ``master_text`` into ``[(slug, ideal_document_text), ...]``.

    Sections are delimited by top-level ``# `` headings; the preamble before the
    first heading is ignored. Returns one clean ideal-format document per workflow.
    """
    lines = master_text.splitlines()
    boundaries: list[int] = [i for i, line in enumerate(lines) if _H1.match(line)]
    if not boundaries:
        return []

    results: list[tuple[str, str]] = []
    for pos, start in enumerate(boundaries):
        end = boundaries[pos + 1] if pos + 1 < len(boundaries) else len(lines)
        block = lines[start:end]
        title = _H1.match(block[0]).group("title")  # type: ignore[union-attr]
        results.append((slugify(title), _strip_helpers(block)))
    return results
