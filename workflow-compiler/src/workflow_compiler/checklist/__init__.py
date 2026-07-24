"""Pre-generation readiness checklist: validate and amend.

The checklist is computed between fact extraction and graph/code generation. It
validates the discovered facts/structure against the requirements that
``examples/ideal_temporal_workflow.md`` is known to satisfy; uncleared items
surface as the spec's **Open Questions**, and answered questions are folded back
in as deterministic amendments (no extra LLM call) at spec approval.
"""

from __future__ import annotations

from workflow_compiler.checklist.validator import ChecklistValidator

__all__ = ["ChecklistValidator"]
