"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Provider-agnostic interface for large language model access.

    Implementations wrap a concrete backend (Anthropic, OpenAI-compatible,
    local, mock, ...). The compiler and agents depend only on this surface.
    """

    #: Short, unique name for the provider implementation.
    name: ClassVar[str] = "base"

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return a text completion for ``prompt``."""
        raise NotImplementedError

    @abstractmethod
    async def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Return a completion parsed/validated into the given Pydantic ``schema``."""
        raise NotImplementedError

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""
        raise NotImplementedError
