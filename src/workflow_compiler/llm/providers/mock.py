"""In-memory mock provider for tests and offline development."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from workflow_compiler.exceptions import LLMProviderError
from workflow_compiler.interfaces.llm import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)


class MockProvider(BaseLLMProvider):
    """A deterministic provider that returns queued or default responses.

    Useful for testing agents and the compiler without any network access while
    still honoring the :class:`BaseLLMProvider` contract.
    """

    name: ClassVar[str] = "mock"

    def __init__(
        self,
        *,
        completions: Sequence[str] | None = None,
        structured: Sequence[BaseModel | dict[str, Any]] | None = None,
        embeddings: Sequence[list[list[float]]] | None = None,
        default_completion: str = "mock-response",
    ) -> None:
        """Seed response queues; queues are consumed in order, FIFO."""
        self._completions = list(completions or [])
        self._structured = list(structured or [])
        self._embeddings = list(embeddings or [])
        self._default_completion = default_completion
        #: Recorded ``(method, prompt)`` calls, for assertions in tests.
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return the next queued completion, or the default."""
        self.calls.append(("complete", prompt))
        if self._completions:
            return self._completions.pop(0)
        return self._default_completion

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Return the next queued structured response validated into ``schema``."""
        self.calls.append(("structured", prompt))
        if not self._structured:
            raise LLMProviderError("MockProvider has no structured responses queued.")
        item = self._structured.pop(0)
        if isinstance(item, schema):
            return item
        return schema.model_validate(item)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return the next queued embedding batch, or deterministic stand-ins."""
        self.calls.append(("embed", "|".join(texts)))
        if self._embeddings:
            return self._embeddings.pop(0)
        return [[float(len(text))] for text in texts]
