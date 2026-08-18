"""ChangeSpecAgent — extract a change spec from a TDD; interpret answers about it.

Follows the app's agent recipe: a plain class over :class:`BaseLLMProvider`,
one prompt per method, a permissive pydantic plan back, and deterministic
cleaning here (kind / change-type coercion, de-duplication, provenance). The
LLM specifies; :mod:`workflow_compiler.spec.change_ingest` and the dialogue
engine dispose.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.kg.models import KgImpactRow
from workflow_compiler.models import (
    ChangeAnswerPlan,
    ChangeSpec,
    ChangeSpecDraft,
    ComponentChange,
    Provenance,
    SpecItem,
)
from workflow_compiler.models.dialogue import DraftedQuestions
from workflow_compiler.prompts import PromptManager
from workflow_compiler.spec.change_ingest import coerce_change_type, coerce_kind

_EXTRACT_PROMPT = "extract_change_spec"
_INTERPRET_PROMPT = "interpret_change_answer"
_DRAFT_PROMPT = "draft_change_questions"

_EXTRACT_SYSTEM = (
    "You are a precise senior engineer. Read design documents against the existing "
    "code base and respond with strict JSON only."
)
_INTERPRET_SYSTEM = (
    "You translate a human's answer about a change specification into minimal "
    "deterministic updates. Respond with strict JSON only."
)
_DRAFT_SYSTEM = (
    "You turn validator findings about a change specification into a short list "
    "of clear questions for an engineer, each with likely answers. Respond with "
    "strict JSON only."
)

#: Cap on components kept from one extraction (a TDD names dozens at most).
MAX_COMPONENTS = 60

_WORD = re.compile(r"[A-Za-z0-9_./-]+")


def impact_table_text(rows: Iterable[KgImpactRow], *, limit: int = 120) -> str:
    """Render impact rows as ``type | name | node id | path`` lines for the prompt."""
    lines: list[str] = []
    for row in list(rows)[:limit]:
        lines.append(f"{row.type} | {row.name} | {row.node_id} | {row.path or ''}")
    return "\n".join(lines) if lines else "(none)"


def seed_components_text(components: Sequence[ComponentChange]) -> str:
    """Render seed components as ``kind | name | change | path | rationale`` lines."""
    lines = [
        f"{c.kind.value} | {c.name} | {c.change_type.value} | {c.path} | "
        f"{(c.proposed or c.existing).splitlines()[0] if (c.proposed or c.existing) else ''}"
        for c in components
    ]
    return "\n".join(lines) if lines else "(none)"


def _grounded(name: str, text: str) -> bool:
    """Whether ``name`` (or its last path/identifier segment) appears in ``text``."""
    needle = name.strip().lower()
    if not needle:
        return False
    haystack = text.lower()
    if needle in haystack:
        return True
    tail = re.split(r"[/:]", needle)[-1]
    return bool(tail) and tail in haystack


class ChangeSpecAgent:
    """Extract / update the change spec through the LLM (plans only, no side effects)."""

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        """Store the provider and prompt manager."""
        self._llm = llm
        self._prompts = prompt_manager or PromptManager()

    def _require_llm(self) -> BaseLLMProvider:
        if self._llm is None:
            raise CompilationError("ChangeSpecAgent requires an LLM provider.")
        return self._llm

    async def extract(
        self,
        document_text: str,
        *,
        kg_context: str | None = None,
        impact_table: Iterable[KgImpactRow] = (),
        seed_components: Sequence[ComponentChange] = (),
        requirement_ids: Sequence[str] = (),
        sources: Sequence[str] = (),
    ) -> ChangeSpec:
        """Extract the change spec for ``document_text`` (a TDD).

        ``kg_context`` is the grounder's rendered block, ``impact_table`` the
        deterministic traversal rows, ``seed_components`` the change request's
        parsed impact rows (kept unless the design drops them) and
        ``requirement_ids`` the only ids the model may cite. Provenance:
        components whose name appears in the document are ``document_grounded``,
        others ``llm_inferred``; seed components the model kept but did not
        return keep their seed provenance.
        """
        if not document_text or not document_text.strip():
            raise CompilationError("Cannot extract a change spec from an empty document.")
        prompt = self._prompts.render(
            _EXTRACT_PROMPT,
            document_text=document_text,
            kg_context=kg_context or "",
            impact_table=impact_table_text(impact_table),
            seed_components=seed_components_text(seed_components),
            requirement_ids=", ".join(requirement_ids) if requirement_ids else "(none)",
        )
        draft = await self._require_llm().structured(
            prompt, ChangeSpecDraft, system=_EXTRACT_SYSTEM
        )
        return self.to_spec(
            draft,
            document_text,
            seed_components=seed_components,
            requirement_ids=requirement_ids,
            sources=sources,
        )

    @staticmethod
    def to_spec(
        draft: ChangeSpecDraft,
        document_text: str,
        *,
        seed_components: Sequence[ComponentChange] = (),
        requirement_ids: Sequence[str] = (),
        sources: Sequence[str] = (),
    ) -> ChangeSpec:
        """Deterministically clean a draft into a :class:`ChangeSpec`.

        Kind / change-type words are coerced onto the enums, requirement ids are
        filtered to the allowed set (when one is given), duplicates (same
        kind + name) collapse onto the first, and empty names are dropped.
        """
        allowed = {r.strip().upper() for r in requirement_ids} if requirement_ids else None
        seeds_by_key = {c.key(): c for c in seed_components}
        components: list[ComponentChange] = []
        seen: set[str] = set()
        for item in draft.components:
            name = item.name.strip().strip("`")
            if not name:
                continue
            kind = coerce_kind(item.kind)
            key = f"{kind.value}:{name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            reqs = [r.strip() for r in item.requirement_ids if r.strip()]
            if allowed is not None:
                reqs = [r for r in reqs if r.upper() in allowed]
            seed = seeds_by_key.get(key)
            path = item.path.strip().strip("`") or (seed.path if seed else "")
            existing = item.existing.strip() or (seed.existing if seed else "")
            proposed = item.proposed.strip() or (seed.proposed if seed else "")
            if not reqs and seed is not None:
                reqs = list(seed.requirement_ids)
            components.append(
                ComponentChange(
                    name=name,
                    kind=kind,
                    path=path,
                    existing=existing,
                    proposed=proposed,
                    change_type=coerce_change_type(item.change_type),
                    requirement_ids=reqs,
                    provenance=(
                        Provenance.DOCUMENT_GROUNDED
                        if _grounded(name, document_text)
                        else Provenance.LLM_INFERRED
                    ),
                )
            )
            if len(components) >= MAX_COMPONENTS:
                break
        if not components and seed_components:
            # A model that returns nothing has not "dropped" the seeds — it has
            # failed to answer; the change request's own rows are the floor.
            components = [c.model_copy(deep=True) for c in seed_components]
        return ChangeSpec(
            components=components,
            assumptions=[
                SpecItem(text=text.strip(), provenance=Provenance.LLM_INFERRED)
                for text in draft.assumptions
                if text.strip()
            ],
            open_questions=[
                SpecItem(text=text.strip(), provenance=Provenance.LLM_INFERRED)
                for text in draft.open_questions
                if text.strip()
            ],
            sources=list(sources),
        )

    async def draft_questions(
        self,
        *,
        findings_block: str,
        questions_block: str,
        current_changes: str,
    ) -> DraftedQuestions:
        """Return the dialogue agenda for the change spec's unresolved items."""
        prompt = self._prompts.render(
            _DRAFT_PROMPT,
            findings_block=findings_block or "(none)",
            questions_block=questions_block or "(none)",
            current_changes=current_changes,
        )
        return await self._require_llm().structured(
            prompt, DraftedQuestions, system=_DRAFT_SYSTEM
        )

    async def interpret_answer(
        self,
        *,
        question: str,
        answer: str,
        current_changes: str,
        prior_followup: str | None = None,
    ) -> ChangeAnswerPlan:
        """Return the update plan for one prose answer about the change spec.

        A second follow-up would let the conversation loop, so when one was
        already asked the plan's ``needs_followup`` is forced off here too.
        """
        followup_context = (
            "\nA clarifying follow-up was ALREADY asked for this question:\n"
            f"{prior_followup}\n"
            "Do not ask another — map the answer to updates or park it.\n"
            if prior_followup
            else ""
        )
        prompt = self._prompts.render(
            _INTERPRET_PROMPT,
            question=question,
            answer=answer,
            followup_context=followup_context,
            current_changes=current_changes,
        )
        plan = await self._require_llm().structured(
            prompt, ChangeAnswerPlan, system=_INTERPRET_SYSTEM
        )
        if prior_followup and plan.needs_followup:
            return plan.model_copy(
                update={"needs_followup": False, "followup_question": None}
            )
        return plan


__all__ = [
    "MAX_COMPONENTS",
    "ChangeSpecAgent",
    "impact_table_text",
    "seed_components_text",
]
