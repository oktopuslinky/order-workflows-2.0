"""Zip an example knowledge-base corpus for upload through the UI/API.

    python scripts/make_kb_zip.py                       # examples/knowledge_bases/order-lifecycle
    python scripts/make_kb_zip.py path/to/folder out.zip

The archive keeps the folder name as its single top-level entry (which the
uploader strips), exactly like a right-click "Compress" of the folder — so the
demo zip and a hand-made one produce identical node ids. PowerShell equivalent:
``Compress-Archive -Path examples/knowledge_bases/order-lifecycle -DestinationPath order-lifecycle.zip``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from workflow_compiler.kg.ingest import zip_folder  # noqa: E402

DEFAULT_SOURCE = ROOT / "examples" / "knowledge_bases" / "order-lifecycle"


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else DEFAULT_SOURCE
    target = Path(argv[2]) if len(argv) > 2 else source.parent / f"{source.name}.zip"
    if not source.is_dir():
        print(f"not a directory: {source}", file=sys.stderr)
        return 2
    data = zip_folder(source)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data):,} bytes) from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
