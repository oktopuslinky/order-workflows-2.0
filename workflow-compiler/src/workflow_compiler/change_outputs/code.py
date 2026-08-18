"""Deterministic half of the code stage: which files, in what order, and the checks.

Nothing here calls a model. Given the change spec and the knowledge base's
Python files it decides the *rewrite set* (files a component resolves to, plus
every file that imports a rewritten module — worker / starter / tests follow the
modules they register), orders it so later files see earlier outputs (types →
activities → workflow → worker/starter → tests, refined by the import graph),
extracts the model's fenced answer, checks it with ``ast.parse`` (and ruff when
available), and produces the unified diff.
"""

from __future__ import annotations

import ast
import difflib
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from workflow_compiler.models.change_spec import ChangeSpec, ComponentChange, ComponentKind

_NODE_PREFIX = re.compile(r"^(?:mod|fn|cls|doc|chk|svc):", re.IGNORECASE)
_FENCE_OPEN = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n")
_PY_START = re.compile(r"^\s*(?:\"\"\"|'''|#|from\s+\S+\s+import|import\s+\S+|@|def\s|class\s)")

#: Category rank used as the tie-break of the topological order (plan order).
_CATEGORY_RANK: tuple[tuple[str, int], ...] = (
    ("test", 5),
    ("starter", 4),
    ("worker", 3),
    ("workflow", 2),
    ("activit", 1),
    ("type", 0),
    ("shared", 0),
    ("model", 0),
    ("contract", 0),
)


def category_rank(path: str) -> int:
    """Plan order rank of a corpus path (types 0 … tests 5, unknown 6)."""
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name.startswith("test_") or "/tests/" in f"/{lowered}" or name.endswith("_test.py"):
        return 5
    for needle, rank in _CATEGORY_RANK:
        if needle == "test":
            continue
        if needle in lowered:
            return rank
    return 6


def _file_part(ref: str) -> str:
    """The file path inside a component ref (node id / path / ``fn:<file>:<symbol>``)."""
    text = ref.strip().strip("`").replace("\\", "/")
    text = _NODE_PREFIX.sub("", text)
    if ".py:" in text:
        text = text.split(".py:", 1)[0] + ".py"
    return text.strip("/")


