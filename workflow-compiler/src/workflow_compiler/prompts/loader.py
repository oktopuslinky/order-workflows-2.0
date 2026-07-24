"""Load prompt templates from Markdown files with optional front matter."""

from __future__ import annotations

from pathlib import Path

from workflow_compiler.exceptions import PromptError, PromptNotFoundError
from workflow_compiler.prompts.models import Prompt

#: Default location of bundled prompt templates.
DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"

_LIST_KEYS = frozenset({"variables", "tags"})


def _parse_scalar(value: str) -> str:
    """Strip surrounding quotes from a scalar front-matter value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_list(value: str) -> list[str]:
    """Parse a ``[a, b]`` or comma-separated front-matter list value."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [_parse_scalar(item) for item in value.split(",") if item.strip()]


def parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split optional ``---`` front matter from the template body.

    Returns ``(metadata, body)``. Front matter is parsed as simple
    ``key: value`` lines; ``variables`` and ``tags`` become lists.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        return {}, text

    metadata: dict[str, object] = {}
    for line in lines[1:closing]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, raw_value = stripped.partition(":")
        key = key.strip()
        metadata[key] = _parse_list(raw_value) if key in _LIST_KEYS else _parse_scalar(raw_value)

    body = "\n".join(lines[closing + 1 :]).strip("\n")
    return metadata, body


class PromptLoader:
    """Discover and load :class:`Prompt` templates from a directory."""

    def __init__(self, root: Path | str | None = None) -> None:
        """Use ``root`` (or the bundled templates dir) as the prompt source."""
        self.root = Path(root) if root is not None else DEFAULT_TEMPLATE_DIR

    def _path_for(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def load(self, name: str) -> Prompt:
        """Load a single prompt by name (file stem, without extension)."""
        path = self._path_for(name)
        if not path.is_file():
            raise PromptNotFoundError(f"Prompt '{name}' not found at {path}.")
        return self._parse(name, path)

    def load_all(self) -> dict[str, Prompt]:
        """Load every ``*.md`` prompt in the root directory."""
        if not self.root.is_dir():
            raise PromptError(f"Prompt directory does not exist: {self.root}")
        prompts: dict[str, Prompt] = {}
        for path in sorted(self.root.glob("*.md")):
            prompts[path.stem] = self._parse(path.stem, path)
        return prompts

    def _parse(self, name: str, path: Path) -> Prompt:
        text = path.read_text(encoding="utf-8")
        metadata, body = parse_front_matter(text)

        variables = metadata.pop("variables", [])
        description = metadata.pop("description", None)
        metadata.pop("name", None)
        metadata.pop("tags", None)

        return Prompt(
            name=name,
            template=body,
            description=str(description) if description is not None else None,
            variables=[str(v) for v in variables] if isinstance(variables, list) else [],
            metadata={k: str(v) for k, v in metadata.items()},
            path=path,
        )
