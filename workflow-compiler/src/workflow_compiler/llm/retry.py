"""Async retry helper with exponential backoff and full jitter."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from workflow_compiler.llm.types import RetryConfig
from workflow_compiler.logging import get_logger

_log = get_logger()


def compute_backoff(attempt: int, config: RetryConfig) -> float:
    """Return the backoff delay (seconds) before ``attempt`` (1-based)."""
    raw = config.initial_backoff * (config.backoff_factor ** (attempt - 1))
    capped = min(raw, config.max_backoff)
    if config.jitter:
        return random.uniform(0.0, capped)
    return capped


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    config: RetryConfig,
    is_retryable: Callable[[BaseException], bool],
    description: str = "operation",
) -> T:
    """Run ``operation`` with retries on retryable failures.

    Retries up to ``config.max_attempts`` times, sleeping with exponential
    backoff between attempts. Non-retryable exceptions propagate immediately.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except Exception as exc:
            if attempt >= config.max_attempts or not is_retryable(exc):
                raise
            delay = compute_backoff(attempt, config)
            _log.warning(
                "{} failed (attempt {}/{}): {}. Retrying in {:.2f}s.",
                description,
                attempt,
                config.max_attempts,
                exc,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)