def resolve_component_file(component: ComponentChange, py_files: Sequence[str]) -> str | None:
    """The corpus Python file ``component`` lives in, or ``None``.

    Matches the ``path`` (node id / corpus path / suffix, case-insensitively —
    the live spec once carried ``existing_CodeBase``), then the ``name`` when it
    is itself a path. Test-case ids (``TC-06``) and business ids resolve to
    nothing on purpose.
    """
    lowered = {p.lower(): p for p in py_files}
    for ref in (component.path, component.name):
        candidate = _file_part(ref).lower()
        if not candidate.endswith(".py"):
            continue
        if candidate in lowered:
            return lowered[candidate]
        suffix = "/" + candidate.lstrip("/")
        hits = [p for low, p in lowered.items() if low.endswith(suffix)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return sorted(hits, key=len)[0]
    return None


def fallback_file_for_kind(kind: ComponentKind, py_files: Sequence[str]) -> str | None:
    """Where a *new* activity / signal / query most plausibly lands.

    A component with an empty path (it does not exist yet) still has to be
    written somewhere; the corpus's activities module and workflow module are
    the deterministic homes for activities and for signals / queries.
    """
    needles = {
        ComponentKind.ACTIVITY: ("activit",),
        ComponentKind.SIGNAL: ("workflow",),
        ComponentKind.QUERY: ("workflow",),
        ComponentKind.WORKFLOW: ("workflow",),
        ComponentKind.TYPE: ("types", "shared", "model"),
    }.get(kind)
    if not needles:
        return None
    candidates = [
        p
        for p in py_files
        if any(n in p.lower() for n in needles)
        and category_rank(p) != 5
        and not p.endswith("__init__.py")
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: (category_rank(p), len(p)))[0]


def _dotted_tails(path: str) -> set[str]:
    """Dotted module names a corpus file answers to (with and without its top dir)."""
    stem = path[:-3] if path.endswith(".py") else path
    parts = stem.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    tails: set[str] = set()
    for start in range(len(parts)):
        tails.add(".".join(parts[start:]))
    return {t for t in tails if t}


def imports_of(text: str) -> list[str]:
    """Dotted module names a Python source imports (``import a.b`` / ``from a.b import c``)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        found: list[str] = []
        for match in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text, re.M):
            found.append(match.group(1) or match.group(2))
        return found
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            # ``from src.shared import types`` imports a module too.
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def resolve_import(module: str, py_files: Sequence[str]) -> str | None:
    """The corpus file an imported dotted name refers to, if any.

    ``src.shared.types`` matches ``existing_Codebase/shared/types.py`` because
    the corpus imports itself under a different top-level name than it is
    checked out as: the first segment of the import is dropped when nothing
    matches it whole.
    """
    tails_by_file = {p: _dotted_tails(p) for p in py_files}
    candidates = [module]
    if "." in module:
        candidates.append(module.split(".", 1)[1])
    for candidate in candidates:
        for path, tails in tails_by_file.items():
            if candidate in tails and not path.endswith("__init__.py"):
                return path
    return None


def import_root_of(texts: Mapping[str, str], py_files: Sequence[str]) -> str:
    """The package name the corpus imports itself as (``src``), or ``""``."""
    counts: dict[str, int] = {}
    for text in texts.values():
        for module in imports_of(text):
            if "." not in module:
                continue
            head, rest = module.split(".", 1)
            if resolve_import(rest, py_files) is not None:
                counts[head] = counts.get(head, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


@dataclass
class RewritePlan:
    """The deterministic decision of what to rewrite and in what order."""

    order: list[str] = field(default_factory=list)  # files to rewrite, in order
    unchanged: list[str] = field(default_factory=list)
    reasons: dict[str, list[str]] = field(default_factory=dict)
    components_by_file: dict[str, list[ComponentChange]] = field(default_factory=dict)
    imports: dict[str, list[str]] = field(default_factory=dict)  # file → corpus files it imports
    import_root: str = ""
    code_root: str = ""


def plan_rewrites(
    spec: ChangeSpec | None,
    texts: Mapping[str, str],
) -> RewritePlan:
    """Decide the rewrite set and order (see the module docstring)."""
    py_files = sorted(p for p in texts if p.endswith(".py"))
    plan = RewritePlan()
    plan.import_root = import_root_of(texts, py_files)
    roots = sorted({p.split("/", 1)[0] for p in py_files if "/" in p and category_rank(p) != 5})
    plan.code_root = roots[0] if len(roots) == 1 else ""

    # 1. Files named by the change spec (directly, or as the home of a new symbol).
    named: dict[str, list[str]] = {}
    for component in spec.components if spec is not None else []:
        if component.kind in (ComponentKind.DIAGRAM, ComponentKind.DOC):
            continue
        target = resolve_component_file(component, py_files)
        if target is None and not component.path.strip():
            target = fallback_file_for_kind(component.kind, py_files)
        if target is None:
            continue
        named.setdefault(target, []).append(
            f"{component.kind.value} {component.name} ({component.change_type.value})"
        )
        plan.components_by_file.setdefault(target, []).append(component)

    # 2. Import graph over the corpus.
    for path in py_files:
        deps: list[str] = []
        for module in imports_of(texts[path]):
            resolved = resolve_import(module, py_files)
            if resolved and resolved != path and resolved not in deps:
                deps.append(resolved)
        plan.imports[path] = deps

    # 3. Dependents (transitively) of a rewritten file are rewritten too.
    selected: dict[str, list[str]] = {p: list(r) for p, r in named.items()}
    changed = True
    while changed:
        changed = False
        for path in py_files:
            if path in selected or path.endswith("__init__.py"):
                continue
            hits = [d for d in plan.imports[path] if d in selected]
            if hits:
                selected[path] = [f"imports {', '.join(hits)}"]
                changed = True

    # 4. Order: topological over the import graph, ties by plan category then path.
    remaining = set(selected)
    order: list[str] = []
    while remaining:
        ready = sorted(
            (p for p in remaining if not any(d in remaining for d in plan.imports[p])),
            key=lambda p: (category_rank(p), p),
        )
        if not ready:  # an import cycle: fall back to category order for the rest
            ready = sorted(remaining, key=lambda p: (category_rank(p), p))
        nxt = ready[0]
        order.append(nxt)
        remaining.remove(nxt)
    plan.order = order
    plan.reasons = {p: selected[p] for p in order}
    plan.unchanged = [p for p in texts if p not in selected]
    return plan


# --------------------------------------------------------------------------- #
# Model answer handling
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FencedCode:
    """The code extracted from a model answer."""

    code: str
    closed: bool  # a closing fence was found
    found: bool  # any code was found at all


def extract_code(answer: str) -> FencedCode:
    """Pull the (single) fenced code block out of ``answer``.

    Prefers a ``python`` fence, then the first fence, and — when the model
    forgot the fences but clearly answered with Python — the whole answer. An
    opening fence without a closing one is returned with ``closed=False`` so the
    caller can ask the model to continue.
    """
    text = answer.replace("\r\n", "\n")
    opens = list(_FENCE_OPEN.finditer(text))
    if opens:
        chosen = next((m for m in opens if m.group(1).lower() in ("python", "py")), opens[0])
        start = chosen.end()
        close = text.find("\n```", start)
        if close == -1:
            return FencedCode(text[start:].rstrip("\n") + "\n", closed=False, found=True)
        return FencedCode(text[start:close].rstrip("\n") + "\n", closed=True, found=True)
    stripped = text.strip()
    if stripped and _PY_START.match(stripped):
        return FencedCode(stripped + "\n", closed=True, found=True)
    return FencedCode("", closed=False, found=False)


def continue_code(previous: str, continuation_answer: str) -> FencedCode:
    """Append the model's continuation (a fenced or bare tail) to ``previous``.

    Overlap the model repeats (it usually restarts at the last full line) is
    trimmed by matching the continuation's first non-empty line against the
    tail of ``previous``.
    """
    tail = extract_code(continuation_answer)
    if not tail.found:
        return FencedCode(previous, closed=False, found=True)
    cont = tail.code
    prev_lines = previous.rstrip("\n").split("\n")
    cont_lines = cont.rstrip("\n").split("\n")
    first = next((line for line in cont_lines if line.strip()), "")
    if first:
        for back in range(min(len(prev_lines), 40), 0, -1):
            if prev_lines[-back] == first:
                # ``first`` (and what follows it) already exists at ``-back``:
                # keep the continuation's version of the tail.
                prev_lines = prev_lines[:-back]
                break
    merged = "\n".join(prev_lines + cont_lines).rstrip("\n") + "\n"
    return FencedCode(merged, closed=tail.closed, found=True)


def check_syntax(code: str) -> tuple[bool, str]:
    """``ast.parse`` as a pass/fail with the error message."""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return False, f"{exc.msg} (line {exc.lineno})"
    except (ValueError, RecursionError) as exc:  # NUL bytes, absurd nesting
        return False, str(exc)
    return True, ""


def ruff_check(code: str, *, timeout: float = 30.0) -> tuple[bool | None, str]:
    """Run ruff's pyflakes-class rules over ``code``; ``None`` when ruff is unavailable."""
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "ruff", "check", "--quiet", "--no-cache",
                "--select", "F,E9", "--ignore", "F401,F841", "--stdin-filename", "changed.py", "-",
            ],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    if proc.returncode == 0:
        return True, ""
    if proc.returncode == 1:
        return False, (proc.stdout or proc.stderr).strip()
    return None, (proc.stderr or proc.stdout).strip()


