"""Abstract agent interface.

An agent consumes the current :class:`WorkflowState`, performs one unit of
compilation work (extract metadata, extract facts, build the graph, classify,
design Temporal, render Mermaid, ...), and returns an updated state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import WorkflowState


class BaseAgent(ABC):
    """Base class for a single-responsibility compilation agent."""

    #: Short, unique name for the agent implementation.
    name: str = "base"

    def __init__(self, llm: BaseLLMProvider | None = None) -> None:
        """Store an optional LLM provider the agent may use."""
        self._llm = llm

    @property
    def llm(self) -> BaseLLMProvider | None:
        """Return the agent's LLM provider, if any."""
        return self._llm

    @abstractmethod
    async def run(self, state: WorkflowState) -> WorkflowState:
        """Perform this agent's work and return the updated state."""
        raise NotImplementedError
