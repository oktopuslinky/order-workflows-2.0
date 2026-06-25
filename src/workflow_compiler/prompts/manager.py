"""High-level prompt access: load, cache, and render by name."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workflow_compiler.prompts.loader import PromptLoader
from workflow_compiler.prompts.models import Prompt
from workflow_compiler.prompts.renderer import PromptRenderer


class PromptManager:
    """Façade over :class:`PromptLoader` and :class:`PromptRenderer`.

    Prompts are loaded lazily and cached. Call :meth:`reload` to clear the
    cache after editing template files.
    """

    def __init__(
        self,
        loader: PromptLoader | None = None,
        renderer: PromptRenderer | None = None,
        *,
        root: Path | str | None = None,
    ) -> None:
        """Build a manager, optionally pointing the loader at a custom ``root``."""
        self._loader = loader or PromptLoader(root=root)
        self._renderer = renderer or PromptRenderer()
        self._cache: dict[str, Prompt] = {}

    def get(self, name: str) -> Prompt:
        """Return the named prompt, loading and caching it on first access."""
        if name not in self._cache:
            self._cache[name] = self._loader.load(name)
        return self._cache[name]

    def render(self, name: str, /, **values: Any) -> str:
        """Load (if needed) and render the named prompt with ``values``."""
        return self._renderer.render(self.get(name), values)

    def names(self) -> list[str]:
        """Return the sorted names of all available prompts."""
        return sorted(self._loader.load_all())

    def reload(self) -> None:
        """Clear the prompt cache so templates are re-read from disk."""
        self._cache.clear()
