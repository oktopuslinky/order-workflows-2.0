"""Spec projection layer: deterministic Markdown render + parse-back-and-merge.

The structured :class:`~workflow_compiler.models.spec.WorkflowSpec` is the
source of truth; ``renderer.render_spec`` projects it to the Markdown file the
user reviews, and ``ingest.ingest_spec_markdown`` folds edits back in.
"""

from __future__ import annotations

from workflow_compiler.spec.ingest import IngestResult, ingest_spec_markdown
from workflow_compiler.spec.renderer import render_spec
from workflow_compiler.spec.validator import SpecPatchApplier, SpecValidator

__all__ = [
    "IngestResult",
    "SpecPatchApplier",
    "SpecValidator",
    "ingest_spec_markdown",
    "render_spec",
]
