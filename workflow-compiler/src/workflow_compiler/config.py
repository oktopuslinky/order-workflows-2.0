"""Application settings, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
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
        default="nemotron",
        description=(
            "Active LLM provider name (registered in ProviderFactory). Default "
            "'nemotron' uses the NVIDIA cloud API. Opt into the local eGPU gateway "
            "with 'local', or 'local-fallback' (eGPU primary, Nemotron fallback)."
        ),
    )
    llm_model: str = Field(
        default="nvidia/llama-3.3-nemotron-super-49b-v1",
        description="Default model id requested from the (Nemotron/fallback) provider.",
    )
    llm_base_url: str | None = Field(
        default=None, description="Optional override for the provider base URL."
    )
    llm_local_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WORKFLOW_COMPILER_LLM_LOCAL_BASE_URL", "LLM_API_BASE"),
        description="Base URL of the local eGPU gateway (OpenAI-compatible, e.g. .../v1).",
    )
    llm_local_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WORKFLOW_COMPILER_LLM_LOCAL_MODEL", "LLM_MODEL"),
        description=(
            "Model id requested from the local gateway. When unset, the gateway's "
            "advertised default (/auth/config) is used, or a per-compile selection."
        ),
    )
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Default temperature.")
    llm_timeout: float = Field(
        default=400.0,
        gt=0.0,
        description=(
            "Per-request LLM timeout in seconds. The review passes and the Temporal "
            "design stage routinely run past a minute on a 49B model, so the transport "
            "default is far too tight for the HTTP API (which, unlike the CLI, has no "
            "--timeout flag)."
        ),
    )

    require_human_approval: bool = Field(
        default=True, description="Block downstream artifacts until the graph is approved."
    )

    session_secret: str | None = Field(
        default=None,
        description=(
            "HMAC key signing HTTP session cookies. When unset, a random secret is "
            "generated once and persisted to <state_store_path>/session_secret."
        ),
    )
    session_ttl_hours: float = Field(
        default=720.0, gt=0.0, description="Lifetime of a signed-in session (30 days)."
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
        ],
        description="Browser origins allowed to call the HTTP API (CORS allow-list).",
    )

    projects_shared: bool = Field(
        default=True,
        description=(
            "When true, every signed-in user can see and open every project "
            "(owner_id is still recorded for attribution). Set false to restore "
            "per-owner isolation."
        ),
    )

    review_enabled: bool = Field(
        default=True,
        description=(
            "Generate one canonical output per LLM stage and improve it with three "
            "sequential review passes (completeness, grounding, consistency). On by "
            "default."
        ),
    )
    review_stages: set[str] = Field(
        default_factory=lambda: {"discovery", "facts"},
        description="Which LLM stages get the sequential review pipeline.",
    )

    predraft_questions: Literal["off", "cloud", "always"] = Field(
        default="cloud",
        description=(
            "When to draft the Resolve tab's questions in the background after "
            "validation, so opening it is instant. 'cloud' (default) skips the local "
            "Spark gateway, which is a single GPU with no queueing — a background "
            "request there can push a concurrent compile past its timeout and kill "
            "it. 'always' enables it on every provider; 'off' disables it and the "
            "questions are drafted on demand as before."
        ),
    )

    graph_health_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description=(
            "Spec-centric pipeline: auto-approve a workflow's graph when its review "
            "health score is at or above this value; below it the workflow halts for "
            "manual review."
        ),
    )

    baseline_hours: dict[str, float] = Field(
        default_factory=lambda: {
            # Estimated hours a human team (BPM analyst + engineer) would spend
            # per pipeline step. ESTIMATES, deliberately conservative — tune to
            # your org (env: WORKFLOW_COMPILER_BASELINE_HOURS as a JSON object).
            # Keyed by the categories metrics.py buckets stage_timings into.
            "discovery": 2.0,  # per project: document analysis + workflow discovery
            "spec": 4.0,  # per workflow: fact extraction + spec drafting
            "validate": 1.0,  # per workflow validate pass: review + consistency check
            "compile": 38.0,  # per workflow: graph 4h + CVPA 2h + design 8h + code 24h
            "edit": 4.0,  # per edit section: analysis + re-spec + re-review
        },
        description=(
            "Estimated human-team hours per pipeline step category, powering the "
            "time-saved metric. Estimates, not measurements — tune to your org."
        ),
    )

    temporal_address: str = Field(
        default="localhost:7233",
        description=(
            "Temporal frontend address used to run generated bundles from the app. "
            "Absence is reported through GET /health so the UI can disable the Run "
            "control rather than failing when it is clicked."
        ),
    )
    temporal_namespace: str = Field(
        default="default", description="Temporal namespace executions are started in."
    )
    generated_root: str = Field(
        default="./generated",
        description=(
            "Root the in-app runner reads bundles from, as "
            "'<generated_root>/<project-id>/<slug>/'. Matches the CLI's --out-dir "
            "default. Bundles execute from disk so a hand-edited activities.py is "
            "what actually runs; a missing bundle is materialized once and then "
            "never overwritten."
        ),
    )

    stepwise: bool = Field(
        default=False,
        description=(
            "Generate step-gated Temporal bundles: every top-level plan step waits "
            "for an `advance` signal (interactive step-through debugging)."
        ),
    )
    kg_enrich_default: bool = Field(
        default=True,
        description=(
            "Knowledge bases: run LLM enrichment (per-file summaries, topics, "
            "entities, process clusters) by default when a corpus is indexed. "
            "Static ingest alone is instant; enrichment is one LLM call per "
            "document/module and runs as a background job."
        ),
    )
    kg_retrieve_budget: int = Field(
        default=4000,
        gt=0,
        description="Knowledge bases: default token budget of a retrieved context packet.",
    )
    kg_max_upload_mb: int = Field(
        default=50,
        gt=0,
        description="Knowledge bases: maximum uncompressed size of an uploaded corpus zip.",
    )
    change_kg_budget: int = Field(
        default=6000,
        gt=0,
        description=(
            "Token budget of knowledge-graph excerpts assembled into one change-wizard "
            "drafting brief (several retrievals, de-duplicated)."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, process-wide :class:`Settings` instance."""
    load_environment()
    return Settings()
