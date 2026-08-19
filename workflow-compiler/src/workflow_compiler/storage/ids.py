"""Store-boundary guards shared by every file-backed store.

Two concerns live here because every store needs both and they must agree:

* **Id sanitisation** — every id that becomes part of a filesystem path
  (workflow states, projects, users, knowledge bases, change requests, generated
  bundle directories) is validated against ``[A-Za-z0-9_-]{1,128}`` *before* a
  path is built. Anything else (``..``, separators, drive letters, NUL) is refused
  as *not found* — an id that cannot exist is indistinguishable from one that
  does not, and the check must never reveal whether path-shaped input would have
  resolved to something.
* **Compare-and-swap on save** — every persisted aggregate carries an integer
  ``version`` that the store bumps on each save. A writer that loaded version *n*
  may pass ``expected_version=n``; if the stored version moved on meanwhile the
  save is refused with :class:`StaleWriteError` (HTTP 409) instead of silently
  overwriting somebody else's work. Writers that pass ``None`` keep last-write-wins
  (the CLI, background jobs, older clients) — CAS is opt-in by decision.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from workflow_compiler.exceptions import StaleWriteError, StateNotFoundError

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def is_safe_id(value: str) -> bool:
    """``True`` when ``value`` is a bare identifier that can be a filename stem."""
    return bool(value) and _ID_RE.match(value) is not None


def validate_store_id(value: str, *, label: str = "record") -> str:
    """Return ``value`` when it is a safe store id, else raise ``StateNotFoundError``."""
    if not is_safe_id(value):
        raise StateNotFoundError(f"No {label} with id {value!r}.")
    return value


def validate_slug(value: str, *, label: str = "workflow") -> str:
    """Return ``value`` when it is a safe path segment (bundle/spec dirs), else raise."""
    if not value or _SLUG_RE.match(value) is None:
        raise StateNotFoundError(f"No {label} {value!r}.")
    return value


def stored_version(path: Path) -> int | None:
    """The ``version`` recorded in the JSON file at ``path`` (``None`` when absent).

    A file written before versions existed reads as ``0``; an unreadable file also
    reads as ``0`` so a corrupt record can still be overwritten by a writer that
    does not ask for CAS.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    value = payload.get("version", 0) if isinstance(payload, dict) else 0
    return value if isinstance(value, int) and value >= 0 else 0


def next_version(current: int | None, expected: int | None, *, label: str, key: str) -> int:
    """Decide the version a save will write, enforcing CAS when ``expected`` is set.

    ``current`` is what the store holds (``None`` = nothing stored yet, treated as
    ``0``); ``expected`` is what the writer last saw. Mismatch → ``StaleWriteError``.
    """
    have = current or 0
    if expected is not None and expected != have:
        raise StaleWriteError(
            f"The {label} {key!r} changed since it was loaded "
            f"(stored version {have}, expected {expected}). Reload and retry."
        )
    return have + 1


__all__ = [
    "is_safe_id",
    "next_version",
    "stored_version",
    "validate_slug",
    "validate_store_id",
]
