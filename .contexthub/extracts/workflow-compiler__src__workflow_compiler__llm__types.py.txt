"""Shared, provider-agnostic message and response types for the LLM layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from workflow_compiler.models.base import WorkflowBaseModel


class Role(StrEnum):
    """Chat message roles understood across providers."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(WorkflowBaseModel):
    """A single chat message in a provider-agnostic conversation."""

    role: Role = Field(..., description="Message role.")
    content: str = Field(..., description="Message text content.")

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        """Build a system message."""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> ChatMessage:
        """Build a user message."""
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> ChatMessage:
        """Build an assistant message."""
        return cls(role=Role.ASSISTANT, content=content)


class LLMUsage(WorkflowBaseModel):
    """Token accounting returned by a provider, when available."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMResponse(WorkflowBaseModel):
    """Normalized response from a chat completion call."""

    text: str = Field(..., description="Assistant message content.")
    model: str | None = Field(default=None, description="Model that produced the response.")
    finish_reason: str | None = Field(default=None, description="Why generation stopped.")
    usage: LLMUsage | None = Field(default=None, description="Token usage, if reported.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw provider payload.")


class RetryConfig(WorkflowBaseModel):
    """Configuration for retrying transient provider failures with backoff."""

    max_attempts: int = Field(default=3, ge=1, description="Total attempts (>=1).")
    initial_backoff: float = Field(default=0.5, ge=0.0, description="First backoff in seconds.")
    backoff_factor: float = Field(default=2.0, ge=1.0, description="Exponential growth factor.")
    max_backoff: float = Field(default=8.0, ge=0.0, description="Maximum backoff in seconds.")
    jitter: bool = Field(default=True, description="Apply full jitter to backoff delays.")
    retry_on_status: frozenset[int] = Field(
        default=frozenset({408, 409, 425, 429, 500, 502, 503, 504}),
        description="HTTP status codes considered retryable.",
    )
