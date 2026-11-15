from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / ".aiwf/bin/guidance.py"
RUNTIME = REPO_ROOT / ".aiwf/bin/ai_workflow.py"
TASK = ".aiwf/records/ai_20261114/001_example"
LEGACY = "POST_FINALIZATION_CORRECTION.md"
FORMAL = "corrections/001_conclusion_corrected.md"
NOTE_BODY = """## Recommended Checks

Keep the exact failure node.

## Applicability

Only for comparable test conditions.

## Inapplicable Cases

Recheck after a dependency change.

## Evidence and Limitations

The source is limited to the recorded run.

## Recheck Triggers

Recheck source or correction changes.
"""


def write_file(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_note(root, metadata, *, name="note", body=NOTE_BODY):
    return write_file(root, f".aiwf/guidance/{name}.md", f"---\n{yaml.safe_dump(metadata)}---\n\n{body}")


def run_helper(root, *args, helper=HELPER):
    return subprocess.run(
        [sys.executable, str(helper), "--repo-root", str(root), *args],
        cwd=root, env=os.environ | {"AIWF_EVENT_LOG": "1"}, capture_output=True, text=True,
    )


def run_runtime(root, *args, runtime=RUNTIME):
    result = subprocess.run(
        [sys.executable, "-B", str(runtime), "--repo-root", str(root), *args],
        cwd=root, env=os.environ | {"AIWF_PYTHON": sys.executable},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def write_correction(root):
    run_runtime(
        root, "correct-finalized", "--path", TASK, "--type", "conclusion_corrected",
        "--authority", "human_review", "--current-state", "Updated interpretation", "--reason", "Recheck this claim",
    )
    return root / TASK / FORMAL


def inventory(root):
    return {p.relative_to(root): digest(p) for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    write_file(root, ".aiwf/config.yaml", 'aiwf_layout_version: 2\nrecord_root: ".aiwf/records"\n')
    write_file(root, f"{TASK}/task.md", "---\nstatus: done\nworkflow_phase: finalized\nfinalized_at: 2026-11-14T00:00:00Z\n---\n# Example\n")
    write_file(root, ".aiwf/events/events.jsonl", '{"example":true}\n')
    write_file(root, f"{TASK}/.aiwf/events.jsonl", '{"example":true}\n')
    write_file(root, f"{TASK}/.aiwf/finalize_manifest.json", '{"example":true}\n')
    evidence = write_file(root, f"{TASK}/evidence/result.log", "same failure node\n")
    metadata = {
        "id": "GUIDE-EXAMPLE-001",
        "title": "Compare failure nodes",
        "status": "active",
        "scope": ["regression"],
        "sources": [{
            "task": TASK,
            "artifact": "evidence/result.log",
            "locator": "L1",
            "sha256": digest(evidence),
            "reviewed_corrections": [],
        }],
        "review_ref": "Review 42 for revision and file",
    }
    write_note(root, metadata)
    return root, metadata


def test_current_output_and_scope_are_read_only(project):
    root, _ = project
    before = inventory(root)
    check = run_helper(root, "check")
    current = run_helper(root, "show", "--scope", "regression")
    other = run_helper(root, "show", "--scope", "yaml")
    assert check.returncode == current.returncode == other.returncode == 0
    assert "sources match" in check.stdout
    assert NOTE_BODY.strip() in current.stdout
    assert f"{TASK}/evidence/result.log | L1" in current.stdout
    assert "Check applicability and authorization" in current.stdout
    assert "GUIDE-EXAMPLE-001" not in other.stdout
    assert inventory(root) == before


@pytest.mark.parametrize("command", ["show", "check"])
@pytest.mark.parametrize("selector", ["--scope", "--id"])
@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_selectors_are_rejected_before_query(project, command, selector, value):
    root, _ = project
    before = inventory(root)
    result = run_helper(root, command, selector, value)
    assert result.returncode == 2
    assert f"argument {selector}: selector must not be empty or whitespace" in result.stderr
    assert result.stdout == ""
    assert inventory(root) == before


def test_nonblank_selector_compatibility_is_read_only(project, monkeypatch):
    root, metadata = project
    helper_dir = root / ".aiwf/bin"
    shutil.copytree(HELPER.parent, helper_dir, ignore=shutil.ignore_patterns("__pycache__"))
    helper = helper_dir / HELPER.name
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)

    regression = metadata["id"]
    validation = "GUIDE-EXAMPLE-002"
    write_note(root, metadata | {"id": validation, "scope": ["validation"]}, name="validation")
    before = inventory(root)
    for selectors, expected in (
        ((), {regression, validation}),
        (("--scope", "regression"), {regression}),
        (("--id", regression), {regression}),
        (("--scope", "regression", "--scope", "validation"), {validation}),
        (("--scope", " regression "), set()),
    ):
        result = run_helper(root, "show", *selectors, helper=helper)
        assert result.returncode == 0, result.stderr
        assert {note_id for note_id in (regression, validation) if note_id in result.stdout} == expected
        assert (NOTE_BODY.strip() in result.stdout) == bool(expected)

    result = run_helper(root, "show", "--id", f" {regression} ", helper=helper)
    assert result.returncode == 2 and "No usable guidance entry found" in result.stdout
    assert NOTE_BODY.strip() not in result.stdout
    result = run_helper(root, "check", "--scope", "", helper=helper)
    assert result.returncode == 2 and result.stdout == ""
    assert inventory(root) == before


@pytest.mark.parametrize("status", ["draft", "withdrawn"])
def test_noncurrent_notes_require_explicit_id(project, status):
    root, metadata = project
    metadata.update(status=status, review_ref=None)
    write_note(root, metadata)
    assert metadata["id"] not in run_helper(root, "show").stdout
    explicit = run_helper(root, "show", "--id", metadata["id"])
    assert explicit.returncode == 0
    assert "Excluded from current references" in explicit.stdout
    assert NOTE_BODY.strip() in explicit.stdout


@pytest.mark.parametrize("remove", [True, False])
def test_missing_or_changed_artifact_withholds_default_body(project, remove):
    root, metadata = project
    artifact = root / TASK / "evidence/result.log"
    if remove:
        artifact.unlink()
    else:
        artifact.write_bytes(b"changed bytes")
    before = inventory(root)
    hidden = run_helper(root, "show")
    explicit = run_helper(root, "show", "--id", metadata["id"])
    assert hidden.returncode == explicit.returncode == 1
    assert "Compare failure nodes" in hidden.stdout and "REVIEW NEEDED" in hidden.stdout
    assert ("source unavailable" if remove else "source SHA-256 changed") in hidden.stdout
    assert NOTE_BODY.strip() not in hidden.stdout and NOTE_BODY.strip() in explicit.stdout
    assert inventory(root) == before


@pytest.mark.parametrize("change", ["added", "removed", "changed", "unknown", "malformed"])
def test_formal_correction_change_with_unchanged_artifact(project, change):
    root, metadata = project
    correction = write_correction(root)
    if change != "added":
        metadata["sources"][0]["reviewed_corrections"] = [{"path": FORMAL, "sha256": digest(correction)}]
        write_note(root, metadata)
        assert run_helper(root, "check").returncode == 0
    if change == "removed":
        correction.unlink()
    elif change == "changed":
        correction.write_text(correction.read_text() + "\nClarification.\n")
    elif change == "unknown":
        correction.write_text(correction.read_text().replace("aiwf-correction-v1", "unknown-schema"))
    elif change == "malformed":
        correction.write_text(correction.read_text().replace("created_by:", "created_by: earlier\ncreated_by:"))
    before = inventory(root)
    result = run_helper(root, "show")
    assert result.returncode == 1
    assert f"corrections {'unknown' if change == 'malformed' else change}" in result.stdout
    assert "source SHA-256 changed" not in result.stdout
    assert NOTE_BODY.strip() not in result.stdout
    assert inventory(root) == before


def test_supported_legacy_correction_and_unknown_baseline(project):
    root, metadata = project
    correction = write_file(
        root, f"{TASK}/{LEGACY}",
        "# Post-finalization correction\n\n## reason\n\nA\n\n## semantic_impact\n\nB\n\n## corrected_statement\n\nC\n",
    )
    assert "corrections added" in run_helper(root, "check").stdout
    metadata["sources"][0]["reviewed_corrections"] = [{"path": LEGACY, "sha256": digest(correction)}]
    write_note(root, metadata)
    assert run_helper(root, "check").returncode == 0
    write_file(root, f"{TASK}/errata.txt", "another format")
    assert "current corrections unknown" in run_helper(root, "check").stdout
    (root / TASK / "errata.txt").unlink()
    metadata["sources"][0]["reviewed_corrections"] = None
    write_note(root, metadata)
    result = run_helper(root, "show")
    assert result.returncode == 1 and "reviewed correction baseline unknown" in result.stdout


def test_configured_records_root_is_used_without_short_id_guessing(project):
    root, metadata = project
    (root / ".aiwf/records").rename(root / "custom-records")
    write_file(root, ".aiwf/config.yaml", "layout:\n  records_root: custom-records\n")
    metadata["sources"][0]["task"] = TASK.replace(".aiwf/records", "custom-records")
    write_note(root, metadata)
    assert run_helper(root, "check").returncode == 0
    metadata["sources"][0]["task"] = "001"
    write_note(root, metadata)
    assert run_helper(root, "check").returncode == 2


@pytest.mark.parametrize("kind", ["artifact", "task", "guidance", "corrections", "correction_leaf"])
def test_symlinks_are_withheld(project, tmp_path, kind):
    root, _ = project
    path = root / {
        "artifact": f"{TASK}/evidence/result.log",
        "task": TASK,
        "guidance": ".aiwf/guidance",
        "corrections": f"{TASK}/corrections",
        "correction_leaf": f"{TASK}/{LEGACY}",
    }[kind]
    outside = tmp_path / "outside"
    if path.exists():
        path.rename(outside)
    # The correction cases use broken links to ensure they are not treated as absent.
    path.symlink_to(outside, target_is_directory=kind in {"task", "guidance", "corrections"})
    result = run_helper(root, "show")
    assert result.returncode != 0
    assert "symlink" in result.stdout + result.stderr
    assert NOTE_BODY.strip() not in result.stdout


def test_markdown_is_printed_as_data(project):
    root, metadata = project
    payload = "## Recommended Checks\n\n```sh\ntouch SHOULD_NOT_EXIST\n```"
    write_note(root, metadata, body=NOTE_BODY.replace("## Recommended Checks\n\nKeep the exact failure node.", payload))
    before = inventory(root)
    result = run_helper(root, "show")
    assert result.returncode == 0 and "touch SHOULD_NOT_EXIST" in result.stdout
    assert inventory(root) == before


@pytest.mark.parametrize("problem", ["duplicate_id", "duplicate_key", "status", "sha256", "review", "traversal", "body"])
def test_invalid_metadata_is_reported_without_writes(project, problem):
    root, metadata = project
    if problem == "duplicate_id":
        write_note(root, metadata, name="second")
    elif problem == "duplicate_key":
        path = root / ".aiwf/guidance/note.md"
        path.write_text(path.read_text().replace("status: active", "status: draft\nstatus: active"))
    elif problem == "body":
        write_note(root, metadata, body=NOTE_BODY.replace("## Applicability", "## Other"))
    else:
        if problem == "status":
            metadata["status"] = "approved"
        elif problem == "sha256":
            metadata["sources"][0]["sha256"] = "<actual SHA>"
        elif problem == "review":
            metadata["review_ref"] = None
        else:
            metadata["sources"][0]["artifact"] = "../other/task.md"
        write_note(root, metadata)
    before = inventory(root)
    result = run_helper(root, "show")
    assert result.returncode == 2 and "INVALID" in result.stdout
    assert NOTE_BODY.strip() not in result.stdout
    assert inventory(root) == before


def test_install_and_upgrade_preserve_project_guidance(tmp_path):
    source = tmp_path / "package"
    source.mkdir()
    shutil.copy2(REPO_ROOT / "aiwf", source / "aiwf")
    for directory in ("bin", "docs", "templates"):
        shutil.copytree(REPO_ROOT / ".aiwf" / directory, source / ".aiwf" / directory)
    shutil.copy2(REPO_ROOT / ".aiwf/config.yaml", source / ".aiwf/config.yaml")
    write_file(source, ".aiwf/guidance/private.md", "source-private note")
    target = tmp_path / "target"
    private = write_file(target, ".aiwf/guidance/private.md", "project-owned note")
    run_runtime(source, "install", "--target", str(target), "--yes", runtime=source / ".aiwf/bin/ai_workflow.py")
    installed = target / ".aiwf/bin/guidance.py"
    assert installed.is_file()
    assert private.read_text() == "project-owned note"
    write_file(source, ".aiwf/guidance/second.md", "not shipped")
    installed.unlink()
    (target / ".aiwf/docs/guidance.md").unlink()
    result = run_runtime(target, "upgrade", "--source", str(source), "--apply")
    assert "migration" in result.lower() and installed.is_file()
    assert (target / ".aiwf/docs/guidance.md").is_file()
    assert private.read_text() == "project-owned note"
    assert not (private.parent / "second.md").exists()
    assert "INVALID .aiwf/guidance/private.md" in run_helper(target, "check", helper=installed).stdout


def test_core_task_can_finalize_with_guidance_helper_and_notes_absent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    run_runtime(REPO_ROOT, "install", "--target", str(target), "--yes")
    (target / ".aiwf/bin/guidance.py").unlink()
    assert not (target / ".aiwf/guidance").exists()
    runtime = target / ".aiwf/bin/ai_workflow.py"
    run_runtime(target, "new-task", "core_smoke", runtime=runtime)
    task = next((target / ".aiwf/records").glob("ai_*/001_core_smoke"))
    relative = task.relative_to(target).as_posix()
    for path in task.glob("*.md"):
        original = path.read_text()
        if path.name == "task.md":
            metadata, body = original.rsplit("\n---\n", 1)
            original = metadata + "\n---\n" + body.split("\n## Background", 1)[0] + """
## Background

This fixture represents a new task in a project without guidance.

## Problem

Exercise the core closure path without the optional helper.

## Goal

Finalize an otherwise complete task.

## Acceptance Criteria

- [x] The synthetic test task has complete evidence.

## Risk

Temporary files only.
"""
        else:
            original = original.splitlines()[0] + "\n\n" + "\n\n".join(
                heading + "\n\nCore workflow smoke test." for heading in (
                    line for line in original.splitlines() if line.startswith("## ")
                )
            ) + "\n"
        path.write_text(original, encoding="utf-8")
    run_runtime(target, "record", "--path", relative, "--kind", "validation", "--result", "pass", runtime=runtime)
    run_runtime(
        target, "record", "--path", relative, "--kind", "review", "--result", "pass",
        "--reviewer", "human", "--decision-authority", "human", "--recorded-by", "test-fixture", runtime=runtime,
    )
    run_runtime(target, "finalize", "--path", relative, runtime=runtime)
    assert 'workflow_phase: "finalized"' in (task / "task.md").read_text()
