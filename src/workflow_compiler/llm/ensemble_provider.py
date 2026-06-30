"""``TemperatureProvider``: a provider decorator that fixes the sampling temperature.

Agents call ``structured(...)`` with the default ``temperature=0.0``, which (see
``llm/base.py``) bypasses the provider's configured temperature. Ensemble
candidates must *diverge* — a consensus merge is a no-op when every candidate is
identical — so each candidate runs against the same underlying provider wrapped
in this decorator at a distinct temperature. It is a pure pass-through otherwise,
so no agent or concrete provider needs to change.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from workflow_compiler.interfaces.llm import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)


class TemperatureProvider(BaseLLMProvider):
    """Wrap a provider, forcing a fixed sampling temperature on every call."""

    def __init__(self, inner: BaseLLMProvider, *, temperature: float) -> None:
        """Decorate ``inner``, injecting ``temperature`` into completions."""
        self._inner = inner
        self._temperature = temperature
        self.name = f"{getattr(inner, 'name', 'provider')}@t{temperature}"

    @property
    def inner(self) -> BaseLLMProvider:
        """The wrapped provider."""
        return self._inner

    @property
    def temperature(self) -> float:
        """The temperature this decorator injects."""
        return self._temperature

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Forward to the inner provider with the injected temperature."""
        return await self._inner.complete(
            prompt, system=system, temperature=self._temperature, max_tokens=max_tokens
        )

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Forward to the inner provider with the injected temperature."""
        return await self._inner.structured(
            prompt, schema, system=system, temperature=self._temperature
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Forward embeddings unchanged (temperature is irrelevant here)."""
        return await self._inner.embed(texts)

    async def aclose(self) -> None:
        """Close the inner provider if it owns a client (best-effort)."""
        aclose = getattr(self._inner, "aclose", None)
        if aclose is not None:
            await aclose()