def unified_diff(path: str, original: str, updated: str) -> str:
    """Unified diff between the two texts, in ``a/<path>`` / ``b/<path>`` form."""
    if original == updated:
        return ""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


# --------------------------------------------------------------------------- #
# Signature summaries (what sibling files see of an earlier output)
# --------------------------------------------------------------------------- #


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return ""


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    return "".join(f"@{_unparse(d)} " for d in node.decorator_list)


def _function_line(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str = "") -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = _unparse(node.args)
    ret = f" -> {_unparse(node.returns)}" if node.returns is not None else ""
    return f"{indent}{_decorators(node)}{prefix} {node.name}({args}){ret}"


def signature_summary(text: str, *, max_lines: int = 120) -> str:
    """A compact outline of a Python file: classes with fields / members, functions.

    Falls back to the file's first lines when it does not parse.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "\n".join(text.splitlines()[:max_lines])
    lines: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = ", ".join(_unparse(t) for t in node.targets)
            value = _unparse(node.value)
            lines.append(f"{targets} = {value[:80]}")
        elif isinstance(node, ast.AnnAssign):
            lines.append(f"{_unparse(node.target)}: {_unparse(node.annotation)}")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            lines.append(_function_line(node))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(_unparse(b) for b in node.bases)
            lines.append(f"{_decorators(node)}class {node.name}({bases}):")
            for item in node.body:
                if isinstance(item, ast.AnnAssign):
                    lines.append(f"    {_unparse(item.target)}: {_unparse(item.annotation)}")
                elif isinstance(item, ast.Assign):
                    lines.append(
                        f"    {', '.join(_unparse(t) for t in item.targets)} = "
                        f"{_unparse(item.value)[:60]}"
                    )
                elif isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    lines.append(_function_line(item, "    "))
        if len(lines) >= max_lines:
            lines.append("…")
            break
    return "\n".join(lines)


def defined_names(text: str) -> list[str]:
    """Top-level function / class / constant names of a Python file."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(_unparse(t) for t in node.targets)
    return names


