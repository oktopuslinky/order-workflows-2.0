"""WorkflowSegmenterAgent: split a document into its constituent workflows.

Unlike the pipeline agents this operates at the *document* level (it produces
several workflows), so it does not implement the ``BaseAgent.run(state)`` contract.
It depends only on :class:`BaseLLMProvider`, keeping the vendor-agnostic rule.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import WorkflowSegment
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "segment_document"
_SYSTEM = (
    "You are a precise business-process analyst. Split the document into distinct "
    "workflows, copying supporting text verbatim, and respond with strict JSON."
)


class _SegmentOut(BaseModel):
    """One workflow as returned by the LLM (permissive; cleaned by the agent)."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="")
    name: str = Field(default="")
    summary: str = Field(default="")
    text: str = Field(default="")
    invokes: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class DocumentSegmentation(BaseModel):
    """Structured LLM output for document segmentation."""

    model_config = ConfigDict(extra="ignore")

    segments: list[_SegmentOut] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)


def _clean_list(items: list[str]) -> list[str]:
    """Strip, drop empties, and de-duplicate (case-insensitively) a string list."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        text = item.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def canonical_name(raw: str) -> str:
    """Normalize a workflow name to a stable PascalCase-friendly phrase.

    Keeps human-readable spacing (``"Order Cancellation"``) but strips noise so the
    same workflow is named identically wherever it is referenced — which is what
    lets ``invokes`` links match a child workflow by name downstream.
    """
    words = re.findall(r"[A-Za-z0-9]+", raw)
    return " ".join(word[:1].upper() + word[1:] for word in words) if words else raw.strip()


class WorkflowSegmenterAgent:
    """Segment a document into :class:`WorkflowSegment` objects via the LLM."""

    name = "workflow-segmenter"

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Store the LLM provider and an optional prompt manager."""
        self._llm = llm
        self._prompts = prompt_manager or PromptManager()

    async def segment(self, document_text: str) -> tuple[list[WorkflowSegment], list[str]]:
        """Return the document's workflows and any document-level clarifications.

        Guarantees at least one segment: if the model returns none (or an empty
        result) the whole document is treated as a single workflow so the caller
        always has something to author.
        """
        if self._llm is None:
            raise CompilationError("WorkflowSegmenterAgent requires an LLM provider.")
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot segment an empty document.")

        prompt = self._prompts.render(_PROMPT_NAME, document_text=document_text)
        result = await self._llm.structured(prompt, DocumentSegmentation, system=_SYSTEM)

        segments = self._clean_segments(result.segments, document_text)
        if not segments:
            segments = [
                WorkflowSegment(id="w1", name="Workflow", source_text=document_text)
            ]
        return segments, _clean_list(result.clarifications)

    # -- internals ----------------------------------------------------------

    def _clean_segments(
        self, raw: list[_SegmentOut], document_text: str
    ) -> list[WorkflowSegment]:
        """Normalize ids/names, drop empty segments, and resolve invokes to names."""
        cleaned: list[WorkflowSegment] = []
        for index, seg in enumerate(raw, start=1):
            name = canonical_name(seg.name)
            body = seg.text.strip() or document_text
            if not name:
                continue
            cleaned.append(
                WorkflowSegment(
                    id=seg.id.strip() or f"w{index}",
                    name=name,
                    summary=seg.summary.strip(),
                    source_text=body,
                    invokes=[canonical_name(x) for x in _clean_list(seg.invokes)],
                    questions=_clean_list(seg.questions),
                )
            )
        # Drop invokes links that do not resolve to a known workflow name.
        known = {s.name for s in cleaned}
        for out_seg in cleaned:
            out_seg.invokes = [
                name for name in out_seg.invokes if name in known and name != out_seg.name
            ]
        return cleaned
