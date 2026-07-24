"""Provider configuration model."""

from __future__ import annotations

from pydantic import Field, SecretStr

from workflow_compiler.llm.types import RetryConfig
from workflow_compiler.models.base import WorkflowBaseModel


class ProviderConfig(WorkflowBaseModel):
    """Connection and behavior settings for an HTTP-based LLM provider.

    Nothing here is provider-specific: a concrete provider supplies defaults for
    ``base_url`` / ``model`` but every value remains overridable, so providers
    stay swappable without changing agent code.
    """

    model: str = Field(..., description="Model identifier to request.")
    base_url: str = Field(..., description="Base URL of the (OpenAI-compatible) API.")
    api_key: SecretStr | None = Field(default=None, description="Bearer credential, if required.")

    timeout: float = Field(default=60.0, gt=0.0, description="Per-request timeout in seconds.")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Default sampling temp.")
    system_preamble: str | None = Field(
        default=None,
        description="System message prepended to every request (e.g. reasoning toggles).",
    )
    max_tokens: int | None = Field(default=None, gt=0, description="Default max output tokens.")
    embed_model: str | None = Field(
        default=None, description="Optional separate model id for embeddings."
    )

    retry: RetryConfig = Field(default_factory=RetryConfig, description="Retry policy.")
    structured_retries: int = Field(
        default=1,
        ge=0,
        description="Corrective re-asks allowed when structured output fails validation.",
    )

    extra_headers: dict[str, str] = Field(
        default_factory=dict, description="Additional headers to send on every request."
    )
