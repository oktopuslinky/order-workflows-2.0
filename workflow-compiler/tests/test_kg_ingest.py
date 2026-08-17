"""Zip extraction safety + folder ingress for knowledge bases."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from workflow_compiler.kg.ingest import CorpusIngestError, copy_tree, extract_zip, zip_folder

FIXTURE = Path(__file__).parent / "fixtures" / "kb_mini"


def _zip(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink is not None:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)  # S_IFLNK | 0777
            info.create_system = 3
            zf.writestr(info, "../../etc/passwd")
    return buf.getvalue()


def test_extract_strips_single_top_level_folder(tmp_path: Path) -> None:
    data = _zip({"Existing_KG/README.md": b"# hi", "Existing_KG/src/a.py": b"x = 1"})
    result = extract_zip(data, tmp_path / "corpus")
    assert result.stripped_root == "Existing_KG"
    assert result.files == 2
    assert (tmp_path / "corpus" / "README.md").read_bytes() == b"# hi"
    assert (tmp_path / "corpus" / "src" / "a.py").is_file()


def test_extract_keeps_layout_without_common_root(tmp_path: Path) -> None:
    data = _zip({"docs/a.md": b"a", "src/b.py": b"b"})
    result = extract_zip(data, tmp_path / "corpus")
    assert result.stripped_root is None
    assert (tmp_path / "corpus" / "docs" / "a.md").is_file()
    assert (tmp_path / "corpus" / "src" / "b.py").is_file()


def test_extract_skips_os_litter_and_directories(tmp_path: Path) -> None:
    data = _zip(
        {"root/": b"", "root/__MACOSX/x": b"junk", "root/.DS_Store": b"j", "root/a.md": b"a"}
    )
    result = extract_zip(data, tmp_path / "corpus")
    assert result.files == 1
    assert sorted(p.name for p in (tmp_path / "corpus").rglob("*") if p.is_file()) == ["a.md"]


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "root/../../evil.txt", "/abs/evil.txt", "C:/Windows/evil.txt", "..\\evil.txt"],
)
def test_extract_rejects_traversal(tmp_path: Path, name: str) -> None:
    data = _zip({"root/ok.md": b"ok", name: b"evil"})
    with pytest.raises(CorpusIngestError):
        extract_zip(data, tmp_path / "corpus")
    # nothing left behind
    assert not (tmp_path / "corpus").exists()


def test_extract_rejects_symlinks(tmp_path: Path) -> None:
    data = _zip({"root/ok.md": b"ok"}, symlink="root/link")
    with pytest.raises(CorpusIngestError, match="symlink"):
        extract_zip(data, tmp_path / "corpus")


def test_extract_enforces_size_and_count_caps(tmp_path: Path) -> None:
    big = _zip({"root/big.bin": b"0" * 2048})
    with pytest.raises(CorpusIngestError, match="MB"):
        extract_zip(big, tmp_path / "c1", max_bytes=1024)
    many = _zip({f"root/f{i}.txt": b"x" for i in range(5)})
    with pytest.raises(CorpusIngestError, match="more than"):
        extract_zip(many, tmp_path / "c2", max_files=3)


def test_extract_rejects_non_zip_and_empty(tmp_path: Path) -> None:
    with pytest.raises(CorpusIngestError, match="not a valid zip"):
        extract_zip(b"not a zip", tmp_path / "c")
    with pytest.raises(CorpusIngestError, match="no files"):
        extract_zip(_zip({"root/": b""}), tmp_path / "c")


def test_copy_tree_and_zip_folder_round_trip(tmp_path: Path) -> None:
    copied = copy_tree(FIXTURE, tmp_path / "corpus")
    assert copied.files == 7
    assert (tmp_path / "corpus" / "src" / "orders" / "workflow.py").is_file()

    data = zip_folder(FIXTURE)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
    assert all(n.startswith("kb_mini/") for n in names)
    result = extract_zip(data, tmp_path / "from_zip")
    assert result.stripped_root == "kb_mini"
    assert result.files == 7
