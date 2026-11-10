from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

import pytest

from test_ai_workflow import ai_workflow


LEGACY_PROFILE = (
    b"# operator comment\r\n"
    b"AIWF_AGENT_TOOL=codex\r\n"
    b"AIWF_MODEL_PROVIDER=openai\r\n"
    b'AIWF_MODEL_NAME="legacy model"\r\n'
    b"AIWF_REASONING_EFFORT=high\r\n"
    b"AIWF_METADATA_SOURCE=profile\r\n"
    b"AIWF_METADATA_CONFIDENCE=high\r\n"
    b"\r\n"
    b"# retain exact configuration line\r\n"
    b"  AIWF_EVENT_LOG = '0'\r\n"
    b"# no trailing newline"
)
CLEAN_PROFILE = (
    b"# operator comment\r\n\r\n"
    b"# retain exact configuration line\r\n"
    b"  AIWF_EVENT_LOG = '0'\r\n"
    b"# no trailing newline"
)


def _repo(tmp_path: Path, profile: bytes = LEGACY_PROFILE) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    profiles = root / ".aiwf" / "metadata_profiles"
    profiles.mkdir(parents=True)
    selected = profiles / "legacy.env"
    selected.write_bytes(profile)
    (root / ".aiwf" / "metadata.current").write_bytes(b"legacy\n")
    # Protect a representative set of historical/configuration artifacts.
    for relative in (
        ".aiwf/records/ai_20260101/001_history/task.md",
        ".aiwf/records/ai_20260101/001_history/review_final.md",
        ".aiwf/records/ai_20260101/001_history/.aiwf/events.jsonl",
        ".aiwf/records/ai_20260101/001_history/finalize_manifest.json",
        ".aiwf/events/events.jsonl",
        ".aiwf/metadata.local.env",
        ".env",
        ".aiwf/metadata_profiles/other.env",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"historical/configuration bytes must remain unchanged\n")
    return root, selected


def _snapshot(root: Path) -> dict[str, tuple]:
    snapshot = {}
    for target in sorted(root.rglob("*")):
        entry = target.lstat()
        key = target.relative_to(root).as_posix()
        if target.is_symlink():
            snapshot[key] = ("symlink", os.readlink(target), entry.st_mtime_ns)
        elif target.is_file():
            snapshot[key] = (
                "file", hashlib.sha256(target.read_bytes()).hexdigest(),
                entry.st_mtime_ns, stat.S_IMODE(entry.st_mode),
            )
        else:
            snapshot[key] = ("directory", entry.st_mtime_ns)
    return snapshot


def test_migration_dry_run_uses_complete_plan_and_leaves_tree_unchanged(tmp_path, capsys):
    root, selected = _repo(tmp_path)
    before = _snapshot(root)
    assert ai_workflow.main(["--repo-root", str(root), "profile", "migrate", "--dry-run"]) == 0
    assert _snapshot(root) == before
    assert selected.read_bytes() == LEGACY_PROFILE
    output = capsys.readouterr().out
    for key in ai_workflow.AI_AGENT_METADATA_ENV_MAP.values():
        assert f"removed: {key}" in output
    assert "preserved: AIWF_EVENT_LOG" in output
    assert "reclassified as configured legacy evidence" in output
    assert "Historical evidence unchanged" in output
    assert "Dry-run: no files changed." in output


def test_migration_preserves_line_bytes_permissions_and_all_other_files(tmp_path, capsys, monkeypatch):
    root, selected = _repo(tmp_path)
    selected.chmod(0o640)
    before = _snapshot(root)
    assert ai_workflow.main(["--repo-root", str(root), "metadata", "profile", "migrate"]) == 0
    assert selected.read_bytes() == CLEAN_PROFILE
    assert stat.S_IMODE(selected.stat().st_mode) == 0o640
    after = _snapshot(root)
    # Directory mtime changes only for the atomic replacement in selected parent.
    excluded = {".aiwf/metadata_profiles", ".aiwf/metadata_profiles/legacy.env"}
    assert {k: v for k, v in after.items() if k not in excluded} == {
        k: v for k, v in before.items() if k not in excluded
    }
    assert set(before) == set(after)
    assert "MIGRATED" in capsys.readouterr().out
    for key in ai_workflow.ENV_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    assert ai_workflow.load_aiwf_env(root)["AIWF_EVENT_LOG"] == "0"
    assert ai_workflow.metadata_validate_command(root) == 0
    capsys.readouterr()
    migrated = _snapshot(root)
    for arguments in (["profile", "migrate"], ["metadata", "profile", "migrate", "legacy"], ["profile", "migrate", "--dry-run"]):
        assert ai_workflow.main(["--repo-root", str(root), *arguments]) == 0
        assert _snapshot(root) == migrated
        assert "No migration required." in capsys.readouterr().out


