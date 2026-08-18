"""FastAPI dependency providers.

These resolve the compiler for request handlers. The compiler is built once from
application settings (``.env``) and cached for the process. Tests override
``get_compiler`` via ``app.dependency_overrides`` to inject a mock provider and
an in-memory store.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Depends

from workflow_compiler.compiler import WorkflowCompiler
from workflow_compiler.kg.service import KgService

if TYPE_CHECKING:
    from workflow_compiler.change.service import ChangeRequestService
    from workflow_compiler.interfaces.executor import WorkflowExecutor
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


@lru_cache(maxsize=1)
def get_executor() -> WorkflowExecutor:
    """Provide the process-wide executor for running generated bundles.

    Cached because it owns long-lived state: a Temporal client and the pool of
    bundle worker subprocesses, which are reused across runs (a workflow parked
    on a 24-hour timer needs its worker to outlive the request that started it).

    Constructing it never imports ``temporalio`` — that happens on first use, so
    the API starts cleanly without the optional ``[run]`` extra and reports
    Temporal as unavailable instead. Tests override this with ``FakeExecutor``.
    """
    from workflow_compiler.config import get_settings
    from workflow_compiler.execution.temporal import TemporalExecutor

    settings = get_settings()
    return TemporalExecutor(
        address=settings.temporal_address, namespace=settings.temporal_namespace
    )


def get_local_provider(
    *, model: str | None = None, timeout: float | None = None
) -> BaseLLMProvider:
    """Build a local eGPU gateway provider (for model discovery and health probes).

    ``model``/``timeout`` pin a specific advertised model and a short deadline,
    which is what probing one model's health needs; both default to the
    configured values.
    """
    from workflow_compiler.config import get_settings
    from workflow_compiler.llm.factory import build_local_provider

    return build_local_provider(get_settings(), model_override=model, timeout=timeout)


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


def provider_for_selection(provider_name: str, model: str | None) -> BaseLLMProvider:
    """Build the LLM provider for an explicit per-request provider choice.

    ``local`` runs the eGPU gateway alone (fails fast when it is down),
    ``nemotron`` the hosted NVIDIA API, and ``local-fallback`` the gateway with
    automatic Nemotron fallback. ``model`` pins a gateway model for the local
    providers (else the gateway's advertised default is used); it is ignored
    for ``nemotron``. Shared by the compile routes and the knowledge-base
    routes so "selectable per request" means the same thing everywhere.
    """
    from workflow_compiler.config import get_settings
    from workflow_compiler.exceptions import LLMProviderError
    from workflow_compiler.llm.factory import build_fallback_provider, build_local_provider
    from workflow_compiler.llm.providers.nemotron import NemotronProvider

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
    return provider


def project_compiler_for_selection(
    provider_name: str, model: str | None
) -> ProjectCompiler:
    """Build a project compiler for an explicit per-compile provider choice
    (see :func:`provider_for_selection` for the provider semantics)."""
    from workflow_compiler.config import get_settings
    from workflow_compiler.project_compiler import ProjectCompiler

    provider = provider_for_selection(provider_name, model)
    return ProjectCompiler.from_settings(llm_provider=provider, settings=get_settings())


#: ``(provider_name, model) -> ProjectCompiler`` — how the compile routes turn an
#: explicit per-request provider choice into a compiler.
CompilerSelector = Callable[[str, "str | None"], "ProjectCompiler"]


def get_compiler_selector() -> CompilerSelector:
    """Provide the per-request compiler selector (:func:`project_compiler_for_selection`).

    A dependency so tests can override it with a selector that returns the mock
    compiler whatever provider a request names — the send-to-workflow route
    always names one (cloud Nemotron by default), so without this override it
    would build a real provider.
    """
    return project_compiler_for_selection


#: Provider the knowledge-base routes use when a request names none. Cloud on
#: purpose: enrichment is ~one call per corpus file and must never land on the
#: single-GPU local gateway by default (plan D6 / cross-cutting rule).
KB_DEFAULT_PROVIDER = "nemotron"


def kb_provider_factory(provider_name: str | None, model: str | None) -> BaseLLMProvider:
    """The ``KgService`` provider factory: per-request selection, cloud default."""
    return provider_for_selection(provider_name or KB_DEFAULT_PROVIDER, model)


@lru_cache(maxsize=1)
def get_kg_service() -> KgService:
    """Provide the process-wide :class:`KgService` (file store under the state root).

    Tests override this with a service on an in-memory store and a mock
    provider factory, exactly like ``get_project_compiler``.
    """
    from workflow_compiler.config import get_settings
    from workflow_compiler.kg.service import KgService
    from workflow_compiler.kg.store import FileKnowledgeBaseStore

    settings = get_settings()
    return KgService(
        FileKnowledgeBaseStore(settings.state_store_path),
        kb_provider_factory,
        max_upload_bytes=settings.kg_max_upload_mb * 1024 * 1024,
        default_budget=settings.kg_retrieve_budget,
    )


def get_change_service(kg: KgService = Depends(get_kg_service)) -> ChangeRequestService:
    """Provide the :class:`ChangeRequestService` (file store under the state root).

    Built per request on top of whatever ``get_kg_service`` resolves to, so a
    test that overrides the KG service gets a change service on the same
    knowledge bases; tests may also override this dependency directly.
    """
    from workflow_compiler.change.service import ChangeRequestService
    from workflow_compiler.config import get_settings
    from workflow_compiler.storage.change_store import FileChangeRequestStore

    settings = get_settings()
    return ChangeRequestService(
        FileChangeRequestStore(settings.state_store_path),
        kg,
        kb_provider_factory,
        kg_budget=settings.change_kg_budget,
    )
