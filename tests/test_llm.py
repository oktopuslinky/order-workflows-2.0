"""Unit tests for the provider-agnostic LLM layer."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from workflow_compiler.exceptions import (
    LLMProviderError,
    ProviderHTTPError,
    SchemaValidationError,
)
from workflow_compiler.llm import (
    ChatMessage,
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
    assert seen["payload"]["model"] == "nvidia/llama-3.3-nemotron-super-49b-v1"
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
