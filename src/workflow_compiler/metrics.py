"""Time-saved metric: measured pipeline seconds vs. estimated human-team hours.

Pure, deterministic functions of a project's persisted ``stage_timings`` and the
configured ``baseline_hours`` — no LLM, no I/O. The baselines are **estimates**
(documented and tunable in :mod:`workflow_compiler.config`); every consumer must
present them as such. Steps that never ran are not counted — a legacy project
with no recorded timings yields ``None``, never a fabricated saving.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from workflow_compiler.models import CompilationProject

#: stage_timings key prefix → baseline category (fallback: "discovery").
_CATEGORY_PREFIXES: list[tuple[str, str]] = [
    ("extract:", "spec"),
    ("validate:", "validate"),
    ("compile:", "compile"),
    ("edit", "edit"),  # matches both "edit:<slug>" and "edit:add:<slug>"
]

_CATEGORY_LABELS: dict[str, str] = {
    "discovery": "Document analysis & workflow discovery",
    "spec": "Fact extraction & spec drafting",
    "validate": "Spec validation & review",
    "compile": "Design & Temporal implementation",
    "edit": "Edit-request turnaround",
}


class TimeSavedRow(BaseModel):
    """One measured pipeline step compared against its human-team estimate."""

    step: str = Field(..., description="stage_timings key, e.g. 'compile:order-workflow'.")
    category: str = Field(..., description="Baseline category the step maps to.")
    label: str = Field(..., description="Human-readable category label.")
    human_baseline_hours: float = Field(..., description="Estimated human-team hours.")
    actual_seconds: float = Field(..., description="Measured wall-clock seconds.")
    saved_hours: float = Field(..., description="baseline minus actual (in hours).")


class TimeSavedReport(BaseModel):
    """Per-project time-saved breakdown. Baselines are estimates, not measurements."""

    rows: list[TimeSavedRow] = Field(default_factory=list)
    total_baseline_hours: float = Field(default=0.0)
    total_actual_seconds: float = Field(default=0.0)
    total_saved_hours: float = Field(default=0.0)


def _category(step: str) -> str:
    for prefix, category in _CATEGORY_PREFIXES:
        if step.startswith(prefix):
            return category
    return "discovery"


def compute_time_saved(
    project: CompilationProject, baseline_hours: dict[str, float]
) -> TimeSavedReport | None:
    """Compare the project's measured step durations against the baselines.

    Returns ``None`` when nothing was measured (legacy/pre-metric projects) —
    no savings are ever claimed for unmeasured runs.
    """
    if not project.stage_timings:
        return None
    rows: list[TimeSavedRow] = []
    for step in sorted(project.stage_timings):
        seconds = project.stage_timings[step]
        category = _category(step)
        baseline = baseline_hours.get(category, 0.0)
        rows.append(
            TimeSavedRow(
                step=step,
                category=category,
                label=_CATEGORY_LABELS.get(category, category),
                human_baseline_hours=baseline,
                actual_seconds=seconds,
                saved_hours=baseline - seconds / 3600.0,
            )
        )
    return TimeSavedReport(
        rows=rows,
        total_baseline_hours=sum(row.human_baseline_hours for row in rows),
        total_actual_seconds=sum(row.actual_seconds for row in rows),
        total_saved_hours=sum(row.saved_hours for row in rows),
    )
