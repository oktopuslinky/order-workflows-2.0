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
    if model == NEMOTRON_CLOUD:
        return project_compiler_for_selection("nemotron", None)
    return project_compiler_for_selection("local-fallback", model)


#: Providers a compile request may select per-run. Kept in sync with the
#: frontend provider picker (app/page.tsx PROVIDER_OPTIONS).
SELECTABLE_PROVIDERS = ("local", "nemotron", "local-fallback")


def project_compiler_for_selection(
    provider_name: str, model: str | None
) -> ProjectCompiler:
    """Build a project compiler for an explicit per-compile provider choice.

    ``local`` runs the eGPU gateway alone (fails fast when it is down),
    ``nemotron`` the hosted NVIDIA API, and ``local-fallback`` the gateway with
    automatic Nemotron fallback. ``model`` pins a gateway model for the local
    providers (else the gateway's advertised default is used); it is ignored
    for ``nemotron``.
    """
    from workflow_compiler.config import get_settings
    from workflow_compiler.exceptions import LLMProviderError
    from workflow_compiler.llm.factory import build_fallback_provider, build_local_provider
    from workflow_compiler.llm.providers.nemotron import NemotronProvider
    from workflow_compiler.project_compiler import ProjectCompiler

    settings = get_settings()
    provider: BaseLLMProvider
    if provider_name == "nemotron":
        provider = NemotronProvider(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
        )
    elif provider_name == "local":
        provider = build_local_provider(settings, model_override=model)
    elif provider_name == "local-fallback":
        provider = build_fallback_provider(settings, local_model_override=model)
    else:
        raise LLMProviderError(
            f"Unknown compile provider '{provider_name}'. "
            f"Available: {', '.join(SELECTABLE_PROVIDERS)}."
        )
    return ProjectCompiler.from_settings(llm_provider=provider, settings=settings)
