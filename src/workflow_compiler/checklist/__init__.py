"""Pre-generation readiness checklist: validate, report, and amend.

The checklist gate sits between fact extraction and graph/code generation. It
validates the discovered facts/structure against the requirements that
``examples/ideal_temporal_workflow.md`` is known to satisfy, renders an editable
report when something is missing, and folds the user's answers back in as
deterministic amendments (no extra LLM call).
"""

from __future__ import annotations

from workflow_compiler.checklist.validator import ChecklistValidator

__all__ = ["ChecklistValidator"]
