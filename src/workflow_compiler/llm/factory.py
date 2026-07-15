"""Registry-based factory for constructing LLM providers by name.

No provider is hardcoded into the compiler or agents: providers register a
builder under a name, and callers select one at runtime. New providers become
available by registering them — agent code never changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from workflow_compiler.exceptions import LLMProviderError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.llm.providers.mock import MockProvider
from workflow_compiler.llm.providers.nemotron import NemotronProvider
from workflow_compiler.llm.providers.openai_compatible import OpenAICompatibleProvider

ProviderBuilder = Callable[..., BaseLLMProvider]

def _scripted_mock(**kwargs: Any) -> MockProvider:
    """Factory-built mocks answer with scripted demo defaults when unqueued.

    This is what makes every CLI command runnable offline with
    ``--provider mock``; tests that need the strict raising behavior construct
    :class:`MockProvider` directly.
    """
    kwargs.setdefault("script_defaults", True)
    return MockProvider(**kwargs)


_DEFAULT_PROVIDERS: dict[str, ProviderBuilder] = {
    "nemotron": NemotronProvider,
    "openai-compatible": OpenAICompatibleProvider,
    "mock": _scripted_mock,
}


class ProviderFactory:
    """Create :class:`BaseLLMProvider` instances from a name + keyword args."""

    def __init__(self, registry: dict[str, ProviderBuilder] | None = None) -> None:
        """Initialize with the default registry (copied) unless overridden."""
        self._registry: dict[str, ProviderBuilder] = dict(registry or _DEFAULT_PROVIDERS)

    def register(self, name: str, builder: ProviderBuilder) -> None:
        """Register (or override) a provider builder under ``name``."""
        self._registry[name.lower()] = builder

    def unregister(self, name: str) -> None:
        """Remove a registered provider builder."""
        self._registry.pop(name.lower(), None)

    @property
    def available(self) -> list[str]:
        """Return the sorted names of registered providers."""
        return sorted(self._registry)

    def create(self, name: str, **kwargs: Any) -> BaseLLMProvider:
        """Construct the provider registered under ``name``."""
        builder = self._registry.get(name.lower())
        if builder is None:
            raise LLMProviderError(
                f"Unknown LLM provider '{name}'. Available: {', '.join(self.available)}."
            )
        return builder(**kwargs)

    def from_settings(self, settings: Any | None = None) -> BaseLLMProvider:
        """Construct the provider described by application :class:`Settings`."""
        from workflow_compiler.config import get_settings

        resolved = settings or get_settings()
        if resolved.llm_provider.lower() == "mock":
            return self.create("mock")

        kwargs: dict[str, Any] = {
            "model": resolved.llm_model,
            "temperature": resolved.llm_temperature,
            "timeout": resolved.llm_timeout,
        }
        if getattr(resolved, "llm_base_url", None):
            kwargs["base_url"] = resolved.llm_base_url
        return self.create(resolved.llm_provider, **kwargs)
