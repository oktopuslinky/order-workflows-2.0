"""Deterministic ``.env`` rendering for the ``workflow-compiler init`` command.

Installation and configuration are two separate steps: ``pip install .`` installs the
software, ``workflow-compiler init`` configures it. A wheel cannot run code at install
time, so the configuration step has to be a command the user types.

The rendering below is a pure function of its arguments — no prompting, no filesystem,
no environment lookups — so the generated file is testable without a terminal. The
prompting lives in ``cli/main.py``; this module only turns answers into text.

The template covers the settings a first run needs. ``.env.example`` in the repository
root stays the exhaustive reference for every supported setting.
"""

from __future__ import annotations

from typing import Final

PROVIDER_CHOICES: Final[tuple[str, ...]] = ("nemotron", "local", "local-fallback", "mock")

PROVIDER_HELP: Final[dict[str, str]] = {
    "nemotron": "NVIDIA-hosted Nemotron cloud API (needs a key from build.nvidia.com)",
    "local": "local eGPU gateway only",
    "local-fallback": "local eGPU gateway, with automatic Nemotron fallback",
    "mock": "deterministic offline provider (no API key, no network)",
}

#: Providers that reach the NVIDIA cloud API and therefore need ``NVIDIA_API_KEY``.
KEY_PROVIDERS: Final[frozenset[str]] = frozenset({"nemotron", "local-fallback"})

#: Providers that reach the local eGPU gateway and therefore need session credentials.
GATEWAY_PROVIDERS: Final[frozenset[str]] = frozenset({"local", "local-fallback"})

DEFAULT_NEMOTRON_MODEL: Final = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULT_GATEWAY_BASE: Final = "http://192.168.1.184:8080/v1"
DEFAULT_STATE_STORE_PATH: Final = ".workflow_state"

_KEY_PLACEHOLDER: Final = "nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def render_env(
    *,
    provider: str,
    nvidia_api_key: str | None = None,
    model: str = DEFAULT_NEMOTRON_MODEL,
    gateway_base: str | None = None,
    gateway_email: str | None = None,
    gateway_password: str | None = None,
    state_store_path: str = DEFAULT_STATE_STORE_PATH,
) -> str:
    """Render the text of a ``.env`` file for ``provider``.

    Credentials the chosen provider does not need are still written, but commented
    out with a placeholder value, so switching provider later is an uncomment rather
    than a trip back to ``.env.example``.

    Raises:
        ValueError: if ``provider`` is not one of :data:`PROVIDER_CHOICES`.
    """
    if provider not in PROVIDER_CHOICES:
        choices = ", ".join(PROVIDER_CHOICES)
        raise ValueError(f"Unknown provider {provider!r}. Choose one of: {choices}")

    lines: list[str] = [
        "# workflow-compiler configuration.",
        "# Written by `workflow-compiler init`. Safe to edit by hand.",
        "# This file is git-ignored. See .env.example for every supported setting.",
        "",
        "# --- LLM provider ------------------------------------------------------------",
        f"# One of: {', '.join(PROVIDER_CHOICES)}",
        f"WORKFLOW_COMPILER_LLM_PROVIDER={provider}",
        f"WORKFLOW_COMPILER_LLM_MODEL={model}",
        "",
        "# --- Credentials -------------------------------------------------------------",
    ]

    lines.extend(_credential_block("NVIDIA_API_KEY", nvidia_api_key, _KEY_PLACEHOLDER))
    lines.append("")
    lines.extend(_credential_block("LLM_API_BASE", gateway_base, DEFAULT_GATEWAY_BASE))
    lines.extend(_credential_block("LLM_GATEWAY_EMAIL", gateway_email, "you@example.com"))
    lines.extend(_credential_block("LLM_GATEWAY_PASSWORD", gateway_password, "your-password"))

    lines.extend(
        [
            "",
            "# --- Application ---------------------------------------------------------"
            "----",
            "WORKFLOW_COMPILER_LOG_LEVEL=INFO",
            f"WORKFLOW_COMPILER_STATE_STORE_PATH={state_store_path}",
            "# Sequential review pipeline (completeness -> grounding -> consistency).",
            "WORKFLOW_COMPILER_REVIEW_ENABLED=true",
            "# Auto-approve a workflow graph at or above this health score.",
            "WORKFLOW_COMPILER_GRAPH_HEALTH_THRESHOLD=0.9",
            "",
        ]
    )
    return "\n".join(lines)


def _credential_block(name: str, value: str | None, placeholder: str) -> list[str]:
    """Render one credential as a live setting, or as a commented placeholder."""
    if value:
        return [f"{name}={value}"]
    return [f"# {name}={placeholder}"]


def missing_credentials(
    provider: str,
    *,
    nvidia_api_key: str | None,
    gateway_email: str | None,
    gateway_password: str | None,
) -> list[str]:
    """Name the credentials ``provider`` needs but did not receive.

    Returned for warning purposes only — ``init`` still writes the file, because a
    half-configured ``.env`` the user can finish by hand beats no file at all.
    """
    missing: list[str] = []
    if provider in KEY_PROVIDERS and not nvidia_api_key:
        missing.append("NVIDIA_API_KEY")
    if provider in GATEWAY_PROVIDERS:
        if not gateway_email:
            missing.append("LLM_GATEWAY_EMAIL")
        if not gateway_password:
            missing.append("LLM_GATEWAY_PASSWORD")
    return missing
