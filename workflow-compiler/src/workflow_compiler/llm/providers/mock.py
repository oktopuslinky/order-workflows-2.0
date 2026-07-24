"""In-memory mock provider for tests and offline development."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from workflow_compiler.exceptions import LLMProviderError
from workflow_compiler.interfaces.llm import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)

#: Canned demo payloads (keyed by output-schema class name) used when
#: ``script_defaults`` is enabled and the structured queue is empty. They form
#: one small, coherent demo workflow so every CLI path (`--provider mock`) runs
#: offline end to end — discovery through Temporal code generation.
_DEMO_RESPONSES: dict[str, dict[str, Any]] = {
    "WorkflowDiscovery": {
        "name": "Demo Order Workflow",
        "purpose": "Validate, reserve, and ship a customer order.",
        "actors": ["Customer", "Warehouse"],
        "systems": ["Order Service", "Inventory Service"],
        "trigger_events": ["order submitted"],
        "start_states": ["received"],
        "end_states": ["shipped", "rejected"],
        "confidence": 0.9,
    },
    "FactExtraction": {
        "inputs": ["order_id", "customer_id"],
        "outputs": ["confirmation_id"],
        "retries": ["Reserve inventory: retry up to 3 times with backoff"],
        "activity_nodes": [
            {"id": "a1", "name": "Validate order"},
            {"id": "a2", "name": "Reserve inventory"},
            {"id": "a3", "name": "Ship order"},
        ],
        "decision_nodes": [
            {
                "id": "d1",
                "question": "Is the order valid?",
                "after": "a1",
                "yes_target": "a2",
                "no_target": "e1",
            }
        ],
        "exception_nodes": [{"id": "e1", "reason": "OrderInvalid", "raised_by": "a1"}],
        "compensation_nodes": [
            {"id": "c1", "name": "Release inventory", "compensates": "a2"}
        ],
        "event_nodes": [{"id": "v1", "name": "order shipped", "emitted_by": "a3"}],
        "confidence": 0.9,
    },
    "WorkflowsDiscovery": {
        "workflows": [
            {
                "name": "Demo Order Workflow",
                "purpose": "Validate, reserve, and ship a customer order.",
            }
        ],
        "dependencies": [],
        "confidence": 0.9,
    },
    "ReviewResult": {},
    "CVPAOutput": {},
    "EditPlan": {
        "patches": [
            {
                "action": "add",
                "target": "rule",
                "payload": {"value": "Mock-edited: refunds require manager approval"},
                "evidence": {"quote": "mock edit request entry"},
            }
        ],
        "note": "canned mock edit plan",
    },
    "TemporalDesignOutput": {
        "workflow_name": "DemoOrderWorkflow",
        "task_queue": "demo-orders",
        "activities": [
            {"name": "Validate order", "timeout_seconds": 10},
            {"name": "Reserve inventory"},
            {"name": "Ship order"},
        ],
        "compensation_activities": [
            {"name": "Release inventory", "compensates": "ReserveInventory"}
        ],
        "default_retry_policy": {"maximum_attempts": 3},
        "confidence": 0.9,
    },
}


class MockProvider(BaseLLMProvider):
    """A deterministic provider that returns queued or default responses.

    Useful for testing agents and the compiler without any network access while
    still honoring the :class:`BaseLLMProvider` contract.
    """

    name: ClassVar[str] = "mock"

    def __init__(
        self,
        *,
        completions: Sequence[str] | None = None,
        structured: Sequence[BaseModel | dict[str, Any]] | None = None,
        embeddings: Sequence[list[list[float]]] | None = None,
        default_completion: str = "mock-response",
        script_defaults: bool = False,
    ) -> None:
        """Seed response queues; queues are consumed in order, FIFO.

        With ``script_defaults`` enabled (the factory's ``mock`` registration
        uses it), an empty structured queue falls back to a canned demo response
        for the requested schema instead of raising — which is what lets every
        CLI command run offline with ``--provider mock``. Tests that assert an
        exact call sequence construct the provider directly and keep the strict
        raising behavior.
        """
        self._completions = list(completions or [])
        self._structured = list(structured or [])
        self._embeddings = list(embeddings or [])
        self._default_completion = default_completion
        self._script_defaults = script_defaults
        #: Recorded ``(method, prompt)`` calls, for assertions in tests.
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Return the next queued completion, or the default."""
        self.calls.append(("complete", prompt))
        if self._completions:
            return self._completions.pop(0)
        return self._default_completion

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Return the next queued structured response validated into ``schema``."""
        self.calls.append(("structured", prompt))
        if not self._structured:
            if self._script_defaults:
                return self._demo_response(schema)
            raise LLMProviderError("MockProvider has no structured responses queued.")
        item = self._structured.pop(0)
        if isinstance(item, schema):
            return item
        return schema.model_validate(item)

    @staticmethod
    def _demo_response(schema: type[T]) -> T:
        """Synthesize a canned (or schema-default) response for ``schema``."""
        payload = _DEMO_RESPONSES.get(schema.__name__)
        if payload is not None:
            return schema.model_validate(payload)
        try:
            return schema()
        except Exception as error:  # pragma: no cover - schema without defaults
            raise LLMProviderError(
                f"MockProvider has no scripted default for schema {schema.__name__!r}."
            ) from error

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return the next queued embedding batch, or deterministic stand-ins."""
        self.calls.append(("embed", "|".join(texts)))
        if self._embeddings:
            return self._embeddings.pop(0)
        return [[float(len(text))] for text in texts]