def test_explicit_name_does_not_require_or_modify_current_pointer(tmp_path):
    root, selected = _repo(tmp_path)
    (root / ".aiwf" / "metadata.current").unlink()
    assert ai_workflow.main(["--repo-root", str(root), "profile", "migrate", "legacy"]) == 0
    assert selected.read_bytes() == CLEAN_PROFILE
    assert not (root / ".aiwf" / "metadata.current").exists()


@pytest.mark.parametrize("profile", [
    b"AIWF_MODEL_NAME=gpt-x\nnot an assignment\nAIWF_EVENT_LOG=1\n",
    b"AIWF_MODEL_NAME=gpt-x\nAIWF_MODEL_NAME=gpt-y\n",
    b"AIWF_EVENT_LOG=1\nAIWF_EVENT_LOG=0\n",
    b"AIWF_MODEL_NAME=gpt-x\nINTEGRATION_URL=example\n",
    b"AIWF_AGENT_TOOL=unregistered\n",
    b"AIWF_MODEL_PROVIDER=unregistered\n",
    b"AIWF_REASONING_EFFORT=maximum\n",
    b"AIWF_METADATA_SOURCE=unknown_source\n",
    b"AIWF_METADATA_CONFIDENCE=unbounded\n",
    b"AIWF_EVENT_LOG=true\n",
    b"AIWF_EVENT_LOG=1 # keep\n",
    b"AIWF_EVENT_LOG='0' # keep\n",
    b"AIWF_AGENT_TOOL=codex # hint\n",
    b"AIWF_MODEL_PROVIDER='openai' # hint\n",
    b"AIWF_METADATA_SOURCE=profile # hint\n",
    b"AIWF_METADATA_CONFIDENCE=high # hint\n",
    b"AIWF_MODEL_NAME=\n",
    b'AIWF_MODEL_NAME="unterminated\n',
    b'AIWF_MODEL_NAME="a""b"\n',
    b"AIWF_MODEL_NAME=a b\n",
    b"AIWF_MODEL_NAME=$(whoami)\n",
    b"AIWF_MODEL_NAME=`whoami`\n",
    b"AIWF_MODEL_NAME=gpt;command\n",
    b"AIWF_MODEL_NAME=gpt\\\n",
    b"export AIWF_MODEL_NAME=gpt-x\n",
    b"AIWF_MODEL_CLASS=example\n",
    b"AIWF_ACTOR_IDENTITY={}\n",
    b"AIWF_MODEL_NAME=bad\x00value\n",
    b"AIWF_MODEL_NAME=\xff\n",
])
@pytest.mark.parametrize("dry_run", [False, True])
def test_invalid_profile_aborts_entire_plan_without_tree_changes(tmp_path, capsys, profile, dry_run):
    root, _ = _repo(tmp_path, profile)
    before = _snapshot(root)
    assert ai_workflow.metadata_profile_migrate_command(root, dry_run=dry_run) == 2
    assert _snapshot(root) == before
    assert "AIWF-PROFILE-MIGRATE-001" in capsys.readouterr().out


