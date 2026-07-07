"""The spec validator: three review passes over a WorkflowSpec vs. the document.

This re-targets the sequential-review discipline (completeness → grounding →
consistency, minimal patches or ``no_change``) at the **spec** artifact: the
passes compare the rendered spec against the original document and propose
patches; a deterministic, **provenance-aware** applier disposes.

The provenance rule is what makes the validator usable in a human review loop:
a ``remove`` aimed at a ``HUMAN_PROVIDED`` element is converted into a finding
(flag for confirmation) instead of being applied — the validator challenges
human additions but never deletes them. LLM-proposed additions must ground in
the document (the underlying appliers drop ungrounded adds), so the validator
cannot inject hallucinations after the human has started reviewing.
"""

from __future__ import annotations

from workflow_compiler.agents.review_pipeline import (
    _METADATA_LIST_FIELDS,
    _METADATA_SCALAR_FIELDS,
    _REVIEW_SYSTEM,
    _SCALAR_CATEGORIES,
    FactsPatchApplier,
    MetadataPatchApplier,
    ReviewPass,
    _norm,
    _payload_value,
)
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import (
    CrossReference,
    Patch,
    PatchAction,
    Provenance,
    ReviewResult,
    SpecItem,
    WorkflowSpec,
)
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec.renderer import render_spec

_ENTITY_KINDS = frozenset({"activity", "decision", "exception", "compensation", "event"})
_ITEM_TARGETS: dict[str, str] = {
    "assumption": "assumptions",
    "ambiguity": "ambiguities",
    "question": "open_questions",
    "suggested_edit": "suggested_edits",
    "suggestion": "suggested_edits",
}

_PASSES: tuple[ReviewPass, ...] = (
    ReviewPass("review_spec_completeness", "completeness"),
    ReviewPass("review_spec_grounding", "grounding"),
    ReviewPass("review_spec_consistency", "consistency"),
)


class SpecPatchApplier:
    """Dispatch spec-level patches to the right deterministic applier.

    * metadata field targets → :class:`MetadataPatchApplier`;
    * entity / scalar-fact targets → :class:`FactsPatchApplier`;
    * ``assumption`` / ``ambiguity`` / ``question`` / ``suggested_edit`` adds →
      appended as :class:`SpecItem`s (deduplicated by text);
    * ``flag`` anywhere → recorded as a finding, artifact untouched;
    * ``remove`` of a human-provided element → converted to a finding.
    """

    def __init__(self) -> None:
        self._metadata = MetadataPatchApplier()
        self._facts = FactsPatchApplier()

    def apply(
        self, spec: WorkflowSpec, patches: list[Patch], document_text: str
    ) -> tuple[WorkflowSpec, list[str], str]:
        """Return ``(new_spec, findings, provenance_summary)``."""
        metadata_patches: list[Patch] = []
        facts_patches: list[Patch] = []
        findings: list[str] = []
        item_added = 0

        for patch in patches:
            kind, _, _ref = patch.target.partition(":")
            kind = kind.strip().lower()
            if patch.action == PatchAction.FLAG:
                findings.append(self._finding(patch))
                continue
            if kind in _ITEM_TARGETS:
                if patch.action == PatchAction.ADD:
                    item_added += int(self._add_item(spec, _ITEM_TARGETS[kind], patch))
                continue
            if patch.action == PatchAction.REMOVE and self._is_human(spec, patch):
                findings.append(
                    f"human-provided element '{patch.target}' is not supported by the "
                    "document — please confirm or remove it yourself"
                )
                continue
            if kind in _METADATA_LIST_FIELDS or kind in _METADATA_SCALAR_FIELDS:
                metadata_patches.append(patch)
            elif kind in _ENTITY_KINDS or kind in _SCALAR_CATEGORIES:
                facts_patches.append(patch)
            else:
                findings.append(self._finding(patch))

        summaries: list[str] = []
        if metadata_patches:
            metadata, summary = self._metadata.apply(
                spec.metadata, metadata_patches, document_text
            )
            spec.metadata = metadata
            summaries.append(f"metadata: {summary}")
        if facts_patches:
            facts, summary = self._facts.apply(spec.facts, facts_patches, document_text)
            spec.facts = facts
            summaries.append(f"facts: {summary}")
        if item_added:
            summaries.append(f"items: {item_added} added")
        if findings:
            summaries.append(f"findings: {len(findings)}")
        return spec, findings, "; ".join(summaries) or "no_change"

    @staticmethod
    def _finding(patch: Patch) -> str:
        note = _payload_value(patch, "note", "reason", "value") or "flagged by validator"
        return f"{patch.target or 'spec'}: {note}"

    @staticmethod
    def _is_human(spec: WorkflowSpec, patch: Patch) -> bool:
        """True when the patch's target element is human-provided."""
        kind, _, ref = patch.target.partition(":")
        kind = kind.strip().lower()
        if kind in _ENTITY_KINDS and ref.strip():
            return spec.provenance_of(f"{kind}:{ref.strip()}") == Provenance.HUMAN_PROVIDED
        if kind in _SCALAR_CATEGORIES:
            statement = _payload_value(patch, "value", "statement", "name")
            key = f"{_SCALAR_CATEGORIES[kind].value}:{statement.lower()}"
            return spec.provenance_of(key) == Provenance.HUMAN_PROVIDED
        return False

    @staticmethod
    def _add_item(spec: WorkflowSpec, field_name: str, patch: Patch) -> bool:
        text = _payload_value(patch, "text", "value", "question")
        if not text:
            return False
        items: list[SpecItem] = getattr(spec, field_name)
        if any(_norm(item.text).lower() == text.lower() for item in items):
            return False
        items.append(SpecItem(text=text, provenance=Provenance.LLM_INFERRED))
        return True


class SpecValidator:
    """Run the three spec review passes and fold their patches in."""

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._llm = llm
        self._prompts = prompt_manager or PromptManager()
        self._applier = SpecPatchApplier()

    async def validate(
        self,
        spec: WorkflowSpec,
        document_text: str,
        cross_references: list[CrossReference],
    ) -> tuple[WorkflowSpec, list[str], str]:
        """Validate ``spec`` against ``document_text``.

        Returns ``(patched_spec, findings, provenance_note)``. The passes are
        idempotent: validating an already-clean spec yields no changes and no
        findings.
        """
        if self._llm is None:
            raise CompilationError("SpecValidator requires an LLM provider.")

        findings: list[str] = []
        notes: list[str] = []
        for review_pass in _PASSES:
            current = render_spec(spec, cross_references)
            prompt = self._prompts.render(
                review_pass.prompt_name, document_text=document_text, current=current
            )
            result = await self._llm.structured(prompt, ReviewResult, system=_REVIEW_SYSTEM)
            spec, pass_findings, summary = self._applier.apply(
                spec, result.effective_patches(), document_text
            )
            findings.extend(f"{review_pass.label}: {f}" for f in pass_findings)
            notes.append(f"{review_pass.label}: {summary}")
        return spec, findings, "; ".join(notes)
