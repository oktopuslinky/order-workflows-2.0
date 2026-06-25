"""FastAPI dependency providers.

These resolve the compiler for request handlers. The compiler is built once from
application settings (``.env``) and cached for the process. Tests override
``get_compiler`` via ``app.dependency_overrides`` to inject a mock provider and
an in-memory store.
"""

from __future__ import annotations

from functools import lru_cache

from workflow_compiler.compiler import WorkflowCompiler


@lru_cache(maxsize=1)
def get_compiler() -> WorkflowCompiler:
    """Provide a process-wide :class:`WorkflowCompiler` built from settings.

    The active LLM provider and the file-backed state store are resolved from
    environment configuration (see :class:`~workflow_compiler.config.Settings`).
    """
    return WorkflowCompiler.from_settings()
