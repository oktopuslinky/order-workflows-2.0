"""Unit tests for the provider-agnostic LLM layer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from workflow_compiler.exceptions import (
    LLMProviderError,
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderResponseError,
    SchemaValidationError,
)
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.llm import (
    ChatMessage,
    FallbackProvider,
    GatewaySessionProvider,
    MockProvider,
    NemotronProvider,
    ProviderFactory,
    RetryConfig,
    Role,
    extract_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Person(BaseModel):
    name: str
    age: int


def _chat_response(content: str, model: str = "nvidia/test") -> dict:
    return {
        "id": "cmpl-1",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }


def _make_nemotron(handler) -> NemotronProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://nvidia.test/v1/")
    return NemotronProvider(
        api_key="test-key",
        client=client,
        retry=RetryConfig(max_attempts=3, initial_backoff=0.0, jitter=False),
    )


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_fenced_block() -> None:
    text = "Here you go:\n```json\n{\"a\": 1, \"b\": [2, 3]}\n```\nThanks!"
    assert extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_ignores_braces_in_strings() -> None:
    assert extract_json('{"k": "a } b"}') == {"k": "a } b"}


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


async def test_mock_provider_complete_and_record() -> None:
    provider = MockProvider(completions=["one", "two"])
    assert await provider.complete("p1") == "one"
    assert await provider.complete("p2") == "two"
    assert await provider.complete("p3") == "mock-response"
    assert provider.calls[0] == ("complete", "p1")


async def test_mock_provider_structured() -> None:
    provider = MockProvider(structured=[{"name": "Ada", "age": 36}])
    person = await provider.structured("who", _Person)
    assert isinstance(person, _Person)
    assert person.name == "Ada"


async def test_mock_provider_structured_without_queue_raises() -> None:
    with pytest.raises(LLMProviderError):
        await MockProvider().structured("who", _Person)


# ---------------------------------------------------------------------------
# NemotronProvider over a mock transport
# ---------------------------------------------------------------------------


async def test_nemotron_complete_hits_v1_endpoint() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_chat_response("Hello from Nemotron"))

    provider = _make_nemotron(handler)
    text = await provider.complete("hi", system="be concise")
    await provider.aclose()

    assert text == "Hello from Nemotron"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["payload"]["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert seen["payload"]["messages"][0]["role"] == "system"


async def test_nemotron_structured_validates_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_response('{"name": "Grace", "age": 45}'))

    provider = _make_nemotron(handler)
    person = await provider.structured("extract", _Person)
    await provider.aclose()
    assert person == _Person(name="Grace", age=45)


async def test_nemotron_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json=_chat_response("recovered"))

    provider = _make_nemotron(handler)
    text = await provider.complete("hi")
    await provider.aclose()
    assert text == "recovered"
    assert calls["n"] == 2


async def test_nemotron_raises_after_exhausting_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = _make_nemotron(handler)
    with pytest.raises(ProviderHTTPError) as excinfo:
        await provider.complete("hi")
    await provider.aclose()
    assert excinfo.value.status_code == 500


async def test_nemotron_non_retryable_status_raises_immediately() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    provider = _make_nemotron(handler)
    with pytest.raises(ProviderHTTPError):
        await provider.complete("hi")
    await provider.aclose()
    assert calls["n"] == 1


async def test_nemotron_structured_invalid_then_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_response("not json at all"))

    provider = _make_nemotron(handler)
    with pytest.raises(SchemaValidationError):
        await provider.structured("extract", _Person)
    await provider.aclose()


# ---------------------------------------------------------------------------
# Empty completions
#
# Reasoning models intermittently return no content at all. That is a different
# failure from malformed JSON and is reported as such, so the logs point at the
# serving setup rather than at the prompt or the schema.
# ---------------------------------------------------------------------------


async def test_structured_recovers_from_an_empty_completion() -> None:
    """An empty first response is re-asked and the retry's answer is accepted."""
    sent: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["messages"])
        if len(sent) == 1:
            return httpx.Response(200, json=_chat_response(""))
        return httpx.Response(200, json=_chat_response('{"name": "Ada", "age": 36}'))

    provider = _make_nemotron(handler)
    person = await provider.structured("extract", _Person)
    await provider.aclose()

    assert person == _Person(name="Ada", age=36)
    assert len(sent) == 2
    # No empty assistant turn is fed back — there is nothing there to correct.
    assert all(m["content"].strip() for m in sent[1])
    assert "empty" in sent[1][-1]["content"].lower()


