"""Generic provider for any OpenAI-compatible chat/embeddings HTTP API."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, ClassVar

import httpx
from pydantic import SecretStr

from workflow_compiler.env import load_environment
from workflow_compiler.exceptions import LLMProviderError, ProviderResponseError
from workflow_compiler.llm.base import HttpChatProvider
from workflow_compiler.llm.config import ProviderConfig
from workflow_compiler.llm.retry import retry_async
from workflow_compiler.llm.types import ChatMessage, LLMResponse, LLMUsage, RetryConfig


class OpenAICompatibleProvider(HttpChatProvider):
    """Provider speaking the OpenAI ``/chat/completions`` wire format.

    This implementation is deliberately vendor-neutral: any service exposing an
    OpenAI-compatible API works by supplying ``base_url`` and ``model``.
    Concrete vendors subclass this only to set sensible defaults.
    """

    name: ClassVar[str] = "openai-compatible"

    #: Subclasses override these to provide vendor defaults.
    DEFAULT_BASE_URL: ClassVar[str | None] = None
    DEFAULT_MODEL: ClassVar[str | None] = None
    API_KEY_ENV: ClassVar[str | None] = None
    DEFAULT_SYSTEM_PREAMBLE: ClassVar[str | None] = None

    # Endpoints are relative (no leading slash) so they join onto a base_url
    # that ends in a path segment such as ``/v1/``.
    CHAT_ENDPOINT: ClassVar[str] = "chat/completions"
    EMBEDDINGS_ENDPOINT: ClassVar[str] = "embeddings"
    MODELS_ENDPOINT: ClassVar[str] = "models"

    def __init__(
        self,
        *,
        config: ProviderConfig | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retry: RetryConfig | None = None,
        extra_headers: dict[str, str] | None = None,
        system_preamble: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Build a provider from an explicit config or keyword overrides."""
        if config is None:
            config = self._build_config(
                model=model,
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                temperature=temperature,
                max_tokens=max_tokens,
                retry=retry,
                extra_headers=extra_headers,
                system_preamble=system_preamble,
            )
        super().__init__(config, client=client)

    @classmethod
    def _build_config(
        cls,
        *,
        model: str | None,
        base_url: str | None,
        api_key: str | None,
        timeout: float | None,
        temperature: float | None,
        max_tokens: int | None,
        retry: RetryConfig | None,
        extra_headers: dict[str, str] | None,
        system_preamble: str | None,
    ) -> ProviderConfig:
        resolved_model = model or cls.DEFAULT_MODEL
        if not resolved_model:
            raise LLMProviderError(f"{cls.__name__} requires a 'model'.")
        resolved_base_url = base_url or cls.DEFAULT_BASE_URL
        if not resolved_base_url:
            raise LLMProviderError(f"{cls.__name__} requires a 'base_url'.")
        # Ensure a trailing slash so relative endpoints append rather than
        # replace the final path segment when joined by httpx.
        resolved_base_url = resolved_base_url.rstrip("/") + "/"

        resolved_key = api_key
        if resolved_key is None and cls.API_KEY_ENV:
            load_environment()
            resolved_key = os.environ.get(cls.API_KEY_ENV)

        fields: dict[str, Any] = {
            "model": resolved_model,
            "base_url": resolved_base_url,
            "api_key": SecretStr(resolved_key) if resolved_key else None,
        }
        if timeout is not None:
            fields["timeout"] = timeout
        if temperature is not None:
            fields["temperature"] = temperature
        if max_tokens is not None:
            fields["max_tokens"] = max_tokens
        if retry is not None:
            fields["retry"] = retry
        if extra_headers is not None:
            fields["extra_headers"] = extra_headers
        resolved_preamble = system_preamble or cls.DEFAULT_SYSTEM_PREAMBLE
        if resolved_preamble is not None:
            fields["system_preamble"] = resolved_preamble
        return ProviderConfig(**fields)

    # -- wire format --------------------------------------------------------

    def _chat_endpoint(self) -> str:
        return self.CHAT_ENDPOINT

    def _build_payload(
        self,
        messages: Sequence[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        *,
        json_mode: bool,
    ) -> dict[str, Any]:
        wire_messages: list[dict[str, str]] = []
        if self._config.system_preamble:
            wire_messages.append({"role": "system", "content": self._config.system_preamble})
        wire_messages.extend({"role": m.role.value, "content": m.content} for m in messages)
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": wire_messages,
            "temperature": self._config.temperature if temperature is None else temperature,
            "stream": False,
        }
        resolved_max = max_tokens if max_tokens is not None else self._config.max_tokens
        if resolved_max is not None:
            payload["max_tokens"] = resolved_max
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices")
        if not choices:
            raise ProviderResponseError(f"{self.name} response contained no choices.")
        first = choices[0]
        message = first.get("message") or {}
        content = message.get("content")
        if content is None:
            raise ProviderResponseError(f"{self.name} response choice had no content.")

        usage_data = data.get("usage")
        usage = (
            LLMUsage(
                prompt_tokens=usage_data.get("prompt_tokens"),
                completion_tokens=usage_data.get("completion_tokens"),
                total_tokens=usage_data.get("total_tokens"),
            )
            if isinstance(usage_data, dict)
            else None
        )
        return LLMResponse(
            text=content,
            model=data.get("model", self._config.model),
            finish_reason=first.get("finish_reason"),
            usage=usage,
            raw=data,
        )

    # -- discovery ----------------------------------------------------------

    async def list_models(self) -> list[str]:
        """Return the ids of models the server exposes (OpenAI ``GET /models``)."""
        data = await self._get(self.MODELS_ENDPOINT)
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderResponseError(f"{self.name} models response missing 'data'.")
        return [item["id"] for item in items if isinstance(item, dict) and "id" in item]

    # -- embeddings ---------------------------------------------------------

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return embedding vectors via the OpenAI-compatible embeddings API."""
        payload = {
            "model": self._config.embed_model or self._config.model,
            "input": list(texts),
        }

        async def operation() -> dict[str, Any]:
            return await self._post(self.EMBEDDINGS_ENDPOINT, payload)

        data = await retry_async(
            operation,
            config=self._config.retry,
            is_retryable=self._is_retryable,
            description=f"{self.name}.embed",
        )
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderResponseError(f"{self.name} embeddings response missing 'data'.")
        return [item["embedding"] for item in items]
