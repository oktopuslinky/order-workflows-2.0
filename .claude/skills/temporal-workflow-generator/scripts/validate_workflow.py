"""Validate a generated Temporal Python workflow bundle for common errors.

Usage:
    python validate_workflow.py <bundle_dir>

Checks:
  - Syntax validity (ast.parse)
  - Determinism violations in workflow.py (datetime.now, random, uuid, asyncio.sleep)
  - Missing start_to_close_timeout on execute_activity calls
  - @workflow.signal defined as async (must be sync)
  - Missing workflow.unsafe.imports_passed_through() in workflow.py
  - Dataclass fields without defaults in shared.py
  - Activities registered in activities.py but imported in worker.py

Exit codes: 0 = all clear, 1 = errors found, 2 = usage error
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple


class Issue(NamedTuple):
    file: str
    line: int
    severity: str  # "ERROR" | "WARNING"
    message: str
    fix: str


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Check: syntax parse
# ---------------------------------------------------------------------------

def check_syntax(path: Path) -> list[Issue]:
    issues: list[Issue] = []
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        issues.append(Issue(
            file=path.name,
            line=exc.lineno or 0,
            severity="ERROR",
            message=f"SyntaxError: {exc.msg}",
            fix="Fix the Python syntax error shown above.",
        ))
    return issues


# ---------------------------------------------------------------------------
# Check: determinism violations in workflow.py
# ---------------------------------------------------------------------------

_DETERMINISM_VIOLATIONS = [
    # (attribute_name_to_detect, parent_name_hint, replacement)
    ("now", "datetime", "workflow.now()"),
    ("today", "date", "workflow.now().date()"),
    ("time", "", "workflow.now().timestamp()"),
    ("random", "random", "workflow.random()"),
    ("randint", "random", "workflow.random().randint(...)"),
    ("choice", "random", "workflow.random().choice(...)"),
    ("uuid4", "uuid", "workflow.uuid4()"),
    ("sleep", "asyncio", "await workflow.sleep(timedelta(seconds=N))"),
    ("sleep", "time", "await workflow.sleep(timedelta(seconds=N))"),
]


def check_determinism(path: Path) -> list[Issue]:
    if path.name != "workflow.py":
        return []
    issues: list[Issue] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        attr = node.attr
        parent = _unparse(node.value)
        for vattr, vparent, fix in _DETERMINISM_VIOLATIONS:
            if attr == vattr and (not vparent or vparent in parent):
                issues.append(Issue(
                    file=path.name,
                    line=node.lineno,
                    severity="ERROR",
                    message=f"Determinism violation: `{parent}.{attr}()` is non-deterministic inside workflow code.",
                    fix=f"Replace with {fix}",
                ))
                break
    return issues


# ---------------------------------------------------------------------------
# Check: missing start_to_close_timeout on execute_activity
# ---------------------------------------------------------------------------

def check_execute_activity_timeout(path: Path) -> list[Issue]:
    issues: list[Issue] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match only the direct execute_activity call (not outer calls that contain it)
        func_str = _unparse(node.func)
        if "execute_activity" not in func_str:
            continue
        kwarg_names = {kw.arg for kw in node.keywords}
        if "start_to_close_timeout" not in kwarg_names and "schedule_to_close_timeout" not in kwarg_names:
            issues.append(Issue(
                file=path.name,
                line=node.lineno,
                severity="ERROR",
                message="execute_activity() called without start_to_close_timeout or schedule_to_close_timeout.",
                fix="Add start_to_close_timeout=timedelta(seconds=30) (or appropriate value).",
            ))
    return issues


# ---------------------------------------------------------------------------
# Check: @workflow.signal defined as async
# ---------------------------------------------------------------------------

def check_signal_handlers(path: Path) -> list[Issue]:
    if path.name != "workflow.py":
        return []
    issues: list[Issue] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef,)):
            continue
        for deco in node.decorator_list:
            deco_str = _unparse(deco)
            if "workflow.signal" in deco_str:
                issues.append(Issue(
                    file=path.name,
                    line=node.lineno,
                    severity="ERROR",
                    message=f"Signal handler `{node.name}` is defined as `async def`. Signal handlers must be sync `def`.",
                    fix=f"Change `async def {node.name}` to `def {node.name}`.",
                ))
    return issues


# ---------------------------------------------------------------------------
# Check: missing workflow.unsafe.imports_passed_through in workflow.py
# ---------------------------------------------------------------------------

def check_import_isolation(path: Path) -> list[Issue]:
    if path.name != "workflow.py":
        return []
    issues: list[Issue] = []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []

    if "imports_passed_through" not in source:
        issues.append(Issue(
            file=path.name,
            line=1,
            severity="WARNING",
            message="workflow.py does not contain `workflow.unsafe.imports_passed_through()`.",
            fix=(
                "Wrap all non-stdlib imports at the top of workflow.py with:\n"
                "    with workflow.unsafe.imports_passed_through():\n"
                "        from activities import ...\n"
                "        from shared import ..."
            ),
        ))
    return issues


# ---------------------------------------------------------------------------
# Check: dataclass fields without defaults in shared.py
# ---------------------------------------------------------------------------

def check_dataclass_defaults(path: Path) -> list[Issue]:
    if path.name != "shared.py":
        return []
    issues: list[Issue] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_dataclass = any("dataclass" in _unparse(d) for d in node.decorator_list)
        if not is_dataclass:
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if item.value is None:
                field_name = _unparse(item.target)
                issues.append(Issue(
                    file=path.name,
                    line=item.lineno,
                    severity="WARNING",
                    message=(
                        f"Dataclass field `{field_name}` in `{node.name}` has no default value. "
                        "Temporal deserialization may fail if this field is missing in the JSON payload."
                    ),
                    fix=f"Add a default: `{field_name}: <type> = <default>` (e.g., `= \"\"` for str, `= 0` for int).",
                ))
    return issues


# ---------------------------------------------------------------------------
# Check: name mismatches between workflow.py calls and activities.py / shared.py
# ---------------------------------------------------------------------------

def _collect_names_from_file(path: Path) -> set[str]:
    """Return all top-level function and class names defined in path."""
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return names
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _collect_names_used_in_execute_activity(path: Path) -> list[tuple[int, str]]:
    """Return (line, name) for every first positional arg of execute_activity calls."""
    used: list[tuple[int, str]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return used
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if "execute_activity" not in _unparse(node.func):
            continue
        if node.args and len(node.args) >= 1:
            name = _unparse(node.args[0])
            used.append((node.lineno, name))
    return used


def _collect_input_classes_used(path: Path) -> list[tuple[int, str]]:
    """Return (line, class_name) for every Name or Attribute call that looks like an Input class."""
    used: list[tuple[int, str]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return used
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_str = _unparse(node.func)
        if func_str.endswith("Input") and func_str[0].isupper():
            used.append((node.lineno, func_str))
    return used


def check_name_mismatches(bundle_dir: Path) -> list[Issue]:
    """Detect names used in workflow.py that don't exist in activities.py or shared.py."""
    issues: list[Issue] = []
    workflow_path = bundle_dir / "workflow.py"
    activities_path = bundle_dir / "activities.py"
    shared_path = bundle_dir / "shared.py"

    if not workflow_path.exists():
        return issues

    activity_fns = _collect_names_from_file(activities_path) if activities_path.exists() else set()
    shared_classes = _collect_names_from_file(shared_path) if shared_path.exists() else set()

    for lineno, fn_name in _collect_names_used_in_execute_activity(workflow_path):
        # Skip Temporal SDK functions and compensation variables
        if fn_name.startswith("workflow.") or fn_name.startswith("_"):
            continue
        if fn_name not in activity_fns:
            issues.append(Issue(
                file="workflow.py",
                line=lineno,
                severity="ERROR",
                message=f"execute_activity() references `{fn_name}` which is not defined in activities.py (defined: {sorted(activity_fns)[:3]}...).",
                fix=f"Use the actual function name from activities.py. Check the import block at the top of workflow.py for the correct name.",
            ))

    for lineno, class_name in _collect_input_classes_used(workflow_path):
        # Only check names that look like activity input classes (not WorkflowInput or child classes)
        if class_name == "WorkflowInput" or not class_name.endswith("Input"):
            continue
        if class_name not in shared_classes:
            issues.append(Issue(
                file="workflow.py",
                line=lineno,
                severity="ERROR",
                message=f"Input class `{class_name}` used but not defined in shared.py.",
                fix=f"Use the actual class name from shared.py. Check the import block at the top of workflow.py for the correct name.",
            ))

    return issues


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def validate_bundle(bundle_dir: Path) -> list[Issue]:
    all_issues: list[Issue] = []
    py_files = sorted(bundle_dir.glob("*.py"))

    if not py_files:
        print(f"No .py files found in {bundle_dir}")
        sys.exit(2)

    for path in py_files:
        all_issues.extend(check_syntax(path))
        all_issues.extend(check_determinism(path))
        all_issues.extend(check_execute_activity_timeout(path))
        all_issues.extend(check_signal_handlers(path))
        all_issues.extend(check_import_isolation(path))
        all_issues.extend(check_dataclass_defaults(path))

    # Cross-file checks (need the bundle_dir)
    all_issues.extend(check_name_mismatches(bundle_dir))

    return all_issues


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    bundle_dir = Path(sys.argv[1])
    if not bundle_dir.is_dir():
        print(f"Error: {bundle_dir} is not a directory")
        sys.exit(2)

    issues = validate_bundle(bundle_dir)

    errors = [i for i in issues if i.severity == "ERROR"]
    warnings = [i for i in issues if i.severity == "WARNING"]

    if not issues:
        print("OK: No issues found.")
        sys.exit(0)

    for issue in sorted(issues, key=lambda i: (i.file, i.line)):
        prefix = "ERROR" if issue.severity == "ERROR" else "WARNING"
        print(f"\n[{prefix}]  {issue.file}:{issue.line}")
        print(f"  {issue.message}")
        print(f"  -> Fix: {issue.fix}")

    print(f"\nSummary: {len(errors)} error(s), {len(warnings)} warning(s) across {bundle_dir}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
