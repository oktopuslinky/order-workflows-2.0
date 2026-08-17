"""Path constants for the vendored Context Hub subset.

Upstream these pointed at the KG-Context repository root (``examples/`` and a
repo-level ``graph.json``). Inside workflow-compiler there is no such repo, so
they resolve to a package-local, non-existent ``examples/`` (only ever used as
*defaults* by :mod:`bootstrap.build`) and to a cwd-relative default graph path.
Callers in workflow-compiler always pass explicit paths.
"""

from pathlib import Path

# The vendored package directory (kept for the same-name upstream constant).
REPO_ROOT = Path(__file__).resolve().parent

# Curated example datasets are NOT vendored; these only serve as defaults.
EXAMPLES_DIR = REPO_ROOT / "examples"
TELECOM_EXAMPLE = EXAMPLES_DIR / "telecom"
TELECOM_DOMAINS = TELECOM_EXAMPLE / "domains"
TELECOM_JOURNEYS = TELECOM_EXAMPLE / "journeys"
TELECOM_SHARED = TELECOM_EXAMPLE / "shared"

# Default runtime artifact (always overridden by an explicit ``out_dir``).
DEFAULT_GRAPH_PATH = Path(".contexthub") / "graph.json"
