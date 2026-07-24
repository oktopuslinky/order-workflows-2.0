"""EditInterpreterAgent: translate edit-request entries into an EditPlan.

The deterministic parser (``spec/edit_ingest.py``) has already validated the
document's structure; this agent only sees the natural-language entries of one
section plus the rendered current spec, and returns the structured
:class:`~workflow_compiler.models.edit.EditPlan` the deterministic appliers
consume. It never applies anything itself.
"""

from __future__ import annotations

from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.models import EditPlan
from workflow_compiler.prompts import PromptManager

_PROMPT_NAME = "interpret_edit_request"

_EDIT_SYSTEM = (
    "You translate a human-authored edit request into minimal deterministic "
    "patch operations against the current workflow specification. The edit "
    "request carries human authority: you never refuse or second-guess it, and "
    "you never invent changes it does not ask for. Every entry must map to one "
    "or more operations; entries you cannot map go verbatim into 'unresolved'. "
    "Respond with strict JSON only."
)


class EditInterpreterAgent:
    """Interpret one edit-request section against the current spec."""

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._llm = llm_provider
        self._prompts = prompt_manager or PromptManager()

    async def interpret(
        self,
        *,
        slug: str,
        edit_section: str,
        current_spec: str,
        project_context: str,
    ) -> EditPlan:
        """Return the :class:`EditPlan` for one workflow's edit section."""
        if self._llm is None:
            raise CompilationError("EditInterpreterAgent requires an LLM provider.")
        prompt = self._prompts.render(
            _PROMPT_NAME,
            workflow_slug=slug,
            edit_section=edit_section,
            current_spec=current_spec,
            project_context=project_context,
        )
        return await self._llm.structured(prompt, EditPlan, system=_EDIT_SYSTEM)