async def test_structured_all_empty_raises_provider_response_error() -> None:
    """Nothing but empty completions is a provider fault, not a schema fault."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_response("   "))

    provider = _make_nemotron(handler)
    with pytest.raises(ProviderResponseError) as excinfo:
        await provider.structured("extract", _Person)
    await provider.aclose()

    message = str(excinfo.value)
    assert "empty completion" in message
    assert not isinstance(excinfo.value, SchemaValidationError)


async def test_structured_mixed_empty_and_invalid_reports_schema_failure() -> None:
    """One empty then real-but-wrong output still ends as a schema failure."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_chat_response(""))
        return httpx.Response(200, json=_chat_response('{"name": "Ada"}'))

    provider = _make_nemotron(handler)
    with pytest.raises(SchemaValidationError):
        await provider.structured("extract", _Person)
    await provider.aclose()


# ---------------------------------------------------------------------------
# ProviderFactory
# ---------------------------------------------------------------------------


def test_factory_available_includes_defaults() -> None:
    factory = ProviderFactory()
    assert {"nemotron", "mock", "openai-compatible"} <= set(factory.available)


def test_factory_create_mock() -> None:
    assert isinstance(ProviderFactory().create("mock"), MockProvider)


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(LLMProviderError):
        ProviderFactory().create("does-not-exist")


def test_factory_register_custom_provider() -> None:
    factory = ProviderFactory()
    factory.register("custom", lambda **kw: MockProvider())
    assert isinstance(factory.create("custom"), MockProvider)


def test_chat_message_helpers() -> None:
    assert ChatMessage.system("x").role is Role.SYSTEM
    assert ChatMessage.user("x").role is Role.USER


def test_compiler_accepts_injected_provider() -> None:
    from workflow_compiler import WorkflowCompiler

    provider = MockProvider()
    compiler = WorkflowCompiler(llm_provider=provider)
    assert compiler.llm_provider is provider


# ---------------------------------------------------------------------------
# GatewaySessionProvider (local eGPU gateway, session auth) over mock transport
# ---------------------------------------------------------------------------


def _make_gateway(handler, *, model: str | None = "gpt-oss-20b") -> GatewaySessionProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://gw.test/v1/")
    return GatewaySessionProvider(
        email="a@b.co",
        password="password1",
        model=model,
        base_url="http://gw.test/v1/",
        client=client,
        retry=RetryConfig(max_attempts=1, initial_backoff=0.0, jitter=False),
    )


async def test_gateway_logs_in_and_sends_bearer() -> None:
    seen: dict[str, Any] = {"logins": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            seen["logins"] += 1
            seen["login_body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"authenticated": True, "expires_in": 3600},
                headers={"set-cookie": "openserver_session=tok123; Path=/"},
            )
        if request.url.path == "/v1/chat/completions":
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=_chat_response("hi", model="gpt-oss-20b"))
        return httpx.Response(404)

    provider = _make_gateway(handler)
    text = await provider.complete("hello")
    await provider.aclose()

    assert text == "hi"
    assert seen["logins"] == 1
    assert seen["login_body"] == {"email": "a@b.co", "password": "password1"}
    assert seen["auth"] == "Bearer tok123"


async def test_gateway_relogins_on_401() -> None:
    state = {"logins": 0, "chats": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            state["logins"] += 1
            return httpx.Response(
                200,
                json={"authenticated": True, "expires_in": 3600},
                headers={"set-cookie": f"openserver_session=tok{state['logins']}; Path=/"},
            )
        # First chat 401s (stale session); after re-login it succeeds.
        state["chats"] += 1
        if state["chats"] == 1:
            return httpx.Response(401, text="expired")
        return httpx.Response(200, json=_chat_response("recovered", model="gpt-oss-20b"))

    provider = _make_gateway(handler)
    text = await provider.complete("hello")
    await provider.aclose()

    assert text == "recovered"
    assert state["logins"] == 2  # initial + forced re-login
    assert state["chats"] == 2


async def test_gateway_login_transport_error_is_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            raise httpx.ConnectError("no route to host")
        return httpx.Response(404)

    provider = _make_gateway(handler)
    with pytest.raises(ProviderConnectionError):
        await provider.complete("hello")
    await provider.aclose()


async def test_gateway_rejected_credentials_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"authenticated": False})
        return httpx.Response(404)

    provider = _make_gateway(handler)
    with pytest.raises(LLMProviderError):
        await provider.complete("hello")
    await provider.aclose()


async def test_gateway_list_models_reads_auth_config() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/config":
            return httpx.Response(
                200,
                json={
                    "model": "NVIDIA-Nemotron-3-Nano-30B",
                    "models": [{"id": "gpt-oss-20b"}, {"id": "qwen3.5-9b"}],
                },
            )
        return httpx.Response(404)

    provider = _make_gateway(handler)
    models = await provider.list_models()
    await provider.aclose()
    assert models == ["gpt-oss-20b", "qwen3.5-9b"]


