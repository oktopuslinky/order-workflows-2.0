"""Tests asserting the abstract interfaces remain abstract."""

from __future__ import annotations

import inspect

import pytest

from workflow_compiler.interfaces import (
    BaseAgent,
    BaseLLMProvider,
    BaseParser,
    ReviewManager,
    StateStore,
)

ABSTRACTS = [BaseAgent, BaseLLMProvider, BaseParser, ReviewManager, StateStore]


@pytest.mark.parametrize("cls", ABSTRACTS)
def test_cannot_instantiate_abstract(cls: type) -> None:
    assert inspect.isabstract(cls)
    with pytest.raises(TypeError):
        cls()  # type: ignore[abstract]


def test_base_agent_stores_llm() -> None:
    class DummyAgent(BaseAgent):
        name = "dummy"

        async def run(self, state):  # type: ignore[override]
            return state

    agent = DummyAgent(llm=None)
    assert agent.llm is None
    assert agent.name == "dummy"