def missing_symbols(code: str, required: Iterable[str]) -> list[str]:
    """Which of ``required`` identifiers do not appear in ``code`` (word match)."""
    return [
        name for name in required
        if name and not re.search(rf"\b{re.escape(name)}\b", code)
    ]


# --------------------------------------------------------------------------- #
# Deterministic import repair for well-known names the model forgot to import
# --------------------------------------------------------------------------- #

#: Names whose import statement is unambiguous in a Temporal Python code base.
KNOWN_IMPORTS: dict[str, str] = {
    "timedelta": "from datetime import timedelta",
    "datetime": "from datetime import datetime",
    "timezone": "from datetime import timezone",
    "asyncio": "import asyncio",
    "uuid": "import uuid",
    "logging": "import logging",
    "Optional": "from typing import Optional",
    "List": "from typing import List",
    "Dict": "from typing import Dict",
    "Any": "from typing import Any",
    "Sequence": "from typing import Sequence",
    "dataclass": "from dataclasses import dataclass",
    "field": "from dataclasses import field",
    "Enum": "from enum import Enum",
    "RetryPolicy": "from temporalio.common import RetryPolicy",
    "ActivityError": "from temporalio.exceptions import ActivityError",
    "ApplicationError": "from temporalio.exceptions import ApplicationError",
    "activity": "from temporalio import activity",
    "workflow": "from temporalio import workflow",
    "pytest": "import pytest",
}
_UNDEFINED = re.compile(r"Undefined name `([A-Za-z_][A-Za-z0-9_]*)`")


def undefined_names(ruff_output: str) -> list[str]:
    """The distinct names ruff's F821 findings mention, in order."""
    seen: list[str] = []
    for match in _UNDEFINED.finditer(ruff_output):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def auto_import(code: str, names: Iterable[str]) -> tuple[str, list[str]]:
    """Insert the well-known import for each of ``names`` (deterministic, no model).

    Only names in :data:`KNOWN_IMPORTS` are handled; the statement goes after
    the last top-level import (or the module docstring / ``from __future__``
    line). Returns the new code and the statements added.
    """
    added: list[str] = []
    lines = code.split("\n")
    for name in names:
        statement = KNOWN_IMPORTS.get(name)
        if statement is None or statement in code:
            continue
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and not line.startswith((" ", "\t")):
                insert_at = i + 1
        if insert_at == 0:
            # after a module docstring, if any
            try:
                tree = ast.parse(code)
            except SyntaxError:
                tree = None
            if tree is not None and tree.body and isinstance(tree.body[0], ast.Expr):
                end = getattr(tree.body[0], "end_lineno", None)
                if isinstance(end, int):
                    insert_at = end
        lines.insert(insert_at, statement)
        added.append(statement)
        code = "\n".join(lines)
    return code, added


# --------------------------------------------------------------------------- #
# Cross-file coherence: names imported from a rewritten sibling must exist there
# --------------------------------------------------------------------------- #


def exported_names(text: str) -> set[str]:
    """Top-level names a module offers: its definitions plus what it imports."""
    names = set(defined_names(text))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def missing_imports(
    code: str, siblings: Mapping[str, str], py_files: Sequence[str]
) -> dict[str, list[str]]:
    """``{sibling path: [names]}`` this file imports from a rewritten sibling that
    the sibling's new text does not define — the model coding against a
    signature it invented instead of the one given."""
    problems: dict[str, list[str]] = {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return problems
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module or node.level:
            continue
        target = resolve_import(node.module, py_files)
        if target is None or target not in siblings:
            continue
        available = exported_names(siblings[target])
        missing = [
            alias.name for alias in node.names
            if alias.name != "*" and alias.name not in available
        ]
        if missing:
            problems.setdefault(target, []).extend(missing)
    return problems
