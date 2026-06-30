"""Application settings, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from workflow_compiler.env import load_environment


class Settings(BaseSettings):
    """Runtime configuration for workflow-compiler."""

    model_config = SettingsConfigDict(
        env_prefix="WORKFLOW_COMPILER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="workflow-compiler", description="Application name.")
    log_level: str = Field(default="INFO", description="Loguru log level.")
    log_json: bool = Field(default=False, description="Emit logs as JSON lines when True.")

    state_store_path: str = Field(
        default=".workflow_state", description="Filesystem path for file-backed state stores."
    )

    llm_provider: str = Field(
        default="nemotron", description="Active LLM provider name (registered in ProviderFactory)."
    )
    llm_model: str = Field(
        default="nvidia/llama-3.3-nemotron-super-49b-v1",
        description="Default model id requested from the provider.",
    )
    llm_base_url: str | None = Field(
        default=None, description="Optional override for the provider base URL."
    )
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Default temperature.")

    require_human_approval: bool = Field(
        default=True, description="Block downstream artifacts until the graph is approved."
    )

    ensemble_enabled: bool = Field(
        default=False,
        description="Run selected LLM stages N times and consensus-merge the candidates.",
    )
    ensemble_n: int = Field(
        default=3, ge=1, le=8, description="Number of ensemble candidates per stage."
    )
    ensemble_temperatures: list[float] = Field(
        default_factory=lambda: [0.2, 0.5, 0.8],
        description="Sampling temperatures used to diversify ensemble candidates.",
    )
    ensemble_stages: set[str] = Field(
        default_factory=lambda: {"discovery", "facts"},
        description="Which LLM stages get the consensus-merge ensemble.",
    )
    ensemble_per_candidate_timeout: float = Field(
        default=300.0, gt=0.0, description="Per-candidate timeout in seconds."
    )
    ensemble_overall_timeout: float = Field(
        default=480.0, gt=0.0, description="Overall ensemble budget in seconds."
    )

    review_enabled: bool = Field(
        default=True,
        description=(
            "Generate one canonical output per LLM stage and improve it with three "
            "sequential review passes (completeness, grounding, consistency). On by "
            "default; the ensemble takes precedence on any stage it is enabled for."
        ),
    )
    review_stages: set[str] = Field(
        default_factory=lambda: {"discovery", "facts"},
        description="Which LLM stages get the sequential review pipeline.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, process-wide :class:`Settings` instance."""
    load_environment()
    return Settings()
