"""Abstract interfaces for workflow-compiler.

These define the extension points the compiler depends on. Concrete
implementations are provided elsewhere; nothing here implements business logic.
"""

from __future__ import annotations

from workflow_compiler.interfaces.agent import BaseAgent
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.interfaces.parser import BaseParser
from workflow_compiler.interfaces.review_manager import ReviewManager
from workflow_compiler.interfaces.state_store import StateStore

__all__ = [
    "BaseAgent",
    "BaseLLMProvider",
    "BaseParser",
    "ReviewManager",
    "StateStore",
]
