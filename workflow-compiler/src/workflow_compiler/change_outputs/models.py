"""Post-approval change outputs (plan Phase 4, decisions D3 / D10).

Once a knowledge-graph-grounded project is approved, three deliverables are
produced from the knowledge base's *actual* files: updated Mermaid diagrams,
the modified code base with a diff per file, and the updated test-case matrix
plus a test-plan addendum. :class:`ChangeOutputs` is the record stored on
``CompilationProject.change_outputs``; the LLM plans at the bottom are what the
:class:`~workflow_compiler.agents.change_outputs.ChangeOutputsAgent` returns and
the deterministic engine (`change_outputs/engine.py`) turns into these records.

Every stage is recorded separately (:class:`StageRecord`) so a timeout in one
keeps the others' results — the engine persists after each stage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from workflow_compiler.docs_export.xlsx_writer import TestCaseRow
from workflow_compiler.models.base import WorkflowBaseModel


class _ContentModel(WorkflowBaseModel):
    """Base for records that carry file text verbatim (no whitespace stripping)."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
        str_strip_whitespace=False,
        frozen=False,
    )


#: The stages, in the order the engine runs them.
STAGES: tuple[str, ...] = ("diagrams", "code", "tests_doc")
StageName = Literal["diagrams", "code", "tests_doc"]


class DiagramKind(StrEnum):
    """Which of the reference diagrams an updated diagram is."""

    STATE = "state"
    SEQUENCE = "sequence"
    ARCHITECTURE = "architecture"
    STATE_PARTIAL = "state-partial"
    WORKFLOW = "workflow"  # the per-workflow spec mermaid (D10, section 4)


class UpdatedDiagram(_ContentModel):
    """One diagram file: its original text (when it existed) and the update."""

    name: str = Field(..., description="File name, e.g. 'order-state-machine.mmd'.")
    kind: DiagramKind = Field(default=DiagramKind.STATE, description="Diagram kind.")
    original: str | None = Field(
        default=None, description="Original Mermaid text from the knowledge base, if any."
    )
    updated: str = Field(default="", description="Updated Mermaid text.")
    notes: str = Field(default="", description="What changed, per the model.")
    source_path: str = Field(default="", description="Corpus path of the original, if any.")
    checks: list[str] = Field(
        default_factory=list, description="Deterministic check failures (empty = all passed)."
    )


class FileStatus(StrEnum):
    """How a code file changed."""

    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


class FileChecks(WorkflowBaseModel):
    """Post-rewrite checks on a Python file."""

    ast_ok: bool = Field(default=True, description="``ast.parse`` succeeded.")
    ast_error: str = Field(default="", description="Syntax error message when ``ast_ok`` is False.")
    ruff_ok: bool | None = Field(
        default=None, description="ruff (pyflakes-class rules) passed; None when ruff was not run."
    )
    ruff_output: str = Field(default="", description="ruff findings when ``ruff_ok`` is False.")
    repaired: bool = Field(default=False, description="A repair round was needed.")
    truncated: bool = Field(
        default=False, description="The model's answer was cut short and continued/repaired."
    )


class ChangedFile(_ContentModel):
    """One file of the code bundle: original, updated and the unified diff."""

    path: str = Field(..., description="Corpus-relative path (POSIX).")
    status: FileStatus = Field(default=FileStatus.UNCHANGED)
    original: str = Field(default="", description="Original text (empty when added).")
    updated: str = Field(default="", description="Updated text (empty when removed).")
    unified_diff: str = Field(default="", description="``difflib.unified_diff`` output.")
    checks: FileChecks = Field(default_factory=FileChecks)
    reason: str = Field(
        default="",
        description="Why this file was rewritten (change-spec components / dependency).",
    )
    notes: str = Field(default="", description="The model's summary of the change.")


class CodeChangeBundle(WorkflowBaseModel):
    """The modified code base."""

    files: list[ChangedFile] = Field(default_factory=list)
    order: list[str] = Field(
        default_factory=list, description="Rewrite order (types → activities → workflow → …)."
    )
    import_root: str = Field(
        default="src",
        description="Package the corpus imports itself as (`from src.shared.types …`).",
    )
    code_root: str = Field(
        default="", description="Corpus directory holding the package (`existing_Codebase`)."
    )

    def changed(self) -> list[ChangedFile]:
        return [f for f in self.files if f.status is not FileStatus.UNCHANGED]


