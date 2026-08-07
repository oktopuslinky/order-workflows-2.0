"""Tests for ``workflow-compiler init`` and its pure ``.env`` renderer."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from workflow_compiler.cli.init_env import (
    DEFAULT_GATEWAY_BASE,
    PROVIDER_CHOICES,
    missing_credentials,
    render_env,
)
from workflow_compiler.cli.main import app

runner = CliRunner()


def _settings(text: str) -> dict[str, str]:
    """Parse rendered .env text into the live (uncommented) settings only."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key] = value
    return out


# --- renderer ---------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDER_CHOICES)
def test_render_env_sets_the_chosen_provider(provider: str) -> None:
    settings = _settings(render_env(provider=provider))
    assert settings["WORKFLOW_COMPILER_LLM_PROVIDER"] == provider


def test_render_env_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        render_env(provider="gpt-9")


def test_render_env_writes_supplied_credentials_live() -> None:
    settings = _settings(
        render_env(
            provider="local-fallback",
            nvidia_api_key="nvapi-real",
            gateway_base="http://box:8080/v1",
            gateway_email="a@b.com",
            gateway_password="pw",
        )
    )
    assert settings["NVIDIA_API_KEY"] == "nvapi-real"
    assert settings["LLM_API_BASE"] == "http://box:8080/v1"
    assert settings["LLM_GATEWAY_EMAIL"] == "a@b.com"
    assert settings["LLM_GATEWAY_PASSWORD"] == "pw"


def test_render_env_comments_out_credentials_it_was_not_given() -> None:
    text = render_env(provider="mock")
    settings = _settings(text)
    # No secret is ever written as a live setting when none was supplied...
    assert "NVIDIA_API_KEY" not in settings
    assert "LLM_GATEWAY_PASSWORD" not in settings
    # ...but the keys stay present as commented placeholders, so switching
    # provider later is an uncomment rather than a hunt through .env.example.
    assert "# NVIDIA_API_KEY=" in text
    assert "# LLM_GATEWAY_PASSWORD=" in text


def test_render_env_always_sets_the_application_defaults() -> None:
    settings = _settings(render_env(provider="mock", state_store_path="custom_state"))
    assert settings["WORKFLOW_COMPILER_STATE_STORE_PATH"] == "custom_state"
    assert settings["WORKFLOW_COMPILER_REVIEW_ENABLED"] == "true"
    assert settings["WORKFLOW_COMPILER_GRAPH_HEALTH_THRESHOLD"] == "0.9"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("mock", []),
        ("nemotron", ["NVIDIA_API_KEY"]),
        ("local", ["LLM_GATEWAY_EMAIL", "LLM_GATEWAY_PASSWORD"]),
        ("local-fallback", ["NVIDIA_API_KEY", "LLM_GATEWAY_EMAIL", "LLM_GATEWAY_PASSWORD"]),
    ],
)
def test_missing_credentials_reports_what_each_provider_needs(
    provider: str, expected: list[str]
) -> None:
    assert (
        missing_credentials(
            provider, nvidia_api_key=None, gateway_email=None, gateway_password=None
        )
        == expected
    )


def test_missing_credentials_is_empty_once_supplied() -> None:
    assert (
        missing_credentials(
            "local-fallback",
            nvidia_api_key="nvapi-real",
            gateway_email="a@b.com",
            gateway_password="pw",
        )
        == []
    )


# --- command ----------------------------------------------------------------


def test_init_writes_the_file_non_interactively(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    result = runner.invoke(app, ["init", "--provider", "mock", "--yes", "--env-file", str(target)])
    assert result.exit_code == 0, result.output
    assert _settings(target.read_text(encoding="utf-8"))[
        "WORKFLOW_COMPILER_LLM_PROVIDER"
    ] == "mock"


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEEP=me\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "--provider", "mock", "--yes", "--env-file", str(target)])

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert target.read_text(encoding="utf-8") == "KEEP=me\n"


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("KEEP=me\n", encoding="utf-8")

    result = runner.invoke(
        app, ["init", "--provider", "mock", "--yes", "--force", "--env-file", str(target)]
    )

    assert result.exit_code == 0, result.output
    assert "KEEP=me" not in target.read_text(encoding="utf-8")


def test_init_rejects_an_unknown_provider(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    result = runner.invoke(app, ["init", "--provider", "gpt-9", "--yes", "--env-file", str(target)])

    assert result.exit_code == 1
    assert "Unknown provider" in result.output
    assert not target.exists()


def test_init_warns_about_credentials_it_did_not_get(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    result = runner.invoke(
        app, ["init", "--provider", "nemotron", "--yes", "--env-file", str(target)]
    )

    assert result.exit_code == 0, result.output
    assert "NVIDIA_API_KEY" in result.output
    assert target.exists()


def test_init_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / ".env"
    result = runner.invoke(app, ["init", "--provider", "mock", "--yes", "--env-file", str(target)])

    assert result.exit_code == 0, result.output
    assert target.exists()


def test_init_prompts_for_provider_and_key_when_interactive(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    result = runner.invoke(
        app, ["init", "--env-file", str(target)], input="nemotron\nnvapi-typed\n"
    )

    assert result.exit_code == 0, result.output
    settings = _settings(target.read_text(encoding="utf-8"))
    assert settings["WORKFLOW_COMPILER_LLM_PROVIDER"] == "nemotron"
    assert settings["NVIDIA_API_KEY"] == "nvapi-typed"


def test_init_prompts_for_gateway_credentials(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    result = runner.invoke(
        app,
        ["init", "--provider", "local", "--env-file", str(target)],
        input="\nme@x.com\nsecret\n",
    )

    assert result.exit_code == 0, result.output
    settings = _settings(target.read_text(encoding="utf-8"))
    assert settings["LLM_API_BASE"] == DEFAULT_GATEWAY_BASE  # blank input took the default
    assert settings["LLM_GATEWAY_EMAIL"] == "me@x.com"
    assert settings["LLM_GATEWAY_PASSWORD"] == "secret"
