from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SAFE_PATHS_PATH = REPO_ROOT / ".aiwf" / "bin" / "safe_paths.py"


def _load_safe_paths():
    spec = importlib.util.spec_from_file_location("safe_paths_under_test", SAFE_PATHS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str = "content\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _symlink_or_skip(link: Path, target: Path | str, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


def test_reject_symlink_rejects_symlink_file(tmp_path: Path):
    safe_paths = _load_safe_paths()
    target = tmp_path / "target.txt"
    _write(target)
    link = tmp_path / "link.txt"
    _symlink_or_skip(link, target)

    with pytest.raises(safe_paths.SafePathError):
        safe_paths.reject_symlink(link)


def test_reject_tree_symlinks_rejects_symlink_directory(tmp_path: Path):
    safe_paths = _load_safe_paths()
    root = tmp_path / "root"
    private = tmp_path / "private"
    root.mkdir()
    _write(private / "secret.txt", "secret\n")
    _symlink_or_skip(root / "linked_dir", private, target_is_directory=True)

    with pytest.raises(safe_paths.SafePathError):
        safe_paths.reject_tree_symlinks(root)


def test_safe_repo_relative_path_rejects_parent_traversal():
    safe_paths = _load_safe_paths()

    with pytest.raises(safe_paths.SafePathError):
        safe_paths.safe_repo_relative_path("../secret.txt")


def test_safe_resolve_under_rejects_resolved_path_outside_root(tmp_path: Path):
    safe_paths = _load_safe_paths()
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    _write(outside / "secret.txt", "secret\n")
    _symlink_or_skip(root / "linked_secret.txt", outside / "secret.txt")

    with pytest.raises(safe_paths.SafePathError):
        safe_paths.safe_resolve_under(root / "linked_secret.txt", root)


def test_safe_output_path_rejects_protected_evidence_path(tmp_path: Path):
    safe_paths = _load_safe_paths()
    repo = tmp_path / "repo"
    records = repo / ".aiwf" / "records"
    records.mkdir(parents=True)

    with pytest.raises(safe_paths.SafePathError):
        safe_paths.safe_output_path(".aiwf/records/out.zip", repo, [records])


def test_safe_copy_tree_no_symlink_copies_normal_tree(tmp_path: Path):
    safe_paths = _load_safe_paths()
    allowed = tmp_path / "allowed"
    source = allowed / "source"
    dest = tmp_path / "dest"
    _write(source / "nested" / "file.txt", "public\n")

    safe_paths.safe_copy_tree_no_symlink(source, dest, allowed)

    assert (dest / "nested" / "file.txt").read_text(encoding="utf-8") == "public\n"