@pytest.mark.parametrize("pointer", [None, b"", b"../legacy\n", b"legacy\nother\n", b"missing\n", b"\xff\n"])
def test_invalid_current_pointer_has_no_side_effects(tmp_path, capsys, pointer):
    root, _ = _repo(tmp_path)
    current = root / ".aiwf" / "metadata.current"
    if pointer is None:
        current.unlink()
    else:
        current.write_bytes(pointer)
    before = _snapshot(root)
    assert ai_workflow.metadata_profile_migrate_command(root) == 2
    assert _snapshot(root) == before
    assert "AIWF-PROFILE-MIGRATE-001" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["../legacy", "Legacy", "legacy.env", "legacy\n", "missing"])
def test_invalid_explicit_profile_name_does_not_normalize_or_create_paths(tmp_path, name):
    root, _ = _repo(tmp_path)
    before = _snapshot(root)
    assert ai_workflow.metadata_profile_migrate_command(root, name) == 2
    assert _snapshot(root) == before


@pytest.mark.parametrize("component", ["profile", "profiles_parent", "aiwf_parent", "pointer"])
@pytest.mark.parametrize("outside", [False, True])
def test_migration_rejects_symlink_components_even_to_repository_history(tmp_path, component, outside):
    root, selected = _repo(tmp_path)
    destination = tmp_path / "outside" if outside else root / "history"
    destination.mkdir()
    if component == "profile":
        target = destination / "profile.env"
        target.write_bytes(LEGACY_PROFILE)
        selected.unlink()
        selected.symlink_to(target)
    elif component == "pointer":
        target = destination / "current"
        target.write_bytes(b"legacy\n")
        current = root / ".aiwf" / "metadata.current"
        current.unlink()
        current.symlink_to(target)
    else:
        source = root / ".aiwf" / "metadata_profiles" if component == "profiles_parent" else root / ".aiwf"
        target = destination / "linked"
        source.rename(target)
        source.symlink_to(target, target_is_directory=True)
    before_root = _snapshot(root)
    before_destination = _snapshot(destination)
    assert ai_workflow.metadata_profile_migrate_command(root) == 2
    assert _snapshot(root) == before_root
    assert _snapshot(destination) == before_destination


def test_atomic_replace_failure_keeps_profile_and_no_temporary_files(tmp_path, monkeypatch):
    root, selected = _repo(tmp_path)
    before = _snapshot(root)
    def fail_replace(*_args):
        raise OSError("injected atomic replace failure")
    monkeypatch.setattr(ai_workflow.os, "replace", fail_replace)
    assert ai_workflow.metadata_profile_migrate_command(root) == 2
    assert selected.read_bytes() == LEGACY_PROFILE
    after = _snapshot(root)
    # Creating/removing a temporary file may change only the profile directory mtime.
    assert set(before) == set(after)
    assert {k: v for k, v in after.items() if k != ".aiwf/metadata_profiles"} == {
        k: v for k, v in before.items() if k != ".aiwf/metadata_profiles"
    }


def test_future_registered_field_is_not_automatically_classified_for_removal(tmp_path, monkeypatch):
    root, _ = _repo(tmp_path, b"AIWF_FUTURE_MODEL=hint\n")
    monkeypatch.setitem(ai_workflow.AI_AGENT_METADATA_ENV_MAP, "future_model", "AIWF_FUTURE_MODEL")
    before = _snapshot(root)
    assert ai_workflow.metadata_profile_migrate_command(root) == 2
    assert _snapshot(root) == before


def test_migration_does_not_require_unix_only_fchmod(tmp_path, monkeypatch):
    root, selected = _repo(tmp_path)
    selected.chmod(0o640)
    before_mode = stat.S_IMODE(selected.stat().st_mode)
    monkeypatch.delattr(ai_workflow.os, "fchmod", raising=False)
    assert ai_workflow.metadata_profile_migrate_command(root) == 0
    assert selected.read_bytes() == CLEAN_PROFILE
    assert stat.S_IMODE(selected.stat().st_mode) == before_mode


def test_clean_empty_profile_is_noop_without_mutation(tmp_path, capsys):
    root, _ = _repo(tmp_path, b"# only comments\r\n")
    before = _snapshot(root)
    assert ai_workflow.metadata_profile_migrate_command(root) == 0
    assert _snapshot(root) == before
    assert "No migration required." in capsys.readouterr().out
