"""Cooperative locking and interrupted-write detection for local AIWF storage."""

from __future__ import annotations

import contextvars
import errno
import json
import os
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


MARKER = ".aiwf-mutation-pending"
LOCK_TIMEOUT = 5.0


class WorkflowLockError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.operation_status = {
            "AIWF-LOCK-BUSY": "timeout", "AIWF-LOCK-UNSUPPORTED": "unsupported",
            "AIWF-RECOVERY-REQUIRED": "blocked", "AIWF-MUTATION-INCOMPLETE": "failed",
        }[code]
        self.requires_reconciliation = code in {"AIWF-RECOVERY-REQUIRED", "AIWF-MUTATION-INCOMPLETE"}
        self.mutation_state = "unknown" if code == "AIWF-MUTATION-INCOMPLETE" else "not_applied"


def unsupported() -> WorkflowLockError:
    return WorkflowLockError("AIWF-LOCK-UNSUPPORTED", "Cannot establish a supported single-owner local storage lock.")


def mutation_root_writable(root: Path) -> bool:
    """Check effective directory permissions without creating a probe file."""
    try:
        return os.access(root, os.W_OK | os.X_OK, effective_ids=True)
    except NotImplementedError:
        return (os.getuid() == os.geteuid() and os.getgid() == os.getegid()
                and os.access(root, os.W_OK | os.X_OK))


def marker_permission_error() -> WorkflowLockError:
    return WorkflowLockError("AIWF-LOCK-UNSUPPORTED",
                             "The Runtime process needs write and search access to the worktree root "
                             "to manage its recovery marker. Use read-only mode for this account.")


def incomplete() -> WorkflowLockError:
    return WorkflowLockError("AIWF-MUTATION-INCOMPLETE", "Write outcome requires reconciliation. Preserve the marker and inspect both event logs, task metadata, manifest and index before further mutation.")


def recovery_required() -> WorkflowLockError:
    return WorkflowLockError("AIWF-RECOVERY-REQUIRED", "A prior writer left an incomplete-operation marker. Inspect preserved task, index and event evidence before resuming.")


@dataclass
class _Lease:
    root: Path
    fd: int
    writer: bool
    operation: str
    target: str | None
    pid: int
    started: bool = False
    uncertain: bool = False


_lease = contextvars.ContextVar("_workflow_lease", default=None)


def participating() -> bool:
    return _lease.get() is not None


def mutation_started() -> bool:
    lease = _lease.get()
    return bool(lease and lease.started)


def require_reconciliation() -> None:
    lease = _lease.get()
    if lease is not None:
        lease.uncertain = True


def set_allocated_target(root: Path, task: Path) -> None:
    lease = _lease.get()
    if lease is not None and not lease.started and lease.operation == "new-task":
        lease.target = task.relative_to(root).as_posix()


def mark_mutation_started(path: Path | None = None) -> None:
    """Install the intent before the first governed write. Internal direct calls have no CLI lease."""
    lease = _lease.get()
    if lease is None:
        return
    if not lease.writer:
        raise unsupported()
    if path is not None:
        verify_path(lease.root, path)
    if lease.started:
        return
    payload = {"version": 1, "operation": lease.operation, "target": lease.target}
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    try:
        fd = os.open(MARKER, flags, 0o600, dir_fd=lease.fd)
        lease.started = True
        with os.fdopen(fd, "w", encoding="utf-8") as marker:
            json.dump(payload, marker)
            marker.write("\n")
            marker.flush()
            os.fsync(marker.fileno())
        os.fsync(lease.fd)
    except OSError as exc:
        if lease.started:
            raise incomplete() from exc
        if exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise marker_permission_error() from exc
        raise unsupported() from exc


def _linux_mounts() -> list[tuple[Path, str, str, str]]:
    result = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        pre, post = line.split(" - ", 1)
        fields = pre.split()
        target = fields[4].replace(r"\040", " ").replace(r"\011", "\t").replace(r"\012", "\n").replace(r"\134", "\\")
        result.append((Path(target), fields[0], fields[3], post.split()[0]))
    return sorted(result, key=lambda row: len(row[0].parts), reverse=True)


