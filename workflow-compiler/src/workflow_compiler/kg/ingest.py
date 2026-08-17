"""Corpus ingress: safe zip extraction and folder copy into ``<kb>/corpus/``.

Uploads are untrusted. :func:`extract_zip` therefore refuses anything that could
write outside the destination (absolute names, drive letters, ``..`` segments,
symlink entries), caps the total uncompressed size and the file count, and
strips one common top-level folder so ``Existing_KG/Business_Docs/…`` lands as
``corpus/Business_Docs/…`` — which is what makes node ids read like
``mod:existing_Codebase/workflows/order_workflow.py``.
"""

from __future__ import annotations

import io
import posixpath
import shutil
import stat
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from workflow_compiler.exceptions import CompilationError

#: Directory entries and OS litter that never belong in a corpus.
_SKIP_NAMES = frozenset({"__MACOSX", ".DS_Store", "Thumbs.db", ".git", "__pycache__"})


class CorpusIngestError(CompilationError):
    """The uploaded archive/folder cannot be used as a corpus (400 at the API)."""


@dataclass
class ExtractResult:
    files: int = 0
    bytes: int = 0
    stripped_root: str | None = None
    skipped: list[str] = field(default_factory=list)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _safe_relative(name: str) -> PurePosixPath | None:
    """Return the entry as a safe relative POSIX path, or ``None`` to skip/reject."""
    normalised = name.replace("\\", "/")
    if not normalised or normalised.endswith("/"):
        return None
    if normalised.startswith("/") or ":" in normalised.split("/", 1)[0]:
        raise CorpusIngestError(f"Archive entry {name!r} has an absolute path.")
    parts = [p for p in posixpath.normpath(normalised).split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise CorpusIngestError(f"Archive entry {name!r} escapes the archive root.")
    if any(p in _SKIP_NAMES for p in parts):
        return None
    return PurePosixPath(*parts)


def extract_zip(
    data: bytes,
    dest: Path,
    *,
    max_bytes: int = 50 * 1024 * 1024,
    max_files: int = 5000,
) -> ExtractResult:
    """Extract ``data`` (a zip archive) into ``dest`` safely.

    Raises :class:`CorpusIngestError` for a non-zip payload, path-traversal
    entries, symlinks, or an archive over the caps. ``dest`` is created; on
    error whatever was written is removed again.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise CorpusIngestError("The upload is not a valid zip archive.") from exc

    entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total = 0
    with archive:
        for info in archive.infolist():
            if _is_symlink(info):
                raise CorpusIngestError(f"Archive entry {info.filename!r} is a symlink.")
            rel = _safe_relative(info.filename)
            if rel is None:
                continue
            total += info.file_size
            if total > max_bytes:
                raise CorpusIngestError(
                    f"Archive exceeds the {max_bytes // (1024 * 1024)} MB uncompressed limit."
                )
            entries.append((info, rel))
            if len(entries) > max_files:
                raise CorpusIngestError(f"Archive has more than {max_files} files.")
        if not entries:
            raise CorpusIngestError("The archive contains no files.")

        stripped = _common_root(rel for _, rel in entries)
        dest.mkdir(parents=True, exist_ok=True)
        result = ExtractResult(stripped_root=stripped)
        try:
            for info, rel in entries:
                target_rel = PurePosixPath(*rel.parts[1:]) if stripped else rel
                target = (dest / Path(*target_rel.parts)).resolve()
                if dest.resolve() not in target.parents:
                    raise CorpusIngestError(f"Archive entry {info.filename!r} escapes the root.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                result.files += 1
                result.bytes += info.file_size
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
    return result


def _common_root(paths: Iterable[PurePosixPath]) -> str | None:
    """The single top-level folder shared by every entry, if there is one."""
    roots: set[str] = set()
    for rel in paths:
        if len(rel.parts) < 2:
            return None
        roots.add(rel.parts[0])
        if len(roots) > 1:
            return None
    return next(iter(roots)) if roots else None


def copy_tree(src: Path, dest: Path, *, max_bytes: int = 50 * 1024 * 1024) -> ExtractResult:
    """Copy a local folder into ``dest`` (CLI ingress), skipping VCS/OS litter."""
    src = Path(src).resolve()
    if not src.is_dir():
        raise CorpusIngestError(f"{src} is not a directory.")
    result = ExtractResult()
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(src)
        if any(part in _SKIP_NAMES for part in rel.parts):
            continue
        size = path.stat().st_size
        result.bytes += size
        if result.bytes > max_bytes:
            shutil.rmtree(dest, ignore_errors=True)
            raise CorpusIngestError(
                f"Folder exceeds the {max_bytes // (1024 * 1024)} MB limit."
            )
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        result.files += 1
    if result.files == 0:
        raise CorpusIngestError(f"{src} contains no files.")
    return result


def zip_folder(src: Path) -> bytes:
    """Zip a folder in memory with the folder name as the single top-level entry.

    Used by the CLI/tests to feed a folder through the same path as an upload.
    """
    src = Path(src).resolve()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            rel = path.relative_to(src)
            if path.is_file() and not any(p in _SKIP_NAMES for p in rel.parts):
                zf.write(path, (PurePosixPath(src.name) / rel.as_posix()).as_posix())
    return buf.getvalue()