class TestDocUpdate(_ContentModel):
    """The updated test-case matrix and the test-plan addendum."""

    __test__ = False  # not a pytest class despite the name
    test_cases: list[TestCaseRow] = Field(
        default_factory=list, description="The full updated matrix (existing + new rows)."
    )
    changed_ids: list[str] = Field(default_factory=list, description="Existing rows updated.")
    new_ids: list[str] = Field(default_factory=list, description="Rows added (TC-18…).")
    test_plan_addendum_md: str = Field(default="", description="Test-plan addendum markdown.")
    linked_tdd: str = Field(default="")
    linked_epic: str = Field(default="")
    test_plan_id: str = Field(default="", description="Id of the test plan being amended.")
    change_request_id: str = Field(default="", description="BCR id the addendum serves.")
    matrix_source: str = Field(default="", description="Corpus path of the original matrix.")
    notes: list[str] = Field(default_factory=list)


class StageRecord(WorkflowBaseModel):
    """Bookkeeping for one stage run."""

    status: Literal["pending", "running", "done", "failed"] = "pending"
    error: str = Field(default="")
    seconds: float | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    provider: str = Field(default="")
    model: str = Field(default="")


class ChangeOutputs(_ContentModel):
    """Everything produced after approval for a grounded project."""

    diagrams: list[UpdatedDiagram] = Field(default_factory=list)
    code: CodeChangeBundle = Field(default_factory=CodeChangeBundle)
    tests_doc: TestDocUpdate = Field(default_factory=TestDocUpdate)
    system_flow_md: str = Field(
        default="", description="Assembled system-flow-diagram.md (numbered H2s, D10)."
    )
    provenance: list[str] = Field(
        default_factory=list, description="Knowledge-base sources (`path — lines a-b`) used."
    )
    warnings: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    stages: dict[str, StageRecord] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def stage(self, name: str) -> StageRecord:
        record = self.stages.get(name)
        if record is None:
            record = StageRecord()
            self.stages[name] = record
        return record

    def done_stages(self) -> list[str]:
        return [s for s in STAGES if self.stages.get(s, StageRecord()).status == "done"]


# --------------------------------------------------------------------------- #
# LLM plans (permissive: extra keys ignored, everything defaulted)
# --------------------------------------------------------------------------- #


class DiagramDraft(BaseModel):
    """One diagram as the model returns it."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    kind: str = "state"
    mermaid: str = ""
    notes: str = ""


class DiagramUpdatePlan(BaseModel):
    """The model's answer for ``update_diagrams``."""

    model_config = ConfigDict(extra="ignore")

    diagrams: list[DiagramDraft] = Field(default_factory=list)
    notes: str = ""


class TestCaseDraft(BaseModel):
    """A new test-case row (the engine assigns the id)."""

    model_config = ConfigDict(extra="ignore")
    __test__ = False  # not a pytest class despite the name

    title: str = ""
    preconditions: str = ""
    steps: str = ""
    expected: str = ""
    type: str = "Functional"
    automated: str = "Yes"
    linked: str = ""
    notes: str = ""


class TestCaseUpdate(BaseModel):
    """An update to an existing row: only non-empty fields replace the original."""

    model_config = ConfigDict(extra="ignore")
    __test__ = False  # not a pytest class despite the name

    tc_id: str = ""
    title: str = ""
    preconditions: str = ""
    steps: str = ""
    expected: str = ""
    type: str = ""
    automated: str = ""
    linked: str = ""
    notes: str = ""


class TestPlanAddendumDraft(BaseModel):
    """Structured test-plan addendum; rendered to markdown deterministically."""

    model_config = ConfigDict(extra="ignore")
    __test__ = False  # not a pytest class despite the name

    out_of_scope_removed: list[str] = Field(default_factory=list)
    in_scope_added: list[str] = Field(default_factory=list)
    test_types_added: list[str] = Field(default_factory=list)
    test_data_added: list[str] = Field(default_factory=list)
    deliverables_added: list[str] = Field(default_factory=list)
    exit_criteria_added: list[str] = Field(default_factory=list)
    risks_added: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TestCaseUpdatePlan(BaseModel):
    """The model's answer for ``update_test_cases``."""

    model_config = ConfigDict(extra="ignore")
    __test__ = False  # not a pytest class despite the name

    new_cases: list[TestCaseDraft] = Field(default_factory=list)
    updated_cases: list[TestCaseUpdate] = Field(default_factory=list)
    addendum: TestPlanAddendumDraft = Field(default_factory=TestPlanAddendumDraft)
