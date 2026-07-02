"""Shared fail-closed filesystem helpers for AIWF tooling."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Sequence


class SafePathError(ValueError):
    """Raised when a path violates an AIWF filesystem safety boundary."""


def lexical_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _display_path(path: Path, root: Path | None = None) -> str:
    if root is None:
        return path.as_posix()
    return lexical_relative(path, root)


def safe_repo_relative_path(path: str | Path) -> str:
    raw = str(path).strip().replace("\\", "/").strip("/")
    if not raw:
        raise SafePathError("empty path is not allowed")
    parsed = Path(str(path))
    if parsed.is_absolute():
        raise SafePathError(f"path must be repository-relative: {path}")
    if any(part == ".." for part in Path(raw).parts):
        raise SafePathError(f"path must not contain '..': {path}")
    return raw


def find_symlink_component(path: Path, root: Path) -> Path | None:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return path if path.is_symlink() else None
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def reject_symlink(path: Path, *, root: Path | None = None) -> None:
    if path.is_symlink():
        raise SafePathError(f"refusing symlink path: {_display_path(path, root)}")


def reject_symlink_components(path: Path, root: Path) -> None:
    symlink = find_symlink_component(path, root)
    if symlink is not None:
        raise SafePathError(f"refusing symlink path component: {lexical_relative(symlink, root)}")


def find_tree_symlink(root: Path) -> Path | None:
    if root.is_symlink():
        return root
    if not root.is_dir():
        return None
    for current_root, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        if current.is_symlink():
            return current
        for name in sorted([*dirs, *files]):
            child = current / name
            if child.is_symlink():
                return child
        dirs[:] = sorted(dirs)
    return None


def reject_tree_symlinks(root: Path, *, display_root: Path | None = None) -> None:
    symlink = find_tree_symlink(root)
    if symlink is not None:
        raise SafePathError(f"tree must not contain symlinks: {_display_path(symlink, display_root)}")


def _resolved_candidate_for_existing_or_parent(path: Path) -> Path:
    if path.exists():
        return path.resolve(strict=True)
    missing_parts: list[str] = []
    current = path
    while not current.exists():
        missing_parts.append(current.name)
        parent = current.parent
        if parent == current:
            raise SafePathError(f"no existing parent for path: {path}")
        current = parent
    resolved = current.resolve(strict=True)
    for part in reversed(missing_parts):
        resolved = resolved / part
    return resolved


def ensure_under_root(path: Path, root: Path) -> Path:
    root_resolved = root.resolve(strict=True)
    candidate = _resolved_candidate_for_existing_or_parent(path)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise SafePathError(f"path escapes allowed root: {path}") from exc
    return candidate


def safe_resolve_under(path: Path, root: Path) -> Path:
    reject_symlink_components(path, root)
    resolved = path.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise SafePathError(f"path escapes allowed root: {path}") from exc
    return resolved


def safe_walk_files(root: Path, *, allowed_root: Path | None = None) -> Iterable[Path]:
    allowed = allowed_root or root
    reject_symlink(root, root=allowed)
    if root.is_file():
        safe_resolve_under(root, allowed)
        yield root
        return
    if not root.is_dir():
        raise SafePathError(f"path is not a regular file or directory: {_display_path(root, allowed)}")

    for current_root, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        reject_symlink(current, root=allowed)
        for dirname in sorted(dirs):
            child = current / dirname
            reject_symlink(child, root=allowed)
        dirs[:] = sorted(dirs)
        for filename in sorted(files):
            child = current / filename
            reject_symlink(child, root=allowed)
            if child.is_file():
                safe_resolve_under(child, allowed)
                yield child


def safe_copy_file_no_symlink(source: Path, dest: Path, allowed_root: Path) -> None:
    safe_resolve_under(source, allowed_root)
    reject_symlink(source, root=allowed_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def safe_copy_tree_no_symlink(source: Path, dest: Path, allowed_root: Path) -> None:
    if source.is_file():
        safe_copy_file_no_symlink(source, dest, allowed_root)
        return
    for source_file in safe_walk_files(source, allowed_root=allowed_root):
        rel = source_file.relative_to(source)
        safe_copy_file_no_symlink(source_file, dest / rel, allowed_root)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_output_path(
    path: str | Path,
    repo_root: Path,
    denied_roots: Sequence[Path],
    *,
    allow_overwrite: bool = False,
) -> Path:
    output = Path(path).expanduser()
    if not output.is_absolute():
        output = repo_root / output
    if output.exists() and output.is_symlink():
        raise SafePathError(f"output path must not be a symlink: {output}")
    if output.exists() and output.is_dir():
        raise SafePathError(f"output path is a directory: {output}")
    if output.exists() and not allow_overwrite:
        raise SafePathError(f"output path already exists; use --force to replace it: {output}")

    resolved_output = _resolved_candidate_for_existing_or_parent(output)
    for denied in denied_roots:
        denied_resolved = _resolved_candidate_for_existing_or_parent(denied)
        if resolved_output == denied_resolved or _is_relative_to(resolved_output, denied_resolved):
            raise SafePathError(f"output path is under protected path: {denied}")
    if not output.parent.exists():
        raise SafePathError(f"output parent does not exist: {output.parent}")
    return resolved_output
