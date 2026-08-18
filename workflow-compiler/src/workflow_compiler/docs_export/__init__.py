"""Deterministic Word / Excel export of change-request artifacts (Phase 2).

Markdown stays the source of truth (``change/render.py`` ⇄ ``change/parse.py``);
this package projects the parsed documents into ``.docx`` / ``.xlsx`` files that
follow the manager's reference templates (research digest §5): 22 pt bold
document-type title, 14 pt subtitle, bold ``Label: value`` metadata block,
Word Heading 1/2, "List Paragraph" bullets, tables with a ``2F5496`` header
row and white bold text, ``☑  ``/``☐  `` checklists, Consolas inline code.

Nothing here calls a model — every byte is a pure function of the change
request, so exports are reproducible and testable offline.
"""

from .artifacts import (
    ArtifactExport,
    export_artifact,
    export_epic,
    export_impact,
    export_stories,
    export_story,
    export_tdd,
    export_test_case_preview,
)
from .bundle import BundleEntry, export_change_request, manifest_lines
from .docx_writer import DocxWriter
from .markdown_to_docx import render_markdown
from .xlsx_writer import (
    TC_COLUMNS,
    TestCaseRow,
    TestCaseSummary,
    read_test_case_rows,
    write_test_case_matrix,
)

__all__ = [
    "TC_COLUMNS",
    "ArtifactExport",
    "BundleEntry",
    "DocxWriter",
    "TestCaseRow",
    "TestCaseSummary",
    "export_artifact",
    "export_change_request",
    "export_epic",
    "export_impact",
    "export_stories",
    "export_story",
    "export_tdd",
    "export_test_case_preview",
    "manifest_lines",
    "read_test_case_rows",
    "render_markdown",
    "write_test_case_matrix",
]
