"""Composite provider: try a primary LLM, fall back to a secondary on failure.

Used to make the local eGPU gateway the primary LLM with the hosted Nemotron API
as a safety net. The fallback triggers only when the primary is **unreachable**
(``ProviderConnectionError`` / ``ProviderTimeoutError``) or returns a **server
error** (HTTP 5xx). Auth failures and other 4xx responses propagate unchanged so
a misconfiguration (e.g. wrong gateway password) surfaces instead of being masked.

When the primary is found unreachable its state is cached for a short window so a
down box does not stall every call; the window expires and the primary is probed
again, so a reconnected eGPU is picked back up automatically.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import ClassVar, TypeVar

from pydantic import BaseModel

from workflow_compiler.exceptions import (
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderTimeoutError,
)
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.logging import get_logger

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class FallbackProvider(BaseLLMProvider):
    """Delegate to ``primary``; on unreachable/5xx, transparently use ``fallback``."""

    name: ClassVar[str] = "local-fallback"

    def __init__(
        self,
        *,
        primary: BaseLLMProvider,
        fallback: BaseLLMProvider,
        recheck_seconds: float = 60.0,
    ) -> None:
        """Wrap a primary and fallback provider; ``recheck_seconds`` gates re-probing."""
        self._primary = primary
        self._fallback = fallback
        self._recheck_seconds = recheck_seconds
        self._down_until: float | None = None
        self._log = get_logger()

    def _primary_down(self) -> bool:
        return self._down_until is not None and time.monotonic() < self._down_until

    async def _with_fallback(self, call: Callable[[BaseLLMProvider], Awaitable[R]]) -> R:
        """Run ``call`` on the primary, delegating to the fallback on unreachable/5xx."""
        if self._primary_down():
            return await call(self._fallback)
        try:
            return await call(self._primary)
        except (ProviderConnectionError, ProviderTimeoutError) as exc:
            self._down_until = time.monotonic() + self._recheck_seconds
            self._log.warning(
                "Primary LLM '{}' unreachable ({}); falling back to '{}'.",
                self._primary.name,
                exc,
                self._fallback.name,
            )
            return await call(self._fallback)
        except ProviderHTTPError as exc:
            if exc.status_code >= 500:
                self._log.warning(
                    "Primary LLM '{}' returned HTTP {}; falling back to '{}'.",
                    self._primary.name,
                    exc.status_code,
                    self._fallback.name,
                )
                return await call(self._fallback)
            raise

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Text completion via the primary, falling back on failure."""
        return await self._with_fallback(
            lambda p: p.complete(
                prompt, system=system, temperature=temperature, max_tokens=max_tokens
            )
        )

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Structured completion via the primary, falling back on failure."""
        return await self._with_fallback(
            lambda p: p.structured(prompt, schema, system=system, temperature=temperature)
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embeddings via the primary, falling back on failure."""
        return await self._with_fallback(lambda p: p.embed(texts))

    async def list_models(self) -> list[str]:
        """List models from the primary provider (empty if it can't enumerate)."""
        lister = getattr(self._primary, "list_models", None)
        if lister is None:
            return []
        result: list[str] = await lister()
        return result

    async def aclose(self) -> None:
        """Close both underlying providers if they own resources."""
        for provider in (self._primary, self._fallback):
            closer = getattr(provider, "aclose", None)
            if closer is not None:
                await closer()