async def test_gateway_resolves_default_model_when_unset() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/config":
            return httpx.Response(200, json={"model": "resolved-default", "models": []})
        if request.url.path == "/auth/login":
            return httpx.Response(
                200,
                json={"authenticated": True, "expires_in": 3600},
                headers={"set-cookie": "openserver_session=tok; Path=/"},
            )
        if request.url.path == "/v1/chat/completions":
            seen["model"] = json.loads(request.content)["model"]
            return httpx.Response(200, json=_chat_response("ok", model="resolved-default"))
        return httpx.Response(404)

    provider = _make_gateway(handler, model=None)
    await provider.complete("hello")
    await provider.aclose()
    assert seen["model"] == "resolved-default"


# ---------------------------------------------------------------------------
# FallbackProvider
# ---------------------------------------------------------------------------


class _StubProvider(BaseLLMProvider):
    """Records calls; returns a fixed completion or raises a configured error."""

    def __init__(self, name: str, *, raises: Exception | None = None, text: str = "ok") -> None:
        self.name = name
        self._raises = raises
        self._text = text
        self.calls = 0

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._text

    async def structured(self, prompt: str, schema: Any, *, system: Any = None, temperature: float = 0.0) -> Any:  # noqa: E501
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return schema()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return [[0.0] for _ in texts]


async def test_fallback_uses_primary_when_healthy() -> None:
    primary = _StubProvider("primary", text="from-primary")
    fallback = _StubProvider("fallback", text="from-fallback")
    provider = FallbackProvider(primary=primary, fallback=fallback)
    assert await provider.complete("hi") == "from-primary"
    assert fallback.calls == 0


async def test_fallback_on_unreachable_and_caches_down() -> None:
    primary = _StubProvider("primary", raises=ProviderConnectionError("down"))
    fallback = _StubProvider("fallback", text="from-fallback")
    provider = FallbackProvider(primary=primary, fallback=fallback)

    assert await provider.complete("a") == "from-fallback"
    assert await provider.complete("b") == "from-fallback"
    # Primary attempted once, then skipped while marked down.
    assert primary.calls == 1
    assert fallback.calls == 2


async def test_fallback_on_5xx_does_not_cache_down() -> None:
    primary = _StubProvider("primary", raises=ProviderHTTPError(503, "busy"))
    fallback = _StubProvider("fallback", text="from-fallback")
    provider = FallbackProvider(primary=primary, fallback=fallback)

    assert await provider.complete("a") == "from-fallback"
    assert await provider.complete("b") == "from-fallback"
    # 5xx is not treated as 'down', so the primary is re-tried each call.
    assert primary.calls == 2


async def test_fallback_reraises_client_error() -> None:
    primary = _StubProvider("primary", raises=ProviderHTTPError(400, "bad"))
    fallback = _StubProvider("fallback")
    provider = FallbackProvider(primary=primary, fallback=fallback)
    with pytest.raises(ProviderHTTPError):
        await provider.complete("a")
    assert fallback.calls == 0


async def test_fallback_reraises_schema_validation_error() -> None:
    primary = _StubProvider("primary", raises=SchemaValidationError("nope"))
    fallback = _StubProvider("fallback")
    provider = FallbackProvider(primary=primary, fallback=fallback)
    with pytest.raises(SchemaValidationError):
        await provider.complete("a")
    assert fallback.calls == 0


# ---------------------------------------------------------------------------
# Factory wiring for local / local-fallback
# ---------------------------------------------------------------------------


def _local_settings(**overrides: Any) -> SimpleNamespace:
    base = {
        "llm_provider": "local-fallback",
        "llm_model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "llm_local_base_url": "http://gw.test/v1",
        "llm_local_model": None,
        "llm_temperature": 0.0,
        "llm_timeout": 60.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_factory_available_includes_local_providers() -> None:
    assert {"local", "local-fallback"} <= set(ProviderFactory().available)


def test_from_settings_builds_fallback_provider() -> None:
    provider = ProviderFactory().from_settings(_local_settings())
    assert isinstance(provider, FallbackProvider)


def test_from_settings_builds_local_provider() -> None:
    provider = ProviderFactory().from_settings(_local_settings(llm_provider="local"))
    assert isinstance(provider, GatewaySessionProvider)


def test_build_local_provider_requires_base_url() -> None:
    from workflow_compiler.llm.factory import build_local_provider

    with pytest.raises(LLMProviderError):
        build_local_provider(_local_settings(llm_local_base_url=None))
