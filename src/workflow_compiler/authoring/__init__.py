"""Authoring: turn extracted workflow state into ideal-format Markdown.

This package is the deterministic counterpart to the LLM extraction stages — it
renders a :class:`~workflow_compiler.models.state.WorkflowState` into a document
shaped like ``examples/ideal_temporal_workflow.md`` (the proven "perfect input"),
assembles per-workflow sections into one editable master document, and splits an
edited master back into per-workflow documents.
"""

from __future__ import annotations

from workflow_compiler.authoring.ideal_render import render_ideal_section
from workflow_compiler.authoring.master_assemble import assemble_master
from workflow_compiler.authoring.parse_master import (
    ParsedMaster,
    ParsedWorkflow,
    parse_master,
)
from workflow_compiler.authoring.split import split_master

__all__ = [
    "ParsedMaster",
    "ParsedWorkflow",
    "assemble_master",
    "parse_master",
    "render_ideal_section",
    "split_master",
]
