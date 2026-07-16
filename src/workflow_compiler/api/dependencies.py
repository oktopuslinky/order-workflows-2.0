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
    from workflow_compiler.interfaces.llm import BaseLLMProvider
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


def get_local_provider() -> BaseLLMProvider:
    """Build a local eGPU gateway provider (for model discovery)."""
    from workflow_compiler.config import get_settings
    from workflow_compiler.llm.factory import build_local_provider

    return build_local_provider(get_settings())


#: Sentinel ``model`` value routing a compile through the hosted NVIDIA Nemotron
#: API instead of the local eGPU gateway. Kept in sync with the frontend
#: (app/page.tsx NEMOTRON_CLOUD).
NEMOTRON_CLOUD = "nemotron-cloud"


def project_compiler_for_model(model: str) -> ProjectCompiler:
    """Build a project compiler for a chosen model.

    ``NEMOTRON_CLOUD`` selects the hosted Nemotron API directly; any other value
    is a local gateway model, run as primary with Nemotron as automatic fallback.
    """
    from workflow_compiler.config import get_settings
    from workflow_compiler.llm.factory import build_fallback_provider
    from workflow_compiler.llm.providers.nemotron import NemotronProvider
    from workflow_compiler.project_compiler import ProjectCompiler

    settings = get_settings()
    provider: BaseLLMProvider
    if model == NEMOTRON_CLOUD:
        provider = NemotronProvider(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
        )
    else:
        provider = build_fallback_provider(settings, local_model_override=model)
    return ProjectCompiler.from_settings(llm_provider=provider, settings=settings)
