"""Unit tests for the prompt management subsystem."""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_compiler.exceptions import PromptNotFoundError, PromptRenderError
from workflow_compiler.prompts import (
    PromptLoader,
    PromptManager,
    PromptRenderer,
)
from workflow_compiler.prompts.loader import parse_front_matter


def test_parse_front_matter_lists_and_scalars() -> None:
    text = "---\nname: demo\ndescription: A demo\nvariables: [a, b]\n---\nBody {{ a }}"
    meta, body = parse_front_matter(text)
    assert meta["name"] == "demo"
    assert meta["description"] == "A demo"
    assert meta["variables"] == ["a", "b"]
    assert body == "Body {{ a }}"


def test_parse_front_matter_absent() -> None:
    meta, body = parse_front_matter("No front matter here.")
    assert meta == {}
    assert body == "No front matter here."


# ---------------------------------------------------------------------------
# Bundled templates
# ---------------------------------------------------------------------------


def test_bundled_prompts_load() -> None:
    # Only prompts an agent actually renders are bundled: graph building,
    # Mermaid rendering, and code generation are deterministic (no LLM, no
    # prompt), so no template exists for them.
    loader = PromptLoader()
    prompts = loader.load_all()
    for expected in (
        "discover_workflow",
        "discover_workflows",
        "extract_facts",
        "classify_cvpa",
        "design_temporal",
    ):
        assert expected in prompts


def test_discover_workflow_prompt_declares_variable() -> None:
    prompt = PromptLoader().load("discover_workflow")
    assert "document_text" in prompt.variables
    assert prompt.description


def test_manager_renders_bundled_prompt() -> None:
    manager = PromptManager()
    rendered = manager.render("discover_workflow", document_text="ORDER DOC")
    assert "ORDER DOC" in rendered
    assert "{{" not in rendered


def test_manager_unknown_prompt_raises() -> None:
    with pytest.raises(PromptNotFoundError):
        PromptManager().get("no_such_prompt")


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def test_renderer_strict_missing_variable_raises(tmp_path: Path) -> None:
    template = "---\nname: t\nvariables: [a, b]\n---\n{{ a }} and {{ b }}"
    (tmp_path / "t.md").write_text(template, encoding="utf-8")
    manager = PromptManager(root=tmp_path)
    with pytest.raises(PromptRenderError):
        manager.render("t", a="only-a")


def test_renderer_lenient_leaves_unknown_placeholder(tmp_path: Path) -> None:
    template = "Hello {{ name }} {{ missing }}"
    (tmp_path / "p.md").write_text(template, encoding="utf-8")
    prompt = PromptLoader(root=tmp_path).load("p")
    renderer = PromptRenderer(strict=False)
    out = renderer.render(prompt, {"name": "Ada"})
    assert out == "Hello Ada {{ missing }}"


def test_custom_root_prompt_round_trip(tmp_path: Path) -> None:
    (tmp_path / "greet.md").write_text(
        "---\nname: greet\ndescription: Greeter\nvariables: [who]\n---\nHi {{ who }}!",
        encoding="utf-8",
    )
    manager = PromptManager(root=tmp_path)
    assert manager.names() == ["greet"]
    assert manager.render("greet", who="World") == "Hi World!"
