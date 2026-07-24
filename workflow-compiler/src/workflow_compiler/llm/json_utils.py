"""Helpers for extracting JSON from free-form LLM text output."""

from __future__ import annotations

import json
import re
from typing import Any

from workflow_compiler.exceptions import ProviderResponseError

_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")
_OPENERS = {"{": "}", "[": "]"}


def _strip_fences(text: str) -> str:
    """Remove a single surrounding Markdown code fence, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE.sub("", stripped)
    return stripped.strip()


def _find_balanced(text: str) -> str | None:
    """Return the first balanced JSON object/array substring, or ``None``.

    Scans character-by-character, respecting string literals and escapes so
    braces inside strings do not unbalance the match.
    """
    start = next((i for i, ch in enumerate(text) if ch in _OPENERS), None)
    if start is None:
        return None

    opener = text[start]
    closer = _OPENERS[opener]
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def extract_json(text: str) -> Any:
    """Extract and parse the first JSON value embedded in ``text``.

    Tolerates surrounding prose and Markdown code fences. Raises
    :class:`ProviderResponseError` when no parseable JSON is found.
    """
    candidate = _strip_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    snippet = _find_balanced(candidate)
    if snippet is None:
        raise ProviderResponseError(
            f"No JSON object or array found in response: {text[:200]!r}"
        )
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise ProviderResponseError(f"Failed to parse JSON from response: {exc}") from exc
