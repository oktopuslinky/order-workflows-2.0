"""FastAPI dependency providers.

These resolve the compiler for request handlers. The compiler is built once from
application settings (``.env``) and cached for the process. Tests override
``get_compiler`` via ``app.dependency_overrides`` to inject a mock provider and
an in-memory store.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from workflow_compiler.compiler import WorkflowCompiler

if TYPE_CHECKING:
    from workflow_compiler.project_compiler import ProjectCompiler


@lru_cache(maxsize=1)
def get_compiler() -> WorkflowCompiler:
    """Provide a process-wide :class:`WorkflowCompiler` built from settings.

    The active LLM provider and the file-backed state store are resolved from
    environment configuration (see :class:`~workflow_compiler.config.Settings`).
    """
    return WorkflowCompiler.from_settings()


@lru_cache(maxsize=1)
def get_project_compiler() -> ProjectCompiler:
    """Provide a process-wide :class:`ProjectCompiler` built from settings."""
    from workflow_compiler.project_compiler import ProjectCompiler

    return ProjectCompiler.from_settings()
