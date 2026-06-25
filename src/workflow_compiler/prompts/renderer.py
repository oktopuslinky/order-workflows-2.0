"""Render prompt templates by substituting ``{{ variable }}`` placeholders."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from workflow_compiler.exceptions import PromptRenderError
from workflow_compiler.prompts.models import Prompt

_PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptRenderer:
    """Substitute variables into a :class:`Prompt` template.

    The renderer is intentionally small and dependency-free. In ``strict`` mode
    (the default) it raises when a declared or referenced variable is missing,
    so prompt/variable drift fails loudly rather than producing silent gaps.
    """

    def __init__(self, *, strict: bool = True) -> None:
        """Configure strict (raise on missing) vs. lenient rendering."""
        self.strict = strict

    @staticmethod
    def referenced_variables(template: str) -> set[str]:
        """Return the set of variable names referenced in ``template``."""
        return set(_PLACEHOLDER.findall(template))

    def render(self, prompt: Prompt, values: Mapping[str, Any] | None = None) -> str:
        """Render ``prompt`` using ``values``, returning the final text."""
        provided = dict(values or {})

        if self.strict:
            required = set(prompt.variables) | self.referenced_variables(prompt.template)
            missing = sorted(required - provided.keys())
            if missing:
                raise PromptRenderError(
                    f"Prompt '{prompt.name}' is missing variables: {', '.join(missing)}."
                )

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key in provided:
                return str(provided[key])
            if self.strict:
                raise PromptRenderError(
                    f"Prompt '{prompt.name}' references undefined variable '{key}'."
                )
            return match.group(0)

        return _PLACEHOLDER.sub(_replace, prompt.template)