def _has_local_backend(root: Path) -> bool:
    if fcntl is None:
        return False
    if sys.platform == "darwin":
        # Darwin df -T filters the actual filesystem containing this path.
        result = subprocess.run(["/bin/df", "-T", "apfs,hfs", str(root)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=2, check=False)
        return result.returncode == 0
    elif sys.platform.startswith("linux"):
        for mount, _, mount_root, kind in _linux_mounts():
            if root.is_relative_to(mount):
                if mount_root != "/":
                    raise unsupported()
                return kind in {"ext2", "ext3", "ext4", "xfs", "btrfs", "tmpfs", "overlay"}
    return False


def _is_workflow_root(path: Path) -> bool:
    return (path / ".aiwf/config.yaml").exists() or (path / ".aiwf/bin/ai_workflow.py").exists()


def verify_path(root: Path, target: Path) -> None:
    """Refuse paths that could share writable storage under a different lease."""
    if not target.is_relative_to(root) or ".." in target.parts:
        raise unsupported()
    device = root.stat().st_dev
    mounted = set()
    if sys.platform.startswith("linux"):
        mounted = {row[0] for row in _linux_mounts() if row[0] != root}
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        try:
            attrs = current.lstat()
        except FileNotFoundError:
            break
        if attrs.st_dev != device or current in mounted or stat.S_ISLNK(attrs.st_mode):
            raise unsupported()
        if stat.S_ISDIR(attrs.st_mode):
            if _is_workflow_root(current):
                raise unsupported()
        elif not stat.S_ISREG(attrs.st_mode) or attrs.st_nlink != 1:
            raise unsupported()


@contextmanager
def workflow_lock(root: Path, *, writer: bool, operation: str, target: str | None = None,
                  timeout: float = LOCK_TIMEOUT, allow_unlocked_observation: bool = False):
    root = root.resolve(strict=True)
    parent = _lease.get()
    if parent and parent.pid == os.getpid():
        if parent.root != root or (writer and not parent.writer):
            raise unsupported()
        yield
        return
    # --repo-root also accepts a legacy directory without an installation.
    # A subdirectory cannot independently own its enclosing project's data.
    if not _is_workflow_root(root) and any(_is_workflow_root(p) for p in root.parents):
        raise unsupported()
    try:
        qualified = _has_local_backend(root)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise unsupported() from exc
    if not qualified:
        if writer or not allow_unlocked_observation:
            raise unsupported()
        try:
            (root / MARKER).lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise unsupported() from exc
        else:
            raise recovery_required()
        print("[WARN] AIWF-LOCK-UNSUPPORTED: Unconfirmed observation without a shared lock. "
              "Readiness and mutation require qualified local storage.", file=sys.stderr)
        yield
        return
    try:
        fd = os.open(root, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise unsupported() from exc
    try:
        mode = (fcntl.LOCK_EX if writer else fcntl.LOCK_SH) | fcntl.LOCK_NB
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, mode)
                break
            except OSError as exc:
                if exc.errno not in {errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK}:
                    raise unsupported() from exc
                if time.monotonic() >= deadline:
                    raise WorkflowLockError("AIWF-LOCK-BUSY", "Timed out before acquiring the workflow storage lock.") from exc
                time.sleep(0.025)
        try:
            os.stat(MARKER, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise recovery_required()
        lease = _Lease(root, fd, writer, operation, target, os.getpid())
        token = _lease.set(lease)
        try:
            try:
                yield
            except BaseException as exc:
                if lease.started:
                    raise incomplete() from exc
                raise
            if lease.started and not lease.uncertain:
                try:
                    os.unlink(MARKER, dir_fd=fd)
                    os.fsync(fd)
                except OSError as exc:
                    raise incomplete() from exc
        finally:
            _lease.reset(token)
    finally:
        os.close(fd)
