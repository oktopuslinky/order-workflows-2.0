"""Provider-agnostic LLM layer.

Agents depend only on :class:`BaseLLMProvider`. Concrete providers (e.g.
:class:`NemotronProvider`) are constructed directly or via
:class:`ProviderFactory` and injected into the compiler. No vendor SDK is used;
NVIDIA-hosted models are reached over their OpenAI-compatible REST API.
"""

from __future__ import annotations

from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.llm.base import HttpChatProvider
from workflow_compiler.llm.config import ProviderConfig
from workflow_compiler.llm.ensemble_provider import TemperatureProvider
from workflow_compiler.llm.factory import ProviderFactory
from workflow_compiler.llm.json_utils import extract_json
from workflow_compiler.llm.providers import (
    MockProvider,
    NemotronProvider,
    OpenAICompatibleProvider,
)
from workflow_compiler.llm.types import (
    ChatMessage,
    LLMResponse,
    LLMUsage,
    RetryConfig,
    Role,
)

__all__ = [
    "BaseLLMProvider",
    "ChatMessage",
    "HttpChatProvider",
    "LLMResponse",
    "LLMUsage",
    "MockProvider",
    "NemotronProvider",
    "OpenAICompatibleProvider",
    "ProviderConfig",
    "ProviderFactory",
    "RetryConfig",
    "Role",
    "TemperatureProvider",
    "extract_json",
]
