"""HTTP chat provider base: transport, retries, timeouts, structured output.

``HttpChatProvider`` implements the provider-agnostic :class:`BaseLLMProvider`
contract that agents depend on. Concrete providers only describe their wire
format (endpoint, payload, response parsing); all reliability concerns —
retries, timeouts, logging, JSON extraction, and schema validation — live here.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from workflow_compiler.exceptions import (
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderResponseError,
    ProviderTimeoutError,
    SchemaValidationError,
)
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.llm.config import ProviderConfig
from workflow_compiler.llm.json_utils import extract_json
from workflow_compiler.llm.retry import retry_async
from workflow_compiler.llm.types import ChatMessage, LLMResponse, Role
from workflow_compiler.logging import get_logger

if TYPE_CHECKING:
    from types import TracebackType

T = TypeVar("T", bound=BaseModel)

_STRUCTURED_INSTRUCTION = (
    "Respond with a single JSON value that conforms to the following JSON Schema. "
    "Return only the JSON — no prose, no Markdown code fences.\n\nJSON Schema:\n{schema}"
)
_CORRECTION_INSTRUCTION = (
    "The previous response was not valid against the schema. Error:\n{error}\n"
    "Return corrected JSON only."
)


class HttpChatProvider(BaseLLMProvider):
    """Abstract base for HTTP, OpenAI-style chat providers."""

    def __init__(self, config: ProviderConfig, *, client: httpx.AsyncClient | None = None) -> None:
        """Store config and an optional injected async client."""
        self._config = config
        self._client = client
        self._owns_client = client is None
        self._log = get_logger()

    # -- lifecycle ----------------------------------------------------------

    @property
    def config(self) -> ProviderConfig:
        """Return the provider configuration."""
        return self._config

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url, timeout=self._config.timeout
            )
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close the underlying client if this provider created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> HttpChatProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- BaseLLMProvider contract ------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return a plain-text completion for ``prompt``."""
        response = await self.chat(
            self._messages(prompt, system), temperature=temperature, max_tokens=max_tokens
        )
        return response.text

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Return a completion validated into ``schema``.

        Re-asks (up to ``config.structured_retries`` times) with the validation
        error appended when the model returns malformed or non-conforming JSON.
        """
        schema_text = json.dumps(schema.model_json_schema(), indent=2)
        messages = self._messages(prompt, system)
        messages.append(ChatMessage.user(_STRUCTURED_INSTRUCTION.format(schema=schema_text)))

        last_error: Exception | None = None
        for attempt in range(self._config.structured_retries + 1):
            if last_error is not None:
                messages.append(
                    ChatMessage.user(_CORRECTION_INSTRUCTION.format(error=last_error))
                )
            response = await self.chat(messages, temperature=temperature, json_mode=True)
            try:
                payload = extract_json(response.text)
                return schema.model_validate(payload)
            except (ProviderResponseError, ValidationError) as exc:
                last_error = exc
                self._log.warning(
                    "Structured output validation failed (attempt {}/{}): {}",
                    attempt + 1,
                    self._config.structured_retries + 1,
                    exc,
                )
                messages.append(ChatMessage.assistant(response.text))

        raise SchemaValidationError(
            f"Structured output failed validation after "
            f"{self._config.structured_retries + 1} attempt(s): {last_error}"
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return embedding vectors for ``texts`` (override per provider)."""
        raise NotImplementedError(f"{self.name} does not implement embeddings.")

    # -- chat orchestration -------------------------------------------------

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send a chat request with retries and return a normalized response."""
        payload = self._build_payload(messages, temperature, max_tokens, json_mode=json_mode)

        async def operation() -> dict[str, Any]:
            return await self._post(self._chat_endpoint(), payload)

        data = await retry_async(
            operation,
            config=self._config.retry,
            is_retryable=self._is_retryable,
            description=f"{self.name}.chat",
        )
        return self._parse_response(data)

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to ``endpoint`` and return the decoded body."""
        client = self._ensure_client()
        try:
            response = await client.post(endpoint, json=payload, headers=self._auth_headers())
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.name} request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"{self.name} transport error: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderHTTPError(response.status_code, response.text[:500])

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"{self.name} returned non-JSON body: {exc}") from exc

    def _is_retryable(self, exc: BaseException) -> bool:
        """Decide whether an exception should trigger a retry."""
        if isinstance(exc, (ProviderTimeoutError, ProviderConnectionError)):
            return True
        if isinstance(exc, ProviderHTTPError):
            return exc.status_code in self._config.retry.retry_on_status
        return False

    # -- helpers ------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Build request headers, including bearer auth when configured."""
        headers = {"Content-Type": "application/json", **self._config.extra_headers}
        if self._config.api_key is not None:
            headers["Authorization"] = f"Bearer {self._config.api_key.get_secret_value()}"
        return headers

    @staticmethod
    def _messages(prompt: str, system: str | None) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        if system:
            messages.append(ChatMessage(role=Role.SYSTEM, content=system))
        messages.append(ChatMessage(role=Role.USER, content=prompt))
        return messages

    # -- wire-format contract (implemented by concrete providers) ----------

    @abstractmethod
    def _chat_endpoint(self) -> str:
        """Return the chat-completions endpoint (relative to ``base_url``)."""
        raise NotImplementedError

    @abstractmethod
    def _build_payload(
        self,
        messages: Sequence[ChatMessage],
        temperature: float | None,
        max_tokens: int | None,
        *,
        json_mode: bool,
    ) -> dict[str, Any]:
        """Build the request body for a chat completion."""
        raise NotImplementedError

    @abstractmethod
    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Normalize a provider response payload into an :class:`LLMResponse`."""
        raise NotImplementedError
