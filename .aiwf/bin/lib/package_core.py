from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class ManifestRow:
    sha256: str
    git_mode: str
    size: int
    package_relative_path: str


def normalize_package_path(raw: str) -> str:
    text = str(raw).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if not text:
        raise ValueError("package path must not be empty")
    if text.startswith("/"):
        raise ValueError("package path must be relative")

    path = PurePosixPath(text)
    parts = path.parts
    if any(part == ".." for part in parts):
        raise ValueError("package path must not contain parent traversal")
    if not parts or any(part in {"", "."} for part in parts):
        raise ValueError("package path must contain stable path segments")
    return path.as_posix()


def repo_to_package_path(repo_root: Path, path: Path, *, package_prefix: str = "") -> str:
    try:
        rel_path = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        raise ValueError("path must be under repository root")
    if package_prefix:
        return normalize_package_path(f"{package_prefix}/{rel_path}")
    return normalize_package_path(rel_path)


def stable_sort(items: Iterable[T], key: Callable[[T], object]) -> list[T]:
    return sorted(items, key=key)


def stable_json_dump(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def stable_tsv_dump(rows: Sequence[Sequence[object]]) -> str:
    return "".join("\t".join(str(value) for value in row) + "\n" for row in rows)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_sha256(path: Path) -> str:
    if path.is_symlink():
        return sha256_bytes(os.readlink(path).encode("utf-8"))
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    if path.is_symlink():
        return len(os.readlink(path).encode("utf-8"))
    return path.stat().st_size


def git_mode(path: Path) -> str:
    if path.is_symlink():
        return "120000"
    if os.access(path, os.X_OK):
        return "100755"
    return "100644"


def build_manifest_row(*, sha256: str, git_mode: str, size: int, package_relative_path: str) -> ManifestRow:
    return ManifestRow(
        sha256=sha256,
        git_mode=git_mode,
        size=int(size),
        package_relative_path=normalize_package_path(package_relative_path),
    )


def manifest_row_tsv(row: ManifestRow) -> str:
    return stable_tsv_dump([[row.sha256, row.git_mode, row.size, row.package_relative_path]])
