"""Bridge the app's async :class:`BaseLLMProvider` to Context Hub's sync JSON-chat client.

Context Hub's enrichment (``bootstrap/enrich.py``, ``cluster.py``) is synchronous
and expects an object with ``chat_json(messages, *, label, retries) -> dict``.
The app's providers are async and their ``httpx`` client is bound to the event
loop that first uses it. :class:`ProviderJsonClient` reconciles the two: it is
called from the worker thread that runs ``init_repo`` and schedules each
completion back onto the loop it was created on (``run_coroutine_threadsafe``),
so provider objects never cross loops. With no loop (a plain script) it falls
back to ``asyncio.run``. Responses are parsed with the app's fence-tolerant
:func:`~workflow_compiler.llm.json_utils.extract_json`, so a model that wraps
its JSON in prose or code fences still works; a non-object answer is retried
and finally reported as :class:`LlmError`, which enrichment treats as
"skip this file" rather than a failed index.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.kg.contexthub.bootstrap.llm import LlmError
from workflow_compiler.llm.json_utils import extract_json

logger = logging.getLogger(__name__)


class ProviderJsonClient:
    """A ``JsonChatClient`` over a :class:`BaseLLMProvider`."""

    def __init__(
        self,
        provider: BaseLLMProvider,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = 1024,
        call_timeout: float | None = None,
    ) -> None:
        self._provider = provider
        self._loop = loop
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._call_timeout = call_timeout
        #: Number of completions actually requested (for tests / runbook timings).
        self.calls = 0
        self.failures = 0

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def _complete(self, prompt: str, system: str | None) -> str:
        coro = self._provider.complete(
            prompt,
            system=system,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=self._call_timeout)
        # No live loop (CLI helper / plain script): run to completion here.
        return asyncio.run(coro)

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        label: str = "",
        retries: int = 3,
    ) -> dict[str, Any]:
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        user_parts = [m["content"] for m in messages if m.get("role") != "system"]
        system = "\n\n".join(system_parts) or None
        prompt = "\n\n".join(user_parts)
        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            self.calls += 1
            try:
                text = self._complete(prompt, system)
                parsed = extract_json(text)
            except Exception as exc:  # provider or parse failure → retry
                last_error = exc
                logger.debug("kg enrichment call %r attempt %d failed: %s", label, attempt, exc)
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = LlmError(f"LLM returned a JSON {type(parsed).__name__}, not an object")
        self.failures += 1
        raise LlmError(f"{label or 'enrichment'}: {last_error}")
