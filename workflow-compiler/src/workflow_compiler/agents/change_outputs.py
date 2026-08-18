"""ChangeOutputsAgent — the LLM half of the post-approval change outputs.

Three prompts, one method each, all returning plans the deterministic engine
(:mod:`workflow_compiler.change_outputs.engine`) disposes of:

* ``update_diagrams`` → :class:`DiagramUpdatePlan` (``llm.structured``);
* ``rewrite_source_file`` → the full updated file as ONE fenced code block via
  ``llm.complete`` — a whole Python file inside JSON is what long-context
  models truncate and mis-escape, so the file protocol is a fence, extracted
  deterministically; an unclosed fence is continued (``continue_source_file``)
  and a file that fails ``ast.parse`` gets one repair round
  (``repair_source_file``);
* ``update_test_cases`` → :class:`TestCaseUpdatePlan` (``llm.structured``).

The agent never touches the project or the knowledge base; the engine feeds it
text and takes text back.
"""

from __future__ import annotations

from dataclasses import dataclass

from workflow_compiler.change_outputs.code import FencedCode, continue_code, extract_code
from workflow_compiler.change_outputs.models import DiagramUpdatePlan, TestCaseUpdatePlan
from workflow_compiler.exceptions import CompilationError
from workflow_compiler.interfaces.llm import BaseLLMProvider
from workflow_compiler.prompts import PromptManager

_DIAGRAMS_PROMPT = "update_diagrams"
_REWRITE_PROMPT = "rewrite_source_file"
_REPAIR_PROMPT = "repair_source_file"
_CONTINUE_PROMPT = "continue_source_file"
_TESTS_PROMPT = "update_test_cases"

_DIAGRAMS_SYSTEM = (
    "You are a meticulous software architect. You update Mermaid diagrams for an "
    "approved change and respond with strict JSON only."
)
_CODE_SYSTEM = (
    "You are a meticulous senior Python engineer implementing an approved change in an "
    "existing Temporal code base. You answer with exactly one fenced code block "
    "containing the complete file and nothing else."
)
_TESTS_SYSTEM = (
    "You are a meticulous QA lead extending a test-case matrix and test plan for an "
    "approved change. Respond with strict JSON only."
)

#: Output budget for one file (a 300-line Python file is ~4k tokens; leave room).
FILE_MAX_TOKENS = 8192
#: How many times an unclosed fence is continued before giving up.
MAX_CONTINUATIONS = 2


@dataclass(frozen=True)
class RewriteResult:
    """A rewritten file as the agent hands it back (before the engine's checks)."""

    code: str
    found: bool  # the model answered with code at all
    truncated: bool  # at least one continuation was needed
    closed: bool  # the final answer ended with a closing fence
    notes: str = ""


class ChangeOutputsAgent:
    """Draft diagrams, source files and test rows through the LLM (plans only)."""

    def __init__(
        self,
        llm: BaseLLMProvider | None = None,
        *,
        prompt_manager: PromptManager | None = None,
        file_max_tokens: int = FILE_MAX_TOKENS,
    ) -> None:
        self._llm = llm
        self._prompts = prompt_manager or PromptManager()
        self._file_max_tokens = file_max_tokens

    def _require_llm(self) -> BaseLLMProvider:
        if self._llm is None:
            raise CompilationError("ChangeOutputsAgent requires an LLM provider.")
        return self._llm

    async def update_diagrams(
        self,
        *,
        change_title: str,
        change_spec: str,
        design_summary: str,
        spec_summary: str,
        original_diagrams: str,
        new_diagrams: str,
        required_states: str,
        kg_context: str = "",
        repair_note: str = "",
    ) -> DiagramUpdatePlan:
        prompt = self._prompts.render(
            _DIAGRAMS_PROMPT,
            change_title=change_title,
            change_spec=change_spec,
            design_summary=design_summary,
            spec_summary=spec_summary,
            original_diagrams=original_diagrams,
            new_diagrams=new_diagrams,
            required_states=required_states,
            kg_context=kg_context,
            repair_note=repair_note,
        )
        return await self._require_llm().structured(
            prompt, DiagramUpdatePlan, system=_DIAGRAMS_SYSTEM
        )

    async def rewrite_file(
        self,
        *,
        path: str,
        reason: str,
        components: str,
        current_content: str,
        sibling_signatures: str,
        change_spec: str,
        design_summary: str,
        document_excerpt: str,
        import_root: str,
        kg_context: str = "",
        extra_rules: str = "",
    ) -> RewriteResult:
        """Ask for the full updated file; continue an unclosed fence up to twice."""
        llm = self._require_llm()
        prompt = self._prompts.render(
            _REWRITE_PROMPT,
            path=path,
            reason=reason,
            components=components,
            current_content=current_content,
            sibling_signatures=sibling_signatures,
            change_spec=change_spec,
            design_summary=design_summary,
            document_excerpt=document_excerpt,
            import_root=import_root or "src",
            kg_context=kg_context,
            extra_rules=extra_rules,
        )
        answer = await llm.complete(
            prompt, system=_CODE_SYSTEM, max_tokens=self._file_max_tokens
        )
        fenced = extract_code(answer)
        if not fenced.found:
            return RewriteResult(code="", found=False, truncated=False, closed=False)
        truncated = False
        for _ in range(MAX_CONTINUATIONS):
            if fenced.closed:
                break
            truncated = True
            tail = "\n".join(fenced.code.rstrip("\n").split("\n")[-12:])
            follow = self._prompts.render(_CONTINUE_PROMPT, path=path, tail=tail)
            more = await llm.complete(
                follow, system=_CODE_SYSTEM, max_tokens=self._file_max_tokens
            )
            fenced = continue_code(fenced.code, more)
        return RewriteResult(
            code=fenced.code, found=True, truncated=truncated, closed=fenced.closed
        )

    async def repair_file(self, *, path: str, code: str, error: str) -> FencedCode:
        """One repair round for a file that failed a deterministic check."""
        prompt = self._prompts.render(_REPAIR_PROMPT, path=path, code=code, error=error)
        answer = await self._require_llm().complete(
            prompt, system=_CODE_SYSTEM, max_tokens=self._file_max_tokens
        )
        return extract_code(answer)

    async def update_test_cases(
        self,
        *,
        change_title: str,
        change_request_id: str,
        change_spec: str,
        existing_matrix: str,
        test_plan_excerpt: str,
        tests_summary: str,
        design_summary: str,
        next_tc_id: str,
        tc_types: str,
        kg_context: str = "",
    ) -> TestCaseUpdatePlan:
        prompt = self._prompts.render(
            _TESTS_PROMPT,
            change_title=change_title,
            change_request_id=change_request_id,
            change_spec=change_spec,
            existing_matrix=existing_matrix,
            test_plan_excerpt=test_plan_excerpt,
            tests_summary=tests_summary,
            design_summary=design_summary,
            next_tc_id=next_tc_id,
            tc_types=tc_types,
            kg_context=kg_context,
        )
        return await self._require_llm().structured(
            prompt, TestCaseUpdatePlan, system=_TESTS_SYSTEM
        )
