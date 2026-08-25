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
import concurrent.futures
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
        # Upstream used 1024. Nemotron-class models often preface the JSON with
        # prose and the clustering answer lists every file, so 1024 truncates the
        # object and the call is wasted; 2048 leaves headroom at negligible cost.
        max_tokens: int | None = 2048,
        # Wall-clock seconds per attempt (None = unbounded). See ``_complete``.
        call_timeout: float | None = None,
    ) -> None:
        self._provider = provider
        self._loop = loop
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._call_timeout = call_timeout
        self._loop_stopped = False
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
        if self._call_timeout is not None:
            # A wall-clock bound per attempt. The provider's own timeout is
            # per socket read, so a hosted endpoint that keeps a connection
            # alive while it stalls (observed: one call held for ~25 min on
            # integrate.api.nvidia.com) would otherwise freeze the whole index
            # on a single file. ``wait_for`` cancels the request on expiry.
            coro = asyncio.wait_for(coro, timeout=self._call_timeout)
        if self._loop is not None:
            if self._loop_stopped or not self._loop.is_running():
                # The loop was handed over but has since stopped (server
                # shutdown or reload): nothing will ever run the coroutine, and
                # once seen it stays that way, so every later call fails at
                # once and the orphaned index thread finishes promptly.
                self._loop_stopped = True
                coro.close()
                raise LlmError("event loop stopped; enrichment call not attempted")
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            # Poll instead of blocking: if the loop stops underneath this
            # worker thread the future is never resolved, and a thread parked
            # on it keeps the interpreter alive at exit — under
            # ``uvicorn --reload`` that meant the old process never exited and
            # no new server was started.
            while True:
                concurrent.futures.wait([future], timeout=1.0)
                if future.done():
                    if future.cancelled():
                        # Only interpreter/loop shutdown cancels tasks here.
                        self._loop_stopped = True
                        raise LlmError("event loop shutting down; enrichment call cancelled")
                    return future.result()
                if self._loop.is_closed() or not self._loop.is_running():
                    self._loop_stopped = True
                    future.cancel()
                    raise LlmError("event loop stopped while waiting for the LLM")
        # No loop (CLI helper / plain script): run to completion here.
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
                logger.warning(
                    "kg enrichment call %r attempt %d/%d failed: %s",
                    label, attempt + 1, max(1, retries), str(exc)[:200],
                )
                continue
            if isinstance(parsed, dict):
                return parsed
            last_error = LlmError(f"LLM returned a JSON {type(parsed).__name__}, not an object")
        self.failures += 1
        logger.warning("kg enrichment call %r gave up after %d attempts", label, max(1, retries))
        raise LlmError(f"{label or 'enrichment'}: {last_error}")
