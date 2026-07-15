from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
REMOVED_ROOT_PACKAGE_HELPER = Path("scripts") / ("package_aiwf" + "_repo.sh")


def _load_aiwf_runtime():
    spec = importlib.util.spec_from_file_location("ai_workflow_under_test", REPO_ROOT / ".aiwf" / "bin" / "ai_workflow.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ai_workflow = _load_aiwf_runtime()


def _init_repo(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("# test repo\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    return tmp_path


def _seed_legacy_relocation_layout(root: Path) -> Path:
    docs = root / "docs"
    (docs / "workflow_protocol.md").write_text("workflow protocol\n", encoding="utf-8")
    (docs / "diagnostics.md").write_text("diagnostics\n", encoding="utf-8")
    (docs / "repo_boundary.md").write_text("repo boundary\n", encoding="utf-8")
    (docs / "adoption_guide.md").write_text("adoption guide\n", encoding="utf-8")
    (docs / "reporting.md").write_text("reporting\n", encoding="utf-8")
    (docs / "agent_integration.md").write_text("agent integration\n", encoding="utf-8")
    (docs / "metadata.md").write_text("metadata\n", encoding="utf-8")
    (docs / "packaging.md").write_text("packaging\n", encoding="utf-8")

    (docs / "agent_rules" / "templates").mkdir(parents=True, exist_ok=True)
    (docs / "agent_rules" / "00_index.md").write_text("agent rules index\n", encoding="utf-8")
    (docs / "agent_rules" / "templates" / "task.md").write_text("task template\n", encoding="utf-8")
    (docs / "releases").mkdir(parents=True, exist_ok=True)
    (docs / "releases" / "v1.0.md").write_text("release 1.0\n", encoding="utf-8")
    (docs / "examples" / "ci").mkdir(parents=True, exist_ok=True)
    (docs / "examples" / "basic_lifecycle.md").write_text("example\n", encoding="utf-8")
    (docs / "examples" / "ci" / "gitlab-aiwf-minimal.yml").write_text("pipeline\n", encoding="utf-8")
    (docs / "knowledge" / "bugs").mkdir(parents=True, exist_ok=True)
    (docs / "knowledge" / "README.md").write_text("knowledge root\n", encoding="utf-8")
    (docs / "knowledge" / "bugs" / "README.md").write_text("knowledge bug\n", encoding="utf-8")

    task_dir = docs / "ai_20260610" / "001_legacy_task"
    task_dir.mkdir(parents=True, exist_ok=True)
    for name in ["task.md", "task_record.md", "self_validation.md", "review_codex.md", "review_final.md"]:
        (task_dir / name).write_text(f"{name}\n", encoding="utf-8")

    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "ai_workflow.py").write_text("print('legacy runtime')\n", encoding="utf-8")
    return task_dir


def _write_legacy_upgrade_runtime(root: Path, *, tool_version: str = "1.7.5.post5", protocol_version: str = "1.7.5") -> None:
    (root / "tools" / "ai_workflow.py").write_text(
        "\n".join(
            [
                f'AIWF_TOOL_VERSION = "{tool_version}"',
                f'WORKFLOW_PROTOCOL_VERSION = "{protocol_version}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _snapshot_text_files(paths: list[Path]) -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in paths}


def _assert_text_files_unchanged(before: dict[Path, str]) -> None:
    for path, content in before.items():
        assert path.read_text(encoding="utf-8") == content


def _symlink_or_skip(link: Path, target: Path | str, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


def _copy_supported_install_set(source_root: Path, target_root: Path) -> None:
    (target_root / ".aiwf").mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "aiwf", target_root / "aiwf")
    (target_root / "aiwf").chmod(0o755)
    for dirname in ("bin", "docs", "templates"):
        shutil.copytree(
            source_root / ".aiwf" / dirname,
            target_root / ".aiwf" / dirname,
            dirs_exist_ok=True,
        )
    shutil.copy2(source_root / ".aiwf" / "config.yaml", target_root / ".aiwf" / "config.yaml")


def test_supported_first_install_preserves_project_scripts_and_does_not_create_removed_helper(tmp_path: Path):
    root = tmp_path
    project_script = root / "scripts" / "project_build.sh"
    project_script.parent.mkdir(parents=True)
    project_script.write_text("#!/usr/bin/env bash\necho project\n", encoding="utf-8")
    before = _snapshot_text_files([project_script])

    _copy_supported_install_set(REPO_ROOT, root)
    rc = ai_workflow.agents_install_command(root, "AGENTS.md", yes=True)

    assert rc == 0
    _assert_text_files_unchanged(before)
    assert not (root / REMOVED_ROOT_PACKAGE_HELPER).exists()
    source_review_helper = REPO_ROOT / ".aiwf" / "bin" / "package_review_bundle.sh"
    installed_review_helper = root / ".aiwf" / "bin" / "package_review_bundle.sh"
    assert installed_review_helper.exists() == source_review_helper.exists()


def _seed_upgrade_target_repo(root: Path) -> Path:
    _init_repo(root)
    _seed_legacy_relocation_layout(root)
    (root / "aiwf").write_text((REPO_ROOT / "aiwf").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "aiwf").chmod(0o755)
    _write_legacy_upgrade_runtime(root)
    (root / ".aiwf").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "config.yaml").write_text(
        "\n".join(
            [
                "layout:",
                "  records_root: docs",
                "project_note: keep-me",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _seed_current_v2_repo(root: Path, *, with_legacy_docs: bool = False) -> Path:
    _init_repo(root)
    if with_legacy_docs:
        _seed_legacy_relocation_layout(root)
    (root / ".aiwf" / "records").mkdir(parents=True, exist_ok=True)
    _copy_supported_install_set(REPO_ROOT, root)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "ai_workflow.py").write_text(
        "print('project-owned legacy tools file')\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "config.yaml").write_text(
        "\n".join(
            [
                "aiwf_layout_version: 2",
                'docs_root: ".aiwf/docs"',
                'record_root: ".aiwf/records"',
                'event_log: ".aiwf/events/events.jsonl"',
                "legacy_enabled: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _seed_minimal_upgrade_source(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "aiwf").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / "aiwf").chmod(0o755)
    runtime = root / ".aiwf" / "bin" / "ai_workflow.py"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        "\n".join(
            [
                'AIWF_TOOL_VERSION = "9.9.9"',
                'WORKFLOW_PROTOCOL_VERSION = "9.9.9"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "bin" / "safe_paths.py").write_text("class SafePathError(ValueError):\n    pass\n", encoding="utf-8")
    (root / ".aiwf" / "bin" / "lib").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "bin" / "lib" / "package_core.py").write_text("# package core\n", encoding="utf-8")
    (root / ".aiwf" / "docs").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "docs" / "workflow_protocol.md").write_text("protocol\n", encoding="utf-8")
    (root / ".aiwf" / "templates").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "templates" / "AGENTS.block.md").write_text("managed block\n", encoding="utf-8")
    return root


def test_find_repo_root_uses_aiwf_marker_without_root_docs(tmp_path: Path):
    root = tmp_path / "repo"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    (root / ".aiwf" / "bin").mkdir(parents=True)
    (root / ".aiwf" / "bin" / "ai_workflow.py").write_text("# runtime marker\n", encoding="utf-8")

    assert ai_workflow.find_repo_root(nested) == root.resolve()


def test_find_repo_root_ignores_project_docs_without_aiwf_marker(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)

    with pytest.raises(SystemExit) as exc:
        ai_workflow.find_repo_root(root)

    assert ".aiwf/config.yaml" in str(exc.value)


def _create_task(root: Path, *, name: str = "fix_ddf_cleanup", date: str = "20260508") -> Path:
    day_dir = root / "docs" / f"ai_{date}"
    before = {p.name for p in day_dir.iterdir()} if day_dir.exists() else set()
    rc = ai_workflow.create_task(root, name, date, update_existing=False, allow_non_today_date=True)
    assert rc == 0
    tasks = sorted(p for p in day_dir.iterdir() if p.is_dir() and p.name not in before)
    assert len(tasks) == 1
    return tasks[0]


def _write_v2_config(root: Path) -> None:
    cfg_dir = root / ".aiwf"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "\n".join(
            [
                "aiwf_layout_version: 2",
                'docs_root: ".aiwf/docs"',
                'record_root: ".aiwf/records"',
                'event_log: ".aiwf/events/events.jsonl"',
                "legacy_enabled: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _create_v2_task(root: Path, *, name: str = "fix_ddf_cleanup", date: str = "20260508") -> Path:
    _write_v2_config(root)
    day_dir = root / ".aiwf" / "records" / f"ai_{date}"
    before = {p.name for p in day_dir.iterdir()} if day_dir.exists() else set()
    rc = ai_workflow.create_task(root, name, date, update_existing=False, allow_non_today_date=True)
    assert rc == 0
    tasks = sorted(p for p in day_dir.iterdir() if p.is_dir() and p.name not in before)
    assert len(tasks) == 1
    return tasks[0]


def _redaction_fixture_internal_url() -> str:
    return "https" + "://ci." + "internal/build/1"


def _redaction_fixture_user_path() -> str:
    return "/Users/" + "alice/project/repo"


def _redaction_fixture_private_ip() -> str:
    return "10." + "1.2.3"


def test_new_task_creates_review_agent_and_not_review_codex(tmp_path: Path):
    root = _init_repo(tmp_path)

    task_dir = _create_task(root, date="20260513")

    assert (task_dir / "review_agent.md").is_file()
    assert not (task_dir / "review_codex.md").exists()
    assert "# Agent Self Review" in (task_dir / "review_agent.md").read_text(encoding="utf-8")
    assert ai_workflow.check_path(root, str(task_dir), strict=False) == 0


def test_legacy_review_codex_alias_is_accepted_without_migration(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    (task_dir / "review_agent.md").rename(task_dir / "review_codex.md")

    assert ai_workflow.check_path(root, str(task_dir), strict=False) == 0
    guard_rc, guard_text = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)

    assert guard_rc == 0
    assert "AIWF-GUARD-PASS" in guard_text
    assert (task_dir / "review_codex.md").exists()
    assert not (task_dir / "review_agent.md").exists()


def _seed_backfill_target(root: Path, *, date: str = "20260501", name: str = "001_legacy_task") -> Path:
    target = root / "docs" / f"ai_{date}" / name
    target.mkdir(parents=True, exist_ok=True)
    return target


def _rewrite_task_metadata(task_md_path: Path, **updates) -> None:
    text = task_md_path.read_text(encoding="utf-8")
    metadata, body = ai_workflow.parse_front_matter(text)
    metadata.update(updates)
    task_md_path.write_text(ai_workflow.format_front_matter(metadata) + body.lstrip("\n"), encoding="utf-8")


def _write_task_body(
    task_dir: Path,
    *,
    background: str = "Concrete task background.",
    problem: str = "Concrete task problem.",
    goal: str = "Concrete task goal.",
    acceptance_lines: list[str] | None = None,
    risk: str = "Workflow-only risk.",
    validation_plan_lines: list[str] | None = None,
) -> None:
    task_md_path = task_dir / "task.md"
    text = task_md_path.read_text(encoding="utf-8")
    metadata, _body = ai_workflow.parse_front_matter(text)
    acceptance = acceptance_lines or [
        "- [x] Required workflow files exist.",
        "- [x] Validation results are documented.",
    ]
    validation_plan = validation_plan_lines or [
        "- python3 -m py_compile .aiwf/bin/ai_workflow.py",
        "- pytest tests/unit/test_ai_workflow.py -q",
    ]
    body = "\n".join(
        [
            f"# Task: {metadata['title']}",
            "",
            "## Background",
            "",
            background,
            "",
            "## Problem",
            "",
            problem,
            "",
            "## Goal",
            "",
            goal,
            "",
            "## Constraints",
            "",
            "- Keep changes surgical.",
            "- Prefer offline validation.",
            "",
            "## Acceptance Criteria",
            "",
            *acceptance,
            "",
            "## Risk",
            "",
            risk,
            "",
            "## Validation Plan",
            "",
            *validation_plan,
            "",
        ]
    )
    task_md_path.write_text(ai_workflow.format_front_matter(metadata) + body, encoding="utf-8")


def _write_finalize_ready_docs(task_dir: Path) -> None:
    _write_task_body(task_dir)
    (task_dir / "task_record.md").write_text(
        "\n".join(
            [
                "# Task Record",
                "## Changed",
                "- Updated workflow logic.",
                "## Why",
                "- Enforce deterministic finalize.",
                "## Compatibility Notes",
                "- Legacy behavior preserved.",
                "## Files Modified",
                "- .aiwf/bin/ai_workflow.py",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "self_validation.md").write_text(
        "\n".join(
            [
                "# Self Validation",
                "## Commands Run",
                "- python3 -m py_compile .aiwf/bin/ai_workflow.py",
                "## Results",
                "- PASS",
                "## Known Limitations",
                "- pytest unavailable.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "review_agent.md").write_text(
        "\n".join(
            [
                "# Agent Self Review",
                "Implementation reviewed.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (task_dir / "review_final.md").write_text(
        "\n".join(
            [
                "# Final Review",
                "## Review Scope",
                "- Scope checked.",
                "## Key Findings",
                "- No blocker.",
                "## Blocking Issues",
                "- None.",
                "## Decision",
                "- Ready.",
                "## Final Result",
                "PASS",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _set_index_status_for_task(task_dir: Path, status_value: str) -> None:
    index_path = task_dir.parent / "index.md"
    lines = index_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if f"`{task_dir.name}`" in line:
            lines[i] = re.sub(
                r"(\|\s*status:\s*)([^|]+)",
                rf"\1{status_value}",
                line,
                count=1,
            )
            index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise AssertionError(f"task entry not found in {index_path}")


def _task_index_line(task_dir: Path) -> str:
    index_path = task_dir.parent / "index.md"
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if f"`{task_dir.name}`" in line:
            return line
    raise AssertionError(f"task entry not found in {index_path}")


def _sync_index(root: Path, task_dir: Path) -> None:
    rc = ai_workflow.sync_index_command(root, str(task_dir))
    assert rc == 0


def _record_v16_finalize_evidence(root: Path, task_dir: Path) -> None:
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="review passed") == 0


def _prepare_finalize_ready_task(root: Path, task_dir: Path) -> None:
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)


def test_new_task_defaults_to_v16(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    task_md_path = task_dir / "task.md"
    metadata, _body = ai_workflow.parse_front_matter(task_md_path.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == "ai-workflow-v1.6"
    assert metadata["task_id"] == "001"
    assert metadata["task_name"] == "fix_ddf_cleanup"
    assert metadata["status"] == "draft"
    assert metadata["priority"] == "P1"
    assert metadata["risk"] == "medium"
    assert metadata["owner"] == "ai-agent"
    assert metadata["reviewer"] == "human"
    assert metadata["review_status"] == "pending"
    assert metadata["blocked_reason"] is None
    assert metadata["workflow_phase"] == "implementation"
    assert metadata["phase_entered_at"]
    assert metadata["finalized_at"] is None
    assert metadata["finalized_by"] is None
    assert metadata["review_not_required_reason"] is None
    assert metadata["created_at"] == "2026-05-08"
    assert metadata["updated_at"] == "2026-05-08"


def test_default_task_metadata_uses_neutral_owner_reviewer_roles():
    metadata = ai_workflow.default_task_metadata(
        task_id="001",
        task_name="owner_reviewer_default_sample",
        title="owner reviewer default sample",
        date="20260605",
    )
    assert metadata["owner"] == "ai-agent"
    assert metadata["reviewer"] == "human"
    assert metadata["owner"] != "codex"


def test_new_task_writes_canonical_reference_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "metadata_writer_sample",
        "20260601",
        update_existing=False,
        parent_task="1",
        related_tasks=["014", "15", "016_sample_task"],
        blocked_by=["7"],
        supersedes=["008"],
        tags=["raw_disk", "smartctl"],
        related_files=["examples/test_raw_disk.py"],
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260601" / "001_metadata_writer_sample"
    meta = ai_workflow.load_task_metadata(task_dir)["metadata"]
    assert meta["owner"] == "ai-agent"
    assert meta["reviewer"] == "human"
    assert meta["parent_task"] == "001"
    assert meta["related_tasks"] == ["014", "015", "016"]
    assert meta["blocked_by"] == ["007"]
    assert meta["supersedes"] == ["008"]
    assert meta["tags"] == ["raw_disk", "smartctl"]
    assert meta["related_files"] == ["examples/test_raw_disk.py"]


def test_metadata_validation_blocks_malformed_related_tasks(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "bad_related_tasks",
        "20260601",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260601" / "001_bad_related_tasks"
    _rewrite_task_metadata(task_dir / "task.md", related_tasks=['\\"014\\"'])
    diagnostics = ai_workflow.validate_task_metadata(root, task_dir, ai_workflow.load_task_metadata(task_dir))
    assert any(d.code == "AIWF-META-009" and d.blocker for d in diagnostics)


def test_metadata_validation_blocks_malformed_parent_task(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "bad_parent_task",
        "20260601",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260601" / "001_bad_parent_task"
    _rewrite_task_metadata(task_dir / "task.md", parent_task="014_bad_name")
    diagnostics = ai_workflow.validate_task_metadata(root, task_dir, ai_workflow.load_task_metadata(task_dir))
    assert any(d.code == "AIWF-META-010" and d.blocker for d in diagnostics)


def test_metadata_validation_keeps_historical_codex_owner_reviewer_compatible(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "historical_codex_compatible_sample",
        "20260605",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260605" / "001_historical_codex_compatible_sample"
    metadata = ai_workflow.load_task_metadata(task_dir)["metadata"]
    metadata["owner"] = "codex"
    metadata["reviewer"] = "codex"
    ai_workflow._rewrite_task_metadata_file(task_dir, metadata)
    diagnostics = ai_workflow.validate_task_metadata(root, task_dir, ai_workflow.load_task_metadata(task_dir))
    assert not any(d.blocker and d.code.startswith("AIWF-META") for d in diagnostics)


def test_metadata_validation_blocks_absolute_related_file(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "bad_related_file",
        "20260601",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260601" / "001_bad_related_file"
    _rewrite_task_metadata(task_dir / "task.md", related_files=["/etc/passwd"])
    diagnostics = ai_workflow.validate_task_metadata(root, task_dir, ai_workflow.load_task_metadata(task_dir))
    assert any(d.code == "AIWF-META-011" and d.blocker for d in diagnostics)


def test_metadata_validation_blocks_parent_traversal_related_file(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "bad_related_file_parent",
        "20260601",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260601" / "001_bad_related_file_parent"
    _rewrite_task_metadata(task_dir / "task.md", related_files=["../secret.txt"])
    diagnostics = ai_workflow.validate_task_metadata(root, task_dir, ai_workflow.load_task_metadata(task_dir))
    assert any(d.code == "AIWF-META-011" and d.blocker for d in diagnostics)


def test_new_task_rejects_non_today_date_without_override(tmp_path: Path, monkeypatch):
    root = _init_repo(tmp_path)
    monkeypatch.setattr(ai_workflow, "today", lambda: "20260601")
    rc = ai_workflow.create_task(
        root,
        "wrong_year_task",
        "20250601",
        update_existing=False,
    )
    assert rc == 2
    assert not (root / "docs" / "ai_20250601").exists()


def test_new_task_allows_non_today_date_with_override(tmp_path: Path, monkeypatch):
    root = _init_repo(tmp_path)
    monkeypatch.setattr(ai_workflow, "today", lambda: "20260601")
    rc = ai_workflow.create_task(
        root,
        "historical_task",
        "20250601",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    assert (root / "docs" / "ai_20250601").exists()


def test_next_id_rejects_invalid_date_format(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.next_id_command(root, "2026-06-15")
    out = capsys.readouterr().out

    assert rc == 2
    assert "[ERROR] AIWF-DATE-002" in out
    assert "Invalid date format: 2026-06-15" in out
    assert "Use YYYYMMDD format" in out


@pytest.mark.parametrize("invalid_date", ["20260230", "20261301"])
def test_next_id_rejects_invalid_calendar_date(tmp_path: Path, capsys, invalid_date: str):
    root = _init_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.next_id_command(root, invalid_date)
    out = capsys.readouterr().out

    assert rc == 2
    assert "[ERROR] AIWF-DATE-003" in out
    assert f"Invalid date value: {invalid_date}" in out
    assert "valid calendar date" in out


def test_list_rejects_invalid_date_format(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.list_command(root, status=None, review_status=None, workflow_phase=None, date="2026/06/15")
    out = capsys.readouterr().out

    assert rc == 2
    assert "[ERROR] AIWF-DATE-002" in out
    assert "Invalid date format: 2026/06/15" in out
    assert "task_id | status | workflow_phase | review_status | task_name" not in out


def test_new_task_rejects_invalid_calendar_date(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.create_task(
        root,
        "calendar_bad_task",
        "20260230",
        update_existing=False,
        allow_non_today_date=True,
    )
    out = capsys.readouterr().out

    assert rc == 2
    assert "[ERROR] AIWF-DATE-003" in out
    assert "Invalid new-task date value: 20260230" in out
    assert not (root / "docs" / "ai_20260230").exists()


def test_backfill_rejects_invalid_date_format(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    target = _seed_backfill_target(root)

    capsys.readouterr()
    rc = ai_workflow.backfill(root, str(target), "2026-05-01", update_existing=False, no_decision=True)
    out = capsys.readouterr().out

    assert rc == 2
    assert "[ERROR] AIWF-DATE-002" in out
    assert "Invalid date format: 2026-05-01" in out
    assert not (root / "docs" / "ai_2026-05-01").exists()


def test_backfill_allows_non_today_date(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    target = _seed_backfill_target(root)

    capsys.readouterr()
    rc = ai_workflow.backfill(root, str(target), "20260501", update_existing=False, no_decision=True)
    out = capsys.readouterr().out

    assert rc == 0
    assert "Current execution record:" in out
    assert (target / "task.md").exists()
    assert (target / "agent.md").exists()
    assert (root / "docs" / "ai_20260501" / "002_backfill_docs_ai_20260501_001_legacy_task" / "task.md").exists()


def test_new_task_rejects_bad_reference_input(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "bad_ref_input",
        "20260601",
        update_existing=False,
        related_tasks=['\\"014\\"'],
        allow_non_today_date=True,
    )
    assert rc == 2
    assert not (root / "docs" / "ai_20260601" / "001_bad_ref_input").exists()


def test_new_task_rolls_back_directory_when_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _init_repo(tmp_path)
    original_write_file = ai_workflow.write_file

    def fail_after_first_file(root_arg: Path, path: Path, content: str, update_existing: bool = False):
        result = original_write_file(root_arg, path, content, update_existing)
        if path.name == "task.md":
            raise RuntimeError("simulated task creation failure")
        return result

    monkeypatch.setattr(ai_workflow, "write_file", fail_after_first_file)

    with pytest.raises(RuntimeError, match="simulated task creation failure"):
        ai_workflow.create_task(root, "interrupted_task", "20260602", update_existing=False, allow_non_today_date=True)

    assert not (root / "docs" / "ai_20260602" / "001_interrupted_task").exists()


def test_new_task_rolls_back_directory_and_index_when_append_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _init_repo(tmp_path)
    original_append_index = ai_workflow.append_index

    def fail_after_index_write(index_path: Path, entry: str):
        result = original_append_index(index_path, entry)
        raise RuntimeError("simulated index failure")

    monkeypatch.setattr(ai_workflow, "append_index", fail_after_index_write)

    with pytest.raises(RuntimeError, match="simulated index failure"):
        ai_workflow.create_task(root, "late_failure_task", "20260602", update_existing=False, allow_non_today_date=True)

    index_path = root / "docs" / "ai_20260602" / "index.md"
    assert not (root / "docs" / "ai_20260602" / "001_late_failure_task").exists()
    assert not index_path.exists()


def test_new_task_update_existing_fails_closed_without_writes(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "new_task",
        "20260602",
        update_existing=True,
        allow_non_today_date=True,
    )

    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-NEW-TASK-001" in out
    assert "No files were written." in out
    assert not (root / "docs" / "ai_20260602").exists()


def test_new_task_cli_dispatch_update_existing_fails_closed_without_writes(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    day_dir = root / "docs" / f"ai_{ai_workflow.today()}"

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "new-task",
            "sample_task",
            "--update-existing",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-NEW-TASK-001" in out
    assert "new-task is create-only" in out
    assert not day_dir.exists()
    assert not (day_dir / "index.md").exists()


def test_new_task_duplicate_normalized_name_fails_before_allocation(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    existing_task = _create_task(root, name="Same Task", date="20260602")
    day_dir = existing_task.parent
    before_index = (day_dir / "index.md").read_text(encoding="utf-8")
    before_dirs = sorted(path.name for path in day_dir.iterdir())

    rc = ai_workflow.create_task(
        root,
        "same-task",
        "20260602",
        update_existing=False,
        allow_non_today_date=True,
    )

    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-TASK-NAME-001" in out
    assert str(existing_task.relative_to(root)) in out
    assert "002_same_task" not in out
    assert sorted(path.name for path in day_dir.iterdir()) == before_dirs
    assert (day_dir / "index.md").read_text(encoding="utf-8") == before_index


def test_new_task_same_name_is_allowed_on_a_different_date(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, name="same_task", date="20260602")

    rc = ai_workflow.create_task(
        root,
        "same-task",
        "20260603",
        update_existing=False,
        allow_non_today_date=True,
    )

    assert rc == 0
    assert (root / "docs" / "ai_20260603" / "001_same_task").exists()


def test_check_doctor_and_finalize_block_preexisting_duplicate_task_names(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    canonical = _create_task(root, name="canonical_task", date="20260602")
    other = _create_task(root, name="other_task", date="20260602")
    duplicate = other.with_name("002_canonical_task")
    other.rename(duplicate)

    rc = ai_workflow.check_path(root, str(canonical), strict=False)
    check_out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-TASK-NAME-001" in check_out
    assert str(canonical.relative_to(root)) in check_out
    assert str(duplicate.relative_to(root)) in check_out

    rc = ai_workflow.doctor_command(root, str(canonical))
    doctor_out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-TASK-NAME-001" in doctor_out

    rc = ai_workflow.finalize_command(root, str(canonical))
    finalize_out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-TASK-NAME-001" in finalize_out


def test_new_task_keyboard_interrupt_leaves_no_orphan_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _init_repo(tmp_path)

    def interrupt_after_directory_create(root_arg: Path, path: Path, _content: str, _update_existing: bool = False):
        ai_workflow.safe_write_path(root_arg, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raise KeyboardInterrupt()

    monkeypatch.setattr(ai_workflow, "write_file", interrupt_after_directory_create)

    with pytest.raises(KeyboardInterrupt):
        ai_workflow.create_task(root, "keyboard_interrupt_task", "20260602", update_existing=False, allow_non_today_date=True)

    assert not (root / "docs" / "ai_20260602" / "001_keyboard_interrupt_task").exists()


def test_check_passes_for_valid_v16_task(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_check_fails_for_invalid_status(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", status="not_allowed")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_check_fails_for_task_id_mismatch(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", task_id="999")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_check_warns_for_legacy_task_without_metadata(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    text = (task_dir / "task.md").read_text(encoding="utf-8")
    _metadata, body = ai_workflow.parse_front_matter(text)
    (task_dir / "task.md").write_text(body.lstrip("\n"), encoding="utf-8")

    capsys.readouterr()
    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" in captured.out
    assert "legacy task without metadata front matter" in captured.out.lower()


def test_valid_pending_review_status_with_draft_passes(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", status="draft", review_status="pending")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_done_with_pending_review_status_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", status="done", review_status="pending")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_done_with_fail_review_status_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", status="done", review_status="fail")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_done_with_pass_review_status_passes(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        schema_version="ai-workflow-v1.5",
        status="done",
        review_status="pass",
        workflow_phase="finalized",
        finalized_at="2026-05-11T00:00:00Z",
        finalized_by="tool",
    )
    _sync_index(root, task_dir)

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_done_with_not_required_review_status_passes(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        schema_version="ai-workflow-v1.5",
        status="done",
        review_status="not_required",
        workflow_phase="finalized",
        finalized_at="2026-05-11T00:00:00Z",
        finalized_by="tool",
    )
    _sync_index(root, task_dir)

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_blocked_with_empty_blocked_by_and_null_reason_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        status="blocked",
        blocked_by=[],
        blocked_reason=None,
    )

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_blocked_with_non_empty_reason_passes(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        status="blocked",
        blocked_by=[],
        blocked_reason="waiting for pytest environment",
    )
    _sync_index(root, task_dir)

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_invalid_task_name_with_hyphen_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", task_name="fix-ddf-cleanup")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_invalid_task_name_with_uppercase_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", task_name="Fix_DDF_Cleanup")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_valid_snake_case_task_name_passes(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", task_name="fix_ddf_cleanup")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_export_json_returns_valid_v16_task(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    payload = ai_workflow.export_tasks_json(root, task_dir)
    assert payload["schema_version"] == "ai-workflow-v1.6"
    assert payload["workflow_version"] == ai_workflow.WORKFLOW_PROTOCOL_VERSION
    assert payload["capabilities"]["deterministic_finalize"] is True
    assert payload["capabilities"]["finalize_idempotent"] is True
    assert len(payload["tasks"]) == 1
    task = payload["tasks"][0]
    assert task["task_id"] == "001"
    assert task["task_name"] == "fix_ddf_cleanup"
    assert task["schema_version"] == "ai-workflow-v1.6"
    assert task["metadata_valid"] is True
    assert task["review_status"] == "pending"
    assert task["blocked_reason"] is None
    assert task["workflow_phase"] == "implementation"
    assert task["finalized_at"] is None
    assert task["finalized_by"] is None


def test_export_json_handles_legacy_task_without_failing(tmp_path: Path):
    root = _init_repo(tmp_path)
    day_dir = root / "docs" / "ai_20260508"
    task_dir = day_dir / "001_fix_ddf_cleanup"
    task_dir.mkdir(parents=True)
    (task_dir / "task.md").write_text("# legacy task\n", encoding="utf-8")
    for name in ["agent.md", "task_record.md", "self_validation.md", "review_codex.md", "review_final.md"]:
        (task_dir / name).write_text("ok\n", encoding="utf-8")

    payload = ai_workflow.export_tasks_json(root, day_dir)
    assert payload["schema_version"] == "ai-workflow-v1.6"
    assert len(payload["tasks"]) == 1
    task = payload["tasks"][0]
    assert task["schema_version"] == "legacy"
    assert task["metadata_valid"] is False
    assert task["task_id"] == "001"
    assert task["task_name"] == "fix_ddf_cleanup"


def test_relocate_dry_run_changes_nothing(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _seed_legacy_relocation_layout(root)
    tracked_files = [
        root / "docs" / "workflow_protocol.md",
        root / "docs" / "diagnostics.md",
        root / "docs" / "repo_boundary.md",
        root / "docs" / "adoption_guide.md",
        root / "docs" / "reporting.md",
        root / "docs" / "agent_integration.md",
        root / "docs" / "metadata.md",
        root / "docs" / "packaging.md",
        root / "docs" / "agent_rules" / "00_index.md",
        root / "docs" / "agent_rules" / "templates" / "task.md",
        root / "docs" / "releases" / "v1.0.md",
        root / "docs" / "examples" / "basic_lifecycle.md",
        root / "docs" / "examples" / "ci" / "gitlab-aiwf-minimal.yml",
        root / "docs" / "knowledge" / "README.md",
        root / "docs" / "knowledge" / "bugs" / "README.md",
        task_dir / "task.md",
        task_dir / "task_record.md",
        task_dir / "self_validation.md",
        task_dir / "review_codex.md",
        task_dir / "review_final.md",
        root / "tools" / "ai_workflow.py",
    ]
    before = _snapshot_text_files(tracked_files)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-DRY-RUN" in out
    assert "Legacy docs migration disabled by default" in out
    assert not (root / ".aiwf").exists()
    _assert_text_files_unchanged(before)


def test_relocate_apply_preserves_project_docs_by_default(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _seed_legacy_relocation_layout(root)
    project_docs = [
        root / "docs" / "workflow_protocol.md",
        root / "docs" / "metadata.md",
        root / "docs" / "releases" / "v1.0.md",
        root / "docs" / "examples" / "basic_lifecycle.md",
        root / "docs" / "knowledge" / "README.md",
        root / "docs" / "ai_20260610" / "001_legacy_task" / "task.md",
    ]
    before = _snapshot_text_files(project_docs)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-OK" in out
    assert "legacy docs migration skipped by default" in out
    _assert_text_files_unchanged(before)
    assert not (root / ".aiwf" / "docs" / "workflow_protocol.md").exists()
    assert not (root / ".aiwf" / "records" / "ai_20260610").exists()


def test_relocate_legacy_docs_apply_moves_aiwf_docs(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _seed_legacy_relocation_layout(root)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--legacy-docs", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-OK" in out
    assert (root / ".aiwf" / "docs" / "workflow_protocol.md").exists()
    assert (root / ".aiwf" / "docs" / "diagnostics.md").exists()
    assert (root / ".aiwf" / "docs" / "repo_boundary.md").exists()
    assert (root / ".aiwf" / "docs" / "adoption_guide.md").exists()
    assert (root / ".aiwf" / "docs" / "reporting.md").exists()
    assert (root / ".aiwf" / "docs" / "agent_integration.md").exists()
    assert (root / ".aiwf" / "docs" / "metadata.md").exists()
    assert (root / ".aiwf" / "docs" / "packaging.md").exists()
    assert (root / ".aiwf" / "docs" / "agent_rules" / "00_index.md").exists()
    assert (root / ".aiwf" / "docs" / "agent_rules" / "templates" / "task.md").exists()
    assert (root / ".aiwf" / "docs" / "releases" / "v1.0.md").exists()
    assert (root / ".aiwf" / "docs" / "examples" / "basic_lifecycle.md").exists()
    assert (root / ".aiwf" / "docs" / "examples" / "ci" / "gitlab-aiwf-minimal.yml").exists()
    assert (root / ".aiwf" / "docs" / "knowledge" / "README.md").exists()
    assert (root / ".aiwf" / "docs" / "knowledge" / "bugs" / "README.md").exists()
    assert not (root / "docs" / "workflow_protocol.md").exists()
    assert not (root / "docs" / "adoption_guide.md").exists()
    assert not (root / "docs" / "reporting.md").exists()
    assert not (root / "docs" / "agent_integration.md").exists()
    assert not (root / "docs" / "metadata.md").exists()
    assert not (root / "docs" / "packaging.md").exists()
    assert not (root / "docs" / "agent_rules").exists()
    assert not (root / "docs" / "releases").exists()
    assert not (root / "docs" / "examples").exists()
    assert not (root / "docs" / "knowledge").exists()


def test_relocate_legacy_docs_apply_moves_aiwf_records(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _seed_legacy_relocation_layout(root)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--legacy-docs", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-OK" in out
    relocated_task_dir = root / ".aiwf" / "records" / "ai_20260610" / task_dir.name
    assert relocated_task_dir.exists()
    assert (relocated_task_dir / "task.md").exists()
    assert not (root / "docs" / "ai_20260610").exists()
    report_dir = root / ".aiwf" / "migrations"
    assert any(report_dir.glob("*_repo_boundary_relocation.md"))


def test_relocate_apply_preserves_legacy_tools_runtime(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _seed_legacy_relocation_layout(root)
    legacy_runtime = root / "tools" / "ai_workflow.py"
    before = legacy_runtime.read_text(encoding="utf-8")

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-OK" in out
    assert not (root / ".aiwf" / "bin" / "ai_workflow.py").exists()
    assert legacy_runtime.read_text(encoding="utf-8") == before


def test_relocate_apply_ignores_project_scripts_by_default(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _seed_legacy_relocation_layout(root)
    project_script = root / "scripts" / "project_build.sh"
    project_script.parent.mkdir(parents=True)
    project_script.write_text("#!/usr/bin/env bash\necho project\n", encoding="utf-8")
    before = _snapshot_text_files([project_script])

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-OK" in out
    assert "scripts/project_build.sh" not in out
    _assert_text_files_unchanged(before)
    assert not (root / REMOVED_ROOT_PACKAGE_HELPER).exists()
    assert not (root / ".aiwf" / "scripts").exists()


def test_relocate_apply_writes_config(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _seed_legacy_relocation_layout(root)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-OK" in out
    config_path = root / ".aiwf" / "config.yaml"
    assert config_path.exists()
    config_text = config_path.read_text(encoding="utf-8")
    assert 'aiwf_layout_version: 2' in config_text
    assert 'docs_root: ".aiwf/docs"' in config_text
    assert 'record_root: ".aiwf/records"' in config_text
    assert 'event_log: ".aiwf/events/events.jsonl"' in config_text
    assert "legacy_enabled: true" in config_text
    assert (root / ".aiwf" / "events" / "events.jsonl").exists()


def test_upgrade_check_legacy_repo_does_not_relocate_tools_runtime(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-CHECK" in out
    assert "Current:" in out
    assert "tool_version: 1.7.5.post5" in out
    assert "Target:" in out
    assert f"tool_version: {ai_workflow.AIWF_TOOL_VERSION}" in out
    assert "upgrade_required: yes" in out
    assert "relocation_required: no" in out
    assert "Will update:" in out
    assert "legacy docs migration disabled by default" in out
    assert "  - tools/ai_workflow.py" not in out
    assert "legacy tools/ai_workflow.py exists and is project-owned" in out
    assert "tools/ai_workflow.py -> .aiwf/bin/ai_workflow.py" not in out
    assert "blockers: none" in out
    assert "./aiwf upgrade --dry-run --source" in out


def test_upgrade_check_current_v2_repo_no_upgrade_needed(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-CHECK" in out
    assert f"tool_version: {ai_workflow.AIWF_TOOL_VERSION}" in out
    assert "upgrade_required: no" in out
    assert "repair_required: no" in out
    assert "relocation_required: no" in out
    assert "blockers: none" in out
    assert "Will update:\n  - none" in out


def test_upgrade_check_current_v2_repo_no_relocation_needed(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "relocation_required: no" in out


def test_upgrade_dry_run_legacy_repo_does_not_relocate_tools_runtime(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)
    tracked_files = [
        root / "aiwf",
        root / "tools" / "ai_workflow.py",
        root / "docs" / "workflow_protocol.md",
        root / "docs" / "adoption_guide.md",
        root / "docs" / "agent_rules" / "00_index.md",
        root / "docs" / "releases" / "v1.0.md",
        root / "docs" / "examples" / "basic_lifecycle.md",
        root / "docs" / "knowledge" / "README.md",
        root / "docs" / "ai_20260610" / "001_legacy_task" / "task.md",
        root / ".aiwf" / "config.yaml",
    ]
    before = _snapshot_text_files(tracked_files)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--dry-run", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-DRY-RUN" in out
    assert "legacy docs migration disabled by default" in out
    assert "  - tools/ai_workflow.py" not in out
    assert "legacy tools/ai_workflow.py exists and is project-owned" in out
    assert "tools/ai_workflow.py -> .aiwf/bin/ai_workflow.py" not in out
    assert "No files changed." in out
    assert not (root / ".aiwf" / "bin").exists()
    assert not (root / ".aiwf" / "migrations").exists()
    _assert_text_files_unchanged(before)


def test_upgrade_apply_preserves_project_docs_by_default(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)
    legacy_tools = root / "tools" / "ai_workflow.py"
    legacy_tools_before = legacy_tools.read_text(encoding="utf-8")
    project_docs = [
        root / "docs" / "workflow_protocol.md",
        root / "docs" / "adoption_guide.md",
        root / "docs" / "agent_rules" / "00_index.md",
        root / "docs" / "releases" / "v1.0.md",
        root / "docs" / "examples" / "basic_lifecycle.md",
        root / "docs" / "knowledge" / "README.md",
        root / "docs" / "ai_20260610" / "001_legacy_task" / "task.md",
    ]
    docs_before = _snapshot_text_files(project_docs)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--apply", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-OK" in out
    assert "Report:" in out
    runtime_text = (root / ".aiwf" / "bin" / "ai_workflow.py").read_text(encoding="utf-8")
    assert f'AIWF_TOOL_VERSION = "{ai_workflow.AIWF_TOOL_VERSION}"' in runtime_text
    assert (root / ".aiwf" / "docs" / "workflow_protocol.md").exists()
    assert (root / ".aiwf" / "bin" / "safe_paths.py").exists()
    assert (root / ".aiwf" / "bin" / "lib" / "package_core.py").exists()
    assert (root / ".aiwf" / "templates" / "AGENTS.block.md").exists()
    assert (root / ".aiwf" / "docs" / "adoption_guide.md").exists()
    assert (root / ".aiwf" / "docs" / "agent_rules" / "00_index.md").exists()
    assert (root / ".aiwf" / "docs" / "examples" / "basic_lifecycle.md").exists()
    if (REPO_ROOT / ".aiwf" / "docs" / "knowledge" / "README.md").exists():
        assert (root / ".aiwf" / "docs" / "knowledge" / "README.md").exists()
    assert not (root / ".aiwf" / "records" / "ai_20260610" / "001_legacy_task" / "task.md").exists()
    assert legacy_tools.read_text(encoding="utf-8") == legacy_tools_before
    assert "legacy tools/ai_workflow.py exists and is project-owned" in out
    assert "legacy docs migration is disabled by default" in out
    _assert_text_files_unchanged(docs_before)
    config_text = (root / ".aiwf" / "config.yaml").read_text(encoding="utf-8")
    assert 'aiwf_layout_version: 2' in config_text
    assert 'project_note: keep-me' in config_text
    assert 'legacy_enabled: true' in config_text
    report_paths = sorted((root / ".aiwf" / "migrations").glob("*_upgrade.md"))
    assert report_paths
    report_text = report_paths[0].read_text(encoding="utf-8")
    assert "# AIWF Upgrade Report" in report_text
    assert f"source_tool_version: {ai_workflow.AIWF_TOOL_VERSION}" in report_text
    assert "validation result" in report_text.lower()
    assert "- .aiwf/bin" in report_text
    assert "- .aiwf/templates" in report_text

    help_result = subprocess.run([str(root / "aiwf"), "--help"], cwd=root, text=True, capture_output=True, check=False)
    assert help_result.returncode == 0


def test_upgrade_apply_preserves_project_scripts_and_does_not_create_removed_helper(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)
    project_script = root / "scripts" / "project_build.sh"
    project_script.parent.mkdir(parents=True)
    project_script.write_text("#!/usr/bin/env bash\necho project\n", encoding="utf-8")
    before = _snapshot_text_files([project_script])

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--apply", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-OK" in out
    assert "scripts/project_build.sh" not in out
    _assert_text_files_unchanged(before)
    assert not (root / REMOVED_ROOT_PACKAGE_HELPER).exists()
    report_paths = sorted((root / ".aiwf" / "migrations").glob("*_upgrade.md"))
    assert report_paths
    report_text = report_paths[0].read_text(encoding="utf-8")
    assert "scripts/project_build.sh" not in report_text


def test_upgrade_apply_migrate_legacy_docs_moves_reviewed_docs(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.main(
        ["--repo-root", str(root), "upgrade", "--apply", "--migrate-legacy-docs", "--source", str(REPO_ROOT)]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-OK" in out
    assert (root / ".aiwf" / "docs" / "workflow_protocol.md").exists()
    assert (root / ".aiwf" / "records" / "ai_20260610" / "001_legacy_task" / "task.md").exists()
    assert not (root / "docs" / "workflow_protocol.md").exists()
    assert not (root / "docs" / "ai_20260610").exists()


def test_upgrade_apply_no_relocate_keeps_legacy_layout(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)

    capsys.readouterr()
    rc = ai_workflow.main(
        ["--repo-root", str(root), "upgrade", "--apply", "--no-relocate", "--source", str(REPO_ROOT)]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "legacy layout relocation skipped by --no-relocate" in out
    assert (root / "docs" / "workflow_protocol.md").exists()
    assert (root / "docs" / "ai_20260610" / "001_legacy_task" / "task.md").exists()
    assert (root / ".aiwf" / "bin" / "ai_workflow.py").exists()


def test_relocate_ignores_tools_shim_when_runtime_exists(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path, with_legacy_docs=True)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "relocate", "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "AIWF-RELOCATE-DRY-RUN" in out
    assert "tools/ai_workflow.py" not in out
    assert (root / ".aiwf" / "bin" / "ai_workflow.py").exists()
    assert (root / "tools" / "ai_workflow.py").exists()


def test_upgrade_check_rejects_missing_source_runtime(tmp_path: Path, capsys):
    root = _seed_upgrade_target_repo(tmp_path)
    bad_source = tmp_path / "bad_source"
    bad_source.mkdir()
    (bad_source / "aiwf").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bad_source / "aiwf").chmod(0o755)
    (bad_source / ".aiwf" / "docs").mkdir(parents=True, exist_ok=True)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(bad_source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "missing required source package path: .aiwf/bin/ai_workflow.py" in out


def test_upgrade_check_rejects_missing_source_safe_paths(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    (source / ".aiwf" / "bin" / "safe_paths.py").unlink()

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "blockers: 1" in out
    assert "missing required source package path: .aiwf/bin/safe_paths.py" in out


def test_upgrade_check_rejects_missing_source_lib(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    shutil.rmtree(source / ".aiwf" / "bin" / "lib")

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "blockers: 2" in out
    assert "missing required source package path: .aiwf/bin/lib" in out
    assert "missing required source package path: .aiwf/bin/lib/package_core.py" in out


def test_upgrade_check_rejects_missing_source_package_core(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    (source / ".aiwf" / "bin" / "lib" / "package_core.py").unlink()

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "blockers: 1" in out
    assert "missing required source package path: .aiwf/bin/lib/package_core.py" in out


def test_upgrade_check_rejects_missing_source_agents_template(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    (source / ".aiwf" / "templates" / "AGENTS.block.md").unlink()

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "blockers: 1" in out
    assert "missing required source package path: .aiwf/templates/AGENTS.block.md" in out


def test_upgrade_check_same_version_missing_runtime_dependency_requires_repair(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path)
    (root / ".aiwf" / "bin" / "safe_paths.py").unlink()

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "upgrade_required: yes" in out
    assert "repair_required: yes" in out
    assert "Will update:\n  - .aiwf/bin/**" in out
    assert "Next:\n  none" not in out


def test_upgrade_check_same_version_missing_package_core_requires_repair(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path)
    (root / ".aiwf" / "bin" / "lib" / "package_core.py").unlink()

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "upgrade_required: yes" in out
    assert "repair_required: yes" in out
    assert "Will update:\n  - .aiwf/bin/**" in out
    assert "upgrade_required: no\n  repair_required: no" not in out
    assert "Next:\n  none" not in out


def test_upgrade_check_same_version_missing_template_requires_repair(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path)
    (root / ".aiwf" / "templates" / "AGENTS.block.md").unlink()

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "upgrade_required: yes" in out
    assert "repair_required: yes" in out
    assert "Will update:\n  - .aiwf/templates/**" in out


def test_upgrade_apply_same_version_repairs_missing_runtime_and_template(tmp_path: Path, capsys):
    root = _seed_current_v2_repo(tmp_path)
    (root / ".aiwf" / "bin" / "safe_paths.py").unlink()
    shutil.rmtree(root / ".aiwf" / "bin" / "lib")
    shutil.rmtree(root / ".aiwf" / "templates")

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--apply", "--source", str(REPO_ROOT)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[INFO] AIWF-UPGRADE-OK" in out
    assert (root / ".aiwf" / "bin" / "safe_paths.py").exists()
    assert (root / ".aiwf" / "bin" / "lib" / "package_core.py").exists()
    assert (root / ".aiwf" / "templates" / "AGENTS.block.md").exists()
    assert "- installed .aiwf/bin" in out
    assert "- installed .aiwf/templates" in out


def test_upgrade_check_rejects_source_runtime_symlink(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    runtime = source / ".aiwf" / "bin" / "ai_workflow.py"
    real_runtime = source / "real_runtime.py"
    real_runtime.write_text(runtime.read_text(encoding="utf-8"), encoding="utf-8")
    runtime.unlink()
    _symlink_or_skip(runtime, real_runtime)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "source package member must not be a symlink: .aiwf/bin/ai_workflow.py" in out


def test_upgrade_check_rejects_source_docs_symlink(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    docs = source / ".aiwf" / "docs"
    real_docs = source / "real_docs"
    shutil.rmtree(docs)
    real_docs.mkdir()
    (real_docs / "workflow_protocol.md").write_text("protocol\n", encoding="utf-8")
    _symlink_or_skip(docs, real_docs, target_is_directory=True)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "source package member must not be a symlink: .aiwf/docs" in out


def test_upgrade_check_rejects_nested_source_docs_symlink(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")
    private_doc = tmp_path / "private_doc.md"
    private_doc.write_text("private\n", encoding="utf-8")
    _symlink_or_skip(source / ".aiwf" / "docs" / "linked.md", private_doc)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "source package tree must not contain symlinks: .aiwf/docs/linked.md" in out


def test_upgrade_check_normal_minimal_source_without_symlinks_still_succeeds(tmp_path: Path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    root = _seed_upgrade_target_repo(target)
    source = _seed_minimal_upgrade_source(tmp_path / "source")

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "upgrade", "--check", "--source", str(source)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "blockers: none" in out


def test_dataset_export_basic_schema_and_allowed_fields(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")

    payload = _run_dataset_export(root)
    assert payload["dataset_version"] == "1"
    assert payload["generated_at"]
    assert payload["records_root"] == "docs"
    assert payload["task_count"] == 1
    assert len(payload["tasks"]) == 1
    record = payload["tasks"][0]
    assert set(record.keys()) == set(ai_workflow.DATASET_ALLOWED_TASK_FIELDS)
    assert record["has_agent_review_artifact"] is True
    assert record["has_review_codex_artifact"] is False


def test_dataset_export_normalizes_legacy_review_codex_to_agent_review(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    (task_dir / "review_agent.md").rename(task_dir / "review_codex.md")

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]

    assert record["has_agent_review_artifact"] is True
    assert record["has_review_codex_artifact"] is True
    assert (task_dir / "review_codex.md").exists()
    assert not (task_dir / "review_agent.md").exists()


def test_dataset_export_missing_artifacts_is_tolerant(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    (task_dir / "review_final.md").unlink()
    (task_dir / "self_validation.md").unlink()

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["has_review_final_artifact"] is False
    assert record["has_self_validation_artifact"] is False


def test_dataset_export_missing_events_file_is_tolerant(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["event_count"] == 0
    assert record["event_types"] == []
    assert record["event_type_counts"] == {}


def test_dataset_export_event_type_counts_from_repo_level_log(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")
    _write_repo_event_log(
        root,
        '{"event":"validation","task_id":"001"}',
        '{"event":"review","task_id":"001"}',
        '{"event":"validation","task_id":"001"}',
    )

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["event_count"] == 3
    assert record["event_type_counts"] == {"review": 1, "validation": 2}
    assert record["has_validation_event"] is True
    assert record["has_review_event"] is True


def test_dataset_export_requires_deterministic_event_association(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")
    _write_repo_event_log(
        root,
        '{"event":"validation","task_id":"001"}',
        '{"event":"validation","message":"looks like task 001 but no explicit task field"}',
    )

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["event_count"] == 1
    assert any(w["code"] == "AIWF-DATASET-UNASSOCIATED-EVENTS" for w in record["export_warnings"])


def test_dataset_export_finalize_event_projection_without_analysis_fields(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")
    _write_repo_event_log(root, '{"event":"finalize_success","task_id":"001"}')

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["has_finalize_event"] is True
    for forbidden_field in (
        "phase",
        "finalized",
        "blocked",
        "failed",
        "review_hold_count",
        "has_rework",
        "rework_count",
        "closure_basis",
        "evidence_strength",
        "quality_score",
        "legacy_record",
    ):
        assert forbidden_field not in record


def test_dataset_export_relationship_counts_from_metadata_lists(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _rewrite_task_metadata(
        task_dir / "task.md",
        related_tasks=["002", "003"],
        blocked_by=["004"],
        supersedes=[],
    )

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["related_task_count"] == 2
    assert record["blocked_by_count"] == 1
    assert record["supersedes_count"] == 0


def test_dataset_export_invalid_relationship_field_warns(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _rewrite_task_metadata(task_dir / "task.md", related_tasks="002")

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["related_task_count"] == 0
    assert any(w["code"] == "AIWF-DATASET-INVALID-RELATIONSHIP-FIELD" for w in record["export_warnings"])


def test_dataset_export_invalid_event_json_warns_and_skips_line(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")
    _write_repo_event_log(
        root,
        '{"event":"validation","task_id":"001"}',
        '{broken-json}',
    )

    payload = _run_dataset_export(root)
    record = payload["tasks"][0]
    assert record["event_count"] == 1
    assert any(w["code"] == "AIWF-DATASET-INVALID-EVENT-JSON" for w in record["export_warnings"])


def test_dataset_export_does_not_modify_existing_files(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _write_repo_event_log(root, '{"event":"validation","task_id":"001"}')

    protected_paths = [
        task_dir / "task.md",
        task_dir / "task_record.md",
        task_dir / "self_validation.md",
        task_dir / "review_agent.md",
        task_dir / "review_final.md",
        root / ".aiwf" / "events" / "events.jsonl",
    ]
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected_paths
    }

    _run_dataset_export(root)

    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected_paths
    }
    assert before == after


def test_package_records_dry_run_manifest_required_fields_and_capabilities(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="core_selection", date="20260601")

    payload = _run_package_records_dry_run(root, "package_records_required.json")

    assert {
        "schema_version",
        "package_type",
        "package_version",
        "capabilities",
        "generator",
        "options",
        "redaction_profile",
        "redaction_count",
        "excluded_artifact_count",
        "records_root",
        "filters",
        "selected_tasks",
        "excluded_tasks",
        "artifacts",
        "events",
        "dataset",
        "redaction",
        "repository",
        "identity",
        "validation",
    }.issubset(payload)
    assert payload["schema_version"] == ai_workflow.AIWF_PACKAGE_RECORDS_MANIFEST_SCHEMA_VERSION
    assert payload["package_type"] == "aiwf-package-records"
    assert payload["capabilities"]["canonical_events"] is True
    assert payload["capabilities"]["referential_validation"] is True
    assert payload["capabilities"]["package_identity"] is True
    assert payload["capabilities"]["dataset"] is True
    assert payload["capabilities"]["redaction"] is True
    assert payload["options"]["redaction_profile"] == "safe"
    assert payload["redaction_profile"] == "safe"
    assert payload["redaction_count"] == 0
    assert payload["excluded_artifact_count"] == 0
    assert payload["redaction"] == {
        "excluded_artifact_count": 0,
        "exclusion_report": [],
        "profile": "safe",
        "redaction_count": 0,
        "redaction_report": [],
        "secret_finding_count": 0,
    }
    assert payload["options"]["include_dataset"] is True
    assert payload["dataset"] == {
        "included": True,
        "path": ai_workflow.AIWF_PACKAGE_RECORDS_DATASET_PATH,
        "schema_version": ai_workflow.AIWF_DATASET_SCHEMA_VERSION,
        "warning_count": 0,
    }
    assert payload["events"]["canonical_event_count"] == 0
    assert payload["identity"]["content_file_count"] == len(payload["artifacts"]["included"])
    assert payload["identity"]["content_total_bytes"] == sum(item["bytes"] for item in payload["artifacts"]["included"])
    assert payload["validation"]["scope"] == "workflow_evidence"
    assert payload["validation"]["package_generation"]["result"] == "pass"
    assert payload["validation"]["manifest_schema"]["result"] == "pass"
    assert payload["validation"]["package_integrity"]["result"] == "pass"
    assert payload["validation"]["privacy_security"]["result"] == "pass"
    assert payload["validation"]["workflow_evidence"]["result"] == payload["validation"]["result"]
    assert payload["validation"]["workflow_evidence"]["finding_count"] == payload["validation"]["finding_count"]
    task_md_artifact = next(item for item in payload["artifacts"]["included"] if item["package_path"].endswith("/task.md"))
    assert task_md_artifact["source_path"] == ai_workflow.rel(root, task_dir / "task.md")
    assert task_md_artifact["artifact_class"] == "task_content"
    assert task_md_artifact["mode"] == "100644"
    assert task_md_artifact["sha256"] == hashlib.sha256((task_dir / "task.md").read_bytes()).hexdigest()
    agent_review_artifact = next(item for item in payload["artifacts"]["included"] if item["package_path"].endswith("/review_agent.md"))
    assert agent_review_artifact["source_path"] == ai_workflow.rel(root, task_dir / "review_agent.md")
    assert agent_review_artifact["artifact_class"] == "agent_review"
    assert not any(item["package_path"].endswith("/review_codex.md") for item in payload["artifacts"]["included"])
    assert payload["selected_tasks"] == [
        {
            "task_id": "001",
            "task_name": "core_selection",
            "source_path": ai_workflow.rel(root, task_dir),
            "package_path": "records/ai_20260601/001_core_selection",
            "status": "draft",
            "workflow_phase": "implementation",
            "review_status": "pending",
        }
    ]


def test_package_records_includes_legacy_review_codex_when_canonical_absent(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="legacy_review_alias_task", date="20260601")
    (task_dir / "review_agent.md").rename(task_dir / "review_codex.md")

    payload = _run_package_records_dry_run(root, "package_records_legacy_review_alias.json")

    agent_review_artifact = next(item for item in payload["artifacts"]["included"] if item["package_path"].endswith("/review_codex.md"))
    assert agent_review_artifact["source_path"] == ai_workflow.rel(root, task_dir / "review_codex.md")
    assert agent_review_artifact["artifact_class"] == "agent_review"
    assert not any(item["package_path"].endswith("/review_agent.md") for item in payload["artifacts"]["included"])
    assert not (task_dir / "review_agent.md").exists()


def test_package_records_prefers_review_agent_when_legacy_alias_also_exists(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="duplicate_review_alias_task", date="20260601")
    legacy_path = task_dir / "review_codex.md"
    legacy_path.write_text("# Codex Self Review\nlegacy alias\n", encoding="utf-8")

    payload = _run_package_records_dry_run(root, "package_records_duplicate_review_alias.json")

    assert any(item["package_path"].endswith("/review_agent.md") and item["artifact_class"] == "agent_review" for item in payload["artifacts"]["included"])
    assert not any(item["package_path"].endswith("/review_codex.md") for item in payload["artifacts"]["included"])
    assert {
        "source_path": ai_workflow.rel(root, legacy_path),
        "reason": "legacy_duplicate_agent_review_alias",
    } in payload["artifacts"]["excluded"]


def test_package_records_generation_passes_with_workflow_evidence_warning(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="workflow_warning_task", date="20260601")
    _write_task_event_log(task_dir, {"timestamp": "not-a-timestamp", "event": "historical-warning"})

    payload = _run_package_records_dry_run(root, "package_records_workflow_warning.json")

    validation = payload["validation"]
    assert validation["package_generation"]["result"] == "pass"
    assert validation["manifest_schema"]["result"] == "pass"
    assert validation["package_integrity"]["result"] == "pass"
    assert validation["privacy_security"]["result"] == "pass"
    assert validation["workflow_evidence"]["result"] == "warn"
    assert validation["result"] == "warn"
    assert validation["workflow_evidence"]["finding_count"] == validation["finding_count"]
    assert any(item["code"] == "AIWF-PACKAGE-RECORDS-INVALID-EVENT-TIMESTAMP" for item in validation["findings"])


def test_package_records_cli_distinguishes_package_status_from_workflow_findings(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="cli_workflow_warning_task", date="20260601")
    _write_task_event_log(task_dir, {"timestamp": "not-a-timestamp", "event": "historical-warning"})
    output_path = root / "package_records_cli_warning.json"

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert output_path.exists()
    assert "Package Generation: PASS" in captured.out
    assert "Manifest Schema: PASS" in captured.out
    assert "Package Integrity: PASS" in captured.out
    assert "Privacy/Security: PASS" in captured.out
    assert "Workflow Evidence Findings: WARNING" in captured.out
    assert "Package validation failed" not in captured.out
    assert "Package validation failed" not in captured.err


def test_package_records_no_dataset_records_explicit_omission(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="dataset_omitted", date="20260601")

    payload = _run_package_records_dry_run(root, "package_records_no_dataset.json", ["--no-dataset"])

    assert payload["capabilities"]["dataset"] is False
    assert payload["options"]["include_dataset"] is False
    assert payload["dataset"] == {"included": False, "warning_count": 0}


def test_package_records_include_dataset_conflict_fails_closed(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="dataset_conflict", date="20260601")
    output_path = root / "package_records_dataset_conflict.json"

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
            "--include-dataset",
            "--no-dataset",
        ]
    )

    assert rc == 2
    assert not output_path.exists()


def test_package_records_dataset_warnings_are_propagated(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="dataset_warning_task", date="20260601")
    _rewrite_task_metadata(task_dir / "task.md", related_tasks="002")

    payload = _run_package_records_dry_run(root, "package_records_dataset_warning.json")

    assert payload["dataset"]["included"] is True
    assert payload["dataset"]["warning_count"] == 1
    assert any(
        item["code"] == "AIWF-PACKAGE-RECORDS-DATASET-WARNING"
        and "AIWF-DATASET-INVALID-RELATIONSHIP-FIELD" in item["message"]
        and item["path"] == ai_workflow.AIWF_PACKAGE_RECORDS_DATASET_PATH
        for item in payload["validation"]["findings"]
    )


def test_package_records_safe_profile_reports_redactions(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="safe_redaction_task", date="20260601")
    (task_dir / "task_record.md").write_text(
        "\n".join(
            [
                f"Internal service: {_redaction_fixture_internal_url()}",
                f"Local path: {_redaction_fixture_user_path()}",
                f"Private address: {_redaction_fixture_private_ip()}",
                "Host: build.local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = _run_package_records_dry_run(root, "package_records_safe_redaction.json", ["--redaction-profile", "safe"])

    assert payload["redaction_profile"] == "safe"
    assert payload["redaction"]["profile"] == "safe"
    assert payload["redaction_count"] >= 4
    assert payload["redaction"]["redaction_count"] == payload["redaction_count"]
    assert {item["rule"] for item in payload["redaction"]["redaction_report"]} >= {
        "absolute_path",
        "hostname",
        "internal_url",
        "private_ip",
    }
    assert payload["validation"]["result"] in {"pass", "warn"}


def test_package_records_internal_and_none_profiles_do_not_redact_internal_references(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="non_safe_redaction_task", date="20260601")
    (task_dir / "task_record.md").write_text(f"Internal service: {_redaction_fixture_internal_url()}\n", encoding="utf-8")

    internal_payload = _run_package_records_dry_run(
        root,
        "package_records_internal_redaction.json",
        ["--redaction-profile", "internal"],
    )
    none_payload = _run_package_records_dry_run(
        root,
        "package_records_none_redaction.json",
        ["--redaction-profile", "none"],
    )

    assert internal_payload["redaction_profile"] == "internal"
    assert internal_payload["redaction_count"] == 0
    assert internal_payload["redaction"]["redaction_report"] == []
    assert none_payload["redaction_profile"] == "none"
    assert none_payload["redaction_count"] == 0
    assert none_payload["redaction"]["redaction_report"] == []


def test_package_records_secret_detection_fails_closed(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="secret_detection_task", date="20260601")
    output_path = root / "package_records_secret_detection.json"
    (task_dir / "task_record.md").write_text(
        "access_token = ghp_1234567890abcdef\npassword = hunter2\n",
        encoding="utf-8",
    )

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
            "--redaction-profile",
            "safe",
        ]
    )

    assert rc == 2
    assert not output_path.exists()
    captured = capsys.readouterr()
    assert "Package Generation: FAIL" in captured.err
    assert "Privacy/Security: FAIL" in captured.err
    assert "package validation failed" not in captured.err.lower()


def test_package_records_private_key_detection_fails_closed(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="private_key_detection_task", date="20260601")
    output_path = root / "package_records_private_key_detection.json"
    (task_dir / "self_validation.md").write_text(
        "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 2
    assert not output_path.exists()


def test_package_records_prohibited_artifacts_are_excluded(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="prohibited_artifact_task", date="20260601")
    secret_file = task_dir / ".env"
    secret_file.write_text("TOKEN=do-not-package\n", encoding="utf-8")

    payload = _run_package_records_dry_run(root, "package_records_prohibited_artifact.json")

    expected = {"source_path": ai_workflow.rel(root, secret_file), "reason": "prohibited_secret_path"}
    assert payload["excluded_artifact_count"] == 1
    assert payload["redaction"]["excluded_artifact_count"] == 1
    assert expected in payload["artifacts"]["excluded"]
    assert expected in payload["redaction"]["exclusion_report"]
    assert payload["artifacts"]["prohibited_count"] == 1


def test_package_records_directory_package_layout_and_redacted_content(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="directory_package_task", date="20260601")
    _write_task_event_log(task_dir, {"timestamp": "2026-06-01T10:00:00Z", "event": "validation", "task_id": "001"})
    (task_dir / "task_record.md").write_text(f"Local path: {_redaction_fixture_user_path()}\n", encoding="utf-8")
    output_dir = root / ai_workflow.AIWF_PACKAGE_RECORDS_ROOT_DIR

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--output",
            str(output_dir),
            "--format",
            "directory",
            "--redaction-profile",
            "safe",
        ]
    )

    assert rc == 0
    for rel_path in [
        "package_manifest.json",
        "package_summary.md",
        "task_inventory.csv",
        "event_inventory.csv",
        "artifact_inventory.tsv",
        "events/events.jsonl",
        "dataset/aiwf_dataset.json",
        "integrity/package_tree_manifest.tsv",
        "integrity/package_identity.json",
        "integrity/redaction_report.json",
        "integrity/exclusion_report.json",
    ]:
        assert (output_dir / rel_path).is_file()

    copied_record = output_dir / "records" / "ai_20260601" / "001_directory_package_task" / "task_record.md"
    copied_text = copied_record.read_text(encoding="utf-8")
    assert _redaction_fixture_user_path().split("/project", 1)[0] not in copied_text
    assert "[AIWF-REDACTED:absolute_path]" in copied_text

    manifest = json.loads((output_dir / "package_manifest.json").read_text(encoding="utf-8"))
    summary_text = (output_dir / "package_summary.md").read_text(encoding="utf-8")
    assert manifest["options"]["format"] == "directory"
    assert manifest["dataset"]["included"] is True
    assert manifest["events"]["canonical_event_count"] == 1
    assert ai_workflow._package_records_validate_manifest_schema(manifest) == []
    assert "- Package Generation: PASS" in summary_text
    assert "- Manifest Schema: PASS" in summary_text
    assert "- Package Integrity: PASS" in summary_text
    assert "- Privacy/Security: PASS" in summary_text
    assert "- Workflow Evidence Findings: PASS" in summary_text
    assert "do not by themselves mean package generation failed" in summary_text
    record_artifact = next(item for item in manifest["artifacts"]["included"] if item["package_path"].endswith("/task_record.md"))
    assert record_artifact["redaction"] == "redacted"
    assert record_artifact["sha256"] == hashlib.sha256(copied_record.read_bytes()).hexdigest()
    assert "records/ai_20260601/001_directory_package_task/task_record.md" in (
        output_dir / "integrity" / "package_tree_manifest.tsv"
    ).read_text(encoding="utf-8")


def test_package_records_zip_is_reproducible_and_rooted(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="zip_package_task", date="20260601")
    _write_task_event_log(task_dir, {"timestamp": "2026-06-01T10:00:00Z", "event": "validation", "task_id": "001"})
    first_zip = root / "first_package.zip"
    second_zip = root / "second_package.zip"

    first_rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--output",
            str(first_zip),
            "--format",
            "zip",
        ]
    )
    second_rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--output",
            str(second_zip),
            "--format",
            "zip",
        ]
    )

    assert first_rc == 0
    assert second_rc == 0
    assert first_zip.read_bytes() == second_zip.read_bytes()
    with zipfile.ZipFile(first_zip) as archive:
        names = sorted(archive.namelist())
        assert all(name.startswith(f"{ai_workflow.AIWF_PACKAGE_RECORDS_ROOT_DIR}/") for name in names)
        assert f"{ai_workflow.AIWF_PACKAGE_RECORDS_ROOT_DIR}/package_manifest.json" in names
        assert f"{ai_workflow.AIWF_PACKAGE_RECORDS_ROOT_DIR}/events/events.jsonl" in names
        assert f"{ai_workflow.AIWF_PACKAGE_RECORDS_ROOT_DIR}/dataset/aiwf_dataset.json" in names
        infos = {item.filename: item for item in archive.infolist()}
        assert all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in infos.values())


def test_package_records_force_replaces_existing_output_after_safety_checks(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="force_package_task", date="20260601")
    output_dir = root / "records_package_dir"
    output_dir.mkdir()
    (output_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--output",
            str(output_dir),
            "--format",
            "directory",
            "--force",
        ]
    )

    assert rc == 0
    assert not (output_dir / "stale.txt").exists()
    assert (output_dir / "package_manifest.json").exists()


def test_package_records_repository_metadata_reports_git_clean_and_dirty_tree(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    _create_v2_task(root, name="repository_metadata_task", date="20260601")
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=AIWF Test",
            "-c",
            "user.email=aiwf-test@example.invalid",
            "commit",
            "-m",
            "seed",
        ],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    clean_path = tmp_path / "clean_repository_manifest.json"
    clean_rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(clean_path),
        ]
    )
    (root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty_path = tmp_path / "dirty_repository_manifest.json"
    dirty_rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(dirty_path),
        ]
    )

    assert clean_rc == 0
    assert dirty_rc == 0
    clean_payload = json.loads(clean_path.read_text(encoding="utf-8"))
    dirty_payload = json.loads(dirty_path.read_text(encoding="utf-8"))
    assert clean_payload["repository"]["git_available"] is True
    assert clean_payload["repository"]["dirty_tree"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", clean_payload["repository"]["commit"])
    assert clean_payload["repository"]["branch"]
    assert dirty_payload["repository"]["git_available"] is True
    assert dirty_payload["repository"]["dirty_tree"] is True


def test_package_records_discovers_all_valid_task_directories(tmp_path: Path):
    root = _init_repo(tmp_path)
    first = _create_v2_task(root, name="first_package_task", date="20260601")
    second = _create_v2_task(root, name="second_package_task", date="20260602")
    invalid_dir = root / ".aiwf" / "records" / "ai_20260602" / "not_a_task"
    invalid_dir.mkdir(parents=True)

    payload = _run_package_records_dry_run(root, "package_records_discover.json")

    assert [item["source_path"] for item in payload["selected_tasks"]] == [
        ai_workflow.rel(root, first),
        ai_workflow.rel(root, second),
    ]
    assert {"source_path": ai_workflow.rel(root, invalid_dir), "reason": "invalid_task_dir"} in payload["excluded_tasks"]


def test_package_records_date_filter_selects_expected_tasks(tmp_path: Path):
    root = _init_repo(tmp_path)
    selected = _create_v2_task(root, name="selected_date_task", date="20260601")
    excluded = _create_v2_task(root, name="excluded_date_task", date="20260602")

    payload = _run_package_records_dry_run(
        root,
        "package_records_date.json",
        ["--date", "2026-06-01"],
    )

    assert [item["source_path"] for item in payload["selected_tasks"]] == [ai_workflow.rel(root, selected)]
    assert {"source_path": ai_workflow.rel(root, excluded), "reason": "filtered_by_date"} in payload["excluded_tasks"]


def test_package_records_metadata_filters_select_expected_tasks(tmp_path: Path):
    root = _init_repo(tmp_path)
    excluded = _create_v2_task(root, name="draft_filtered_task", date="20260601")
    selected = _create_v2_task(root, name="reviewed_filtered_task", date="20260601")
    _rewrite_task_metadata(
        selected / "task.md",
        status="review",
        workflow_phase="validation",
        review_status="pass",
    )

    payload = _run_package_records_dry_run(
        root,
        "package_records_metadata_filters.json",
        ["--status", "review", "--workflow-phase", "validation", "--review-status", "pass"],
    )

    assert [item["source_path"] for item in payload["selected_tasks"]] == [ai_workflow.rel(root, selected)]
    assert {"source_path": ai_workflow.rel(root, excluded), "reason": "filtered_by_status"} in payload["excluded_tasks"]


def test_package_records_task_id_selector_fails_when_ambiguous(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="first_ambiguous_task", date="20260601")
    _create_v2_task(root, name="second_ambiguous_task", date="20260602")
    output_path = root / "package_records_ambiguous.json"

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
            "--task",
            "001",
        ]
    )

    assert rc == 2
    assert not output_path.exists()


def test_package_records_task_path_selector_selects_exact_task(tmp_path: Path):
    root = _init_repo(tmp_path)
    excluded = _create_v2_task(root, name="path_selector_excluded", date="20260601")
    selected = _create_v2_task(root, name="path_selector_selected", date="20260602")

    payload = _run_package_records_dry_run(
        root,
        "package_records_path_selector.json",
        ["--task", ai_workflow.rel(root, selected)],
    )

    assert [item["source_path"] for item in payload["selected_tasks"]] == [ai_workflow.rel(root, selected)]
    assert {"source_path": ai_workflow.rel(root, excluded), "reason": "filtered_by_task"} in payload["excluded_tasks"]


def test_package_records_excluded_reasons_are_recorded(tmp_path: Path):
    root = _init_repo(tmp_path)
    draft_task = _create_v2_task(root, name="excluded_draft_task", date="20260601")
    reviewed_task = _create_v2_task(root, name="included_review_task", date="20260601")
    _rewrite_task_metadata(reviewed_task / "task.md", status="review")

    payload = _run_package_records_dry_run(
        root,
        "package_records_excluded_reasons.json",
        ["--status", "review"],
    )

    assert [item["source_path"] for item in payload["selected_tasks"]] == [ai_workflow.rel(root, reviewed_task)]
    assert {"source_path": ai_workflow.rel(root, draft_task), "reason": "filtered_by_status"} in payload["excluded_tasks"]


def test_package_records_rejects_output_inside_records_root(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="records_output_rejected", date="20260601")
    output_path = root / ".aiwf" / "records" / "package_records_manifest.json"

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 2
    assert not output_path.exists()


def test_package_records_dry_run_does_not_generate_archive_or_directory(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="no_archive_task", date="20260601")

    _run_package_records_dry_run(root, "package_records_no_archive.json")

    assert not (root / "aiwf_records_package").exists()
    assert not (root / "aiwf_records_package.zip").exists()
    assert not (root / ai_workflow.AIWF_PACKAGE_RECORDS_DATASET_PATH).exists()
    assert not list(root.glob("*.zip"))


def test_package_records_repeated_manifest_generation_is_byte_identical(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="stable_manifest_task", date="20260601")

    first_path = _run_package_records_dry_run_file(root, "package_records_stable_1.json")
    second_path = _run_package_records_dry_run_file(root, "package_records_stable_2.json")

    assert first_path.read_bytes() == second_path.read_bytes()


def test_package_records_task_ordering_is_deterministic(tmp_path: Path):
    root = _init_repo(tmp_path)
    third = _create_v2_task(root, name="third_order_task", date="20260602")
    first = _create_v2_task(root, name="first_order_task", date="20260601")
    second = _create_v2_task(root, name="second_order_task", date="20260601")

    payload = _run_package_records_dry_run(root, "package_records_task_order.json")

    assert [item["source_path"] for item in payload["selected_tasks"]] == [
        ai_workflow.rel(root, first),
        ai_workflow.rel(root, second),
        ai_workflow.rel(root, third),
    ]


def test_package_records_package_path_normalization_is_stable():
    assert ai_workflow.normalize_package_path(r"./records\ai_20260601//001_task/task.md") == "records/ai_20260601/001_task/task.md"


def test_package_records_package_path_rejects_absolute_path():
    with pytest.raises(ValueError):
        ai_workflow.normalize_package_path("/records/ai_20260601/001_task/task.md")


def test_package_records_package_path_rejects_parent_traversal():
    with pytest.raises(ValueError):
        ai_workflow.normalize_package_path("records/ai_20260601/../001_task/task.md")


def test_package_records_package_tree_manifest_rows_are_ordered(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="tree_manifest_task", date="20260601")

    payload = _run_package_records_dry_run(root, "package_records_tree_manifest.json")
    tree_manifest = ai_workflow._package_records_package_tree_manifest_tsv(payload["artifacts"]["included"])
    rows = [line.split("\t") for line in tree_manifest.splitlines()]
    paths = [row[3] for row in rows]

    assert paths == sorted(paths)
    assert all(len(row) == 4 for row in rows)
    assert all(re.fullmatch(r"[0-9a-f]{64}", row[0]) for row in rows)
    assert all(row[1] in {"100644", "100755", "120000"} for row in rows)


def test_package_records_identity_is_stable_across_repeated_runs(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="stable_identity_task", date="20260601")

    first = _run_package_records_dry_run(root, "package_records_identity_1.json")
    second = _run_package_records_dry_run(root, "package_records_identity_2.json")

    assert first["identity"]["reproducible_evidence_sha256"] == second["identity"]["reproducible_evidence_sha256"]
    assert first["artifacts"]["included"] == second["artifacts"]["included"]


def test_package_records_instance_metadata_is_excluded_from_identity(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="identity_exclusion_task", date="20260601")

    payload = _run_package_records_dry_run(root, "package_records_identity_exclusion.json")
    original_identity = payload["identity"]["reproducible_evidence_sha256"]
    payload["generated_at_utc"] = "2026-06-30T00:00:00Z"
    payload["repository"]["dirty_tree"] = not payload["repository"]["dirty_tree"]

    recomputed = ai_workflow._package_records_identity(payload["artifacts"]["included"])

    assert recomputed["reproducible_evidence_sha256"] == original_identity
    assert "generated_at_utc" in payload["identity"]["excluded_identity_fields"]
    assert "repository.dirty_tree" in payload["identity"]["excluded_identity_fields"]


def test_package_records_stable_json_orders_keys():
    assert ai_workflow.stable_json_dump({"b": 1, "a": 2}) == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_package_records_valid_manifest_passes_schema_validation(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="valid_schema_task", date="20260601")

    payload = _run_package_records_dry_run(root, "package_records_schema_valid.json")

    assert ai_workflow._package_records_validate_manifest_schema(payload) == []


def test_package_records_schema_validation_rejects_missing_required_top_level_field(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="missing_schema_field_task", date="20260601")
    payload = _run_package_records_dry_run(root, "package_records_schema_missing.json")
    del payload["capabilities"]

    errors = ai_workflow._package_records_validate_manifest_schema(payload)

    assert {"path": "$.capabilities", "message": "required field is missing"} in errors


def test_package_records_schema_validation_rejects_wrong_capability_type(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="bad_capability_task", date="20260601")
    payload = _run_package_records_dry_run(root, "package_records_schema_capability.json")
    payload["capabilities"]["dataset"] = "false"

    errors = ai_workflow._package_records_validate_manifest_schema(payload)

    assert {"path": "$.capabilities.dataset", "message": "expected boolean"} in errors


def test_package_records_schema_validation_rejects_wrong_artifact_class(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="bad_artifact_class_task", date="20260601")
    payload = _run_package_records_dry_run(root, "package_records_schema_artifact_class.json")
    payload["artifacts"]["included"][0]["artifact_class"] = "runtime_policy"

    errors = ai_workflow._package_records_validate_manifest_schema(payload)

    assert any(error["path"] == "$.artifacts.included[0].artifact_class" for error in errors)
    assert any("derived_analysis" in error["message"] and "workflow_evidence" in error["message"] for error in errors)


def test_package_records_schema_validation_rejects_invalid_identity_hash_policy(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="bad_hash_policy_task", date="20260601")
    payload = _run_package_records_dry_run(root, "package_records_schema_hash_policy.json")
    payload["identity"]["hash_policy"] = "wrong-policy"

    errors = ai_workflow._package_records_validate_manifest_schema(payload)

    assert {"path": "$.identity.hash_policy", "message": 'expected "aiwf-package-records-v1"'} in errors


def test_package_records_schema_validation_rejects_invalid_validation_status(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="bad_validation_status_task", date="20260601")
    payload = _run_package_records_dry_run(root, "package_records_schema_validation_status.json")
    payload["validation"]["package_generation"]["result"] = "maybe"

    errors = ai_workflow._package_records_validate_manifest_schema(payload)

    assert {
        "path": "$.validation.package_generation.result",
        "message": "expected one of: fail, pass, warn",
    } in errors


def test_package_records_schema_validation_failure_does_not_write_output(tmp_path: Path, monkeypatch, capsys):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="schema_failure_no_write_task", date="20260601")
    output_path = root / "package_records_schema_failure.json"
    monkeypatch.setattr(
        ai_workflow,
        "_package_records_validate_manifest_schema",
        lambda _manifest: [{"path": "$.identity.hash_policy", "message": 'expected "aiwf-package-records-v1"'}],
    )

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 2
    assert not output_path.exists()
    captured = capsys.readouterr()
    assert "Package Generation: FAIL" in captured.err
    assert "Manifest Schema: FAIL" in captured.err
    assert "package records manifest schema validation failed" in captured.err


def test_package_records_schema_validation_errors_are_deterministically_ordered(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="schema_error_order_task", date="20260601")
    payload = _run_package_records_dry_run(root, "package_records_schema_order.json")
    payload["identity"]["hash_policy"] = "wrong-policy"
    payload["capabilities"]["dataset"] = "false"
    payload["artifacts"]["included"][0]["artifact_class"] = "runtime_policy"

    errors = ai_workflow._package_records_validate_manifest_schema(payload)

    assert errors == sorted(errors, key=lambda item: (item["path"], item["message"]))
    assert [error["path"] for error in errors] == [
        "$.artifacts.included[0].artifact_class",
        "$.capabilities.dataset",
        "$.identity.hash_policy",
    ]


def test_package_records_task_local_events_counted_for_selected_task(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="task_local_events", date="20260601")
    _write_task_event_log(
        task_dir,
        {"timestamp": "2026-06-01T10:00:00Z", "event": "start"},
        {"timestamp": "2026-06-01T10:01:00Z", "event": "check"},
    )

    payload = _run_package_records_dry_run(
        root,
        "package_records_task_local_events.json",
        ["--task", ai_workflow.rel(root, task_dir)],
    )

    source_path = ai_workflow.rel(root, task_dir / ".aiwf" / "events.jsonl")
    assert payload["events"]["task_local_event_count"] == 2
    assert payload["events"]["global_event_count"] == 0
    assert payload["events"]["canonical_event_count"] == 2
    assert {
        "source_path": source_path,
        "event_count": 2,
        "malformed_count": 0,
    } in payload["events"]["sources"]


def test_package_records_global_events_associated_by_task_path(tmp_path: Path):
    root = _init_repo(tmp_path)
    selected = _create_v2_task(root, name="global_task_path_selected", date="20260601")
    unselected = _create_v2_task(root, name="global_task_path_unselected", date="20260602")
    _write_repo_event_log(
        root,
        json.dumps(
            {
                "timestamp": "2026-06-01T10:00:00Z",
                "event": "selected",
                "task_path": ai_workflow.rel(root, selected),
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-06-01T10:01:00Z",
                "event": "unselected",
                "task_path": ai_workflow.rel(root, unselected),
            }
        ),
    )

    payload = _run_package_records_dry_run(
        root,
        "package_records_global_task_path.json",
        ["--task", ai_workflow.rel(root, selected)],
    )

    assert payload["events"]["global_event_count"] == 1
    assert payload["events"]["canonical_event_count"] == 1
    assert payload["events"]["unassociated_event_count"] == 1
    assert any(item["source_path"] == ".aiwf/events/events.jsonl" and item["event_count"] == 1 for item in payload["events"]["sources"])


def test_package_records_global_events_associated_by_unambiguous_task_id(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="global_task_id_selected", date="20260601")
    _write_repo_event_log(
        root,
        json.dumps({"timestamp": "2026-06-01T10:00:00Z", "event": "selected", "task_id": "001"}),
    )

    payload = _run_package_records_dry_run(
        root,
        "package_records_global_task_id.json",
        ["--task", ai_workflow.rel(root, task_dir)],
    )

    assert payload["events"]["global_event_count"] == 1
    assert payload["events"]["canonical_event_count"] == 1
    assert payload["events"]["unassociated_event_count"] == 0


def test_package_records_task_path_precedence_wins_over_ambiguous_task_id(tmp_path: Path):
    root = _init_repo(tmp_path)
    selected = _create_v2_task(root, name="precedence_selected", date="20260601")
    _create_v2_task(root, name="precedence_ambiguous_id_peer", date="20260602")
    _write_repo_event_log(
        root,
        json.dumps(
            {
                "timestamp": "2026-06-01T10:00:00Z",
                "event": "precedence",
                "task_path": ai_workflow.rel(root, selected),
                "task_id": "001",
            }
        ),
    )

    payload = _run_package_records_dry_run(root, "package_records_task_path_precedence.json")

    assert payload["events"]["global_event_count"] == 1
    assert payload["events"]["unassociated_event_count"] == 0
    assert not any(item["code"] == "AIWF-PACKAGE-RECORDS-AMBIGUOUS-EVENT-TASK-ID" for item in payload["validation"]["findings"])


def test_package_records_legacy_record_path_mapping_associates_global_event(tmp_path: Path):
    root = _init_repo(tmp_path)
    selected = _create_v2_task(root, name="legacy_record_path_selected", date="20260601")
    _write_repo_event_log(
        root,
        json.dumps(
            {
                "timestamp": "2026-06-01T10:00:00Z",
                "event": "legacy-record-path",
                "record_path": f"{ai_workflow.rel(root, selected)}/task_record.md",
            }
        ),
    )

    payload = _run_package_records_dry_run(root, "package_records_legacy_record_path.json")

    assert payload["events"]["global_event_count"] == 1
    assert payload["events"]["canonical_event_count"] == 1
    assert payload["events"]["unassociated_event_count"] == 0


def test_package_records_task_id_precedence_wins_over_legacy_record_path(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_id_selected = _create_v2_task(root, name="task_id_precedence_selected", date="20260601")
    legacy_peer = _create_v2_task(root, name="legacy_precedence_peer", date="20260602")
    _write_repo_event_log(
        root,
        json.dumps(
            {
                "timestamp": "2026-06-01T10:00:00Z",
                "event": "task-id-precedence",
                "task_id": "001",
                "record_path": f"{ai_workflow.rel(root, legacy_peer)}/task_record.md",
            }
        ),
    )

    payload = _run_package_records_dry_run(
        root,
        "package_records_task_id_precedence.json",
        ["--task", ai_workflow.rel(root, task_id_selected)],
    )

    assert payload["events"]["global_event_count"] == 1
    assert payload["events"]["unassociated_event_count"] == 0
    assert not any(item["code"] == "AIWF-PACKAGE-RECORDS-UNASSOCIATED-EVENT" for item in payload["validation"]["findings"])


def test_package_records_ambiguous_task_id_association_reports_finding_and_strict_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="first_ambiguous_event_task", date="20260601")
    _create_v2_task(root, name="second_ambiguous_event_task", date="20260602")
    _write_repo_event_log(
        root,
        json.dumps({"timestamp": "2026-06-01T10:00:00Z", "event": "ambiguous", "task_id": "001"}),
    )

    payload = _run_package_records_dry_run(root, "package_records_ambiguous_event_task_id.json")
    strict_output = root / "package_records_ambiguous_event_task_id_strict.json"
    strict_rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(strict_output),
            "--strict",
        ]
    )

    assert payload["events"]["global_event_count"] == 0
    assert payload["events"]["unassociated_event_count"] == 1
    assert any(item["code"] == "AIWF-PACKAGE-RECORDS-AMBIGUOUS-EVENT-TASK-ID" for item in payload["validation"]["findings"])
    assert strict_rc == 2
    assert not strict_output.exists()


def test_package_records_unassociated_global_events_are_excluded_and_counted(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="unassociated_global_event_task", date="20260601")
    _write_repo_event_log(
        root,
        json.dumps({"timestamp": "2026-06-01T10:00:00Z", "event": "repo-wide"}),
    )

    payload = _run_package_records_dry_run(root, "package_records_unassociated_global_event.json")

    assert payload["events"]["global_event_count"] == 0
    assert payload["events"]["canonical_event_count"] == 0
    assert payload["events"]["unassociated_event_count"] == 1
    assert any(item["code"] == "AIWF-PACKAGE-RECORDS-UNASSOCIATED-EVENT" for item in payload["validation"]["findings"])


def test_package_records_malformed_jsonl_row_is_counted_and_reported(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="malformed_task_local_event", date="20260601")
    _write_task_event_log(
        task_dir,
        '{"timestamp": "2026-06-01T10:00:00Z", "event": "valid"}',
        '{"timestamp":',
    )

    payload = _run_package_records_dry_run(root, "package_records_malformed_event.json")

    assert payload["events"]["task_local_event_count"] == 1
    assert payload["events"]["malformed_event_count"] == 1
    assert any(item["code"] == "AIWF-PACKAGE-RECORDS-MALFORMED-EVENT" for item in payload["validation"]["findings"])


def test_package_records_invalid_timestamp_reports_finding_and_sort_key_is_deterministic(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="invalid_timestamp_event", date="20260601")
    _write_task_event_log(
        task_dir,
        {"timestamp": "not-a-timestamp", "event": "bad"},
        {"timestamp": "2026-06-01T10:00:00Z", "event": "good"},
    )

    payload = _run_package_records_dry_run(root, "package_records_invalid_timestamp.json")
    sorted_items = sorted(
        [
            {
                "parsed_timestamp": None,
                "source_path": "b/events.jsonl",
                "source_line": 1,
            },
            {
                "parsed_timestamp": ai_workflow.dt.datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
                "source_path": "a/events.jsonl",
                "source_line": 2,
            },
        ],
        key=ai_workflow._package_records_canonical_event_sort_key,
    )

    assert payload["events"]["canonical_event_count"] == 2
    assert any(item["code"] == "AIWF-PACKAGE-RECORDS-INVALID-EVENT-TIMESTAMP" for item in payload["validation"]["findings"])
    assert sorted_items[0]["source_path"] == "a/events.jsonl"


def test_package_records_task_local_events_only_excludes_global_event_counts(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="task_local_only_events", date="20260601")
    _write_task_event_log(task_dir, {"timestamp": "2026-06-01T10:00:00Z", "event": "local"})
    _write_repo_event_log(
        root,
        json.dumps(
            {
                "timestamp": "2026-06-01T10:01:00Z",
                "event": "global",
                "task_path": ai_workflow.rel(root, task_dir),
            }
        ),
    )

    payload = _run_package_records_dry_run(
        root,
        "package_records_task_local_only.json",
        ["--task-local-events-only"],
    )

    assert payload["options"]["include_global_events"] is False
    assert payload["events"]["task_local_event_count"] == 1
    assert payload["events"]["global_event_count"] == 0
    assert payload["events"]["canonical_event_count"] == 1
    assert all(item["source_path"] != ".aiwf/events/events.jsonl" for item in payload["events"]["sources"])


def test_package_records_conflicting_global_event_options_fail_closed(tmp_path: Path):
    root = _init_repo(tmp_path)
    _create_v2_task(root, name="conflicting_global_options", date="20260601")
    output_path = root / "package_records_conflicting_global_options.json"

    rc = ai_workflow.main(
        [
            "--repo-root",
            str(root),
            "package",
            "records",
            "--dry-run",
            "--output",
            str(output_path),
            "--include-global-events",
            "--task-local-events-only",
        ]
    )

    assert rc == 2
    assert not output_path.exists()


def test_package_records_manifest_remains_schema_valid_after_event_packaging(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, name="schema_valid_event_packaging", date="20260601")
    _write_task_event_log(task_dir, {"timestamp": "2026-06-01T10:00:00Z", "event": "local"})
    _write_repo_event_log(
        root,
        json.dumps(
            {
                "timestamp": "2026-06-01T10:01:00Z",
                "event": "global",
                "task_path": ai_workflow.rel(root, task_dir),
            }
        ),
    )

    payload = _run_package_records_dry_run(root, "package_records_event_schema_valid.json")

    assert payload["events"]["canonical_event_count"] == 2
    assert ai_workflow._package_records_validate_manifest_schema(payload) == []


def test_invalid_workflow_phase_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", workflow_phase="shipit")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_guard_pre_edit_passes_for_valid_open_task(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    rc, output = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)
    assert rc == 0
    assert "AIWF-GUARD-PASS" in output
    assert f"task_path: {ai_workflow.rel(root, task_dir)}" in output


def test_guard_pre_edit_blocks_missing_task_path(tmp_path: Path):
    root = _init_repo(tmp_path)
    missing_task = root / "docs" / "ai_20260508" / "999_missing_task"

    rc, output = ai_workflow.guard_pre_edit(root, str(missing_task), pre_edit=True)
    assert rc == 2
    assert "AIWF-GUARD-001" in output
    assert "task path does not exist" in output


def test_guard_pre_edit_blocks_missing_required_artifact(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    (task_dir / "agent.md").unlink()

    rc, output = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)
    assert rc == 2
    assert "AIWF-GUARD-002" in output
    assert "missing:" in output
    assert "- agent.md" in output


def test_guard_pre_edit_blocks_bad_task_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    (task_dir / "task.md").write_text(
        "\n".join(
            [
                "---",
                "status: draft",
                "workflow_phase: implementation",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc, output = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)
    assert rc == 2
    assert "AIWF-GUARD-003" in output


def test_guard_pre_edit_blocks_finalized_workflow_phase(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", workflow_phase="finalized", finalized_at=None)

    rc, output = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)
    assert rc == 2
    assert "AIWF-GUARD-004" in output
    assert "reason: workflow_phase=finalized" in output


def test_guard_pre_edit_blocks_done_status(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        status="done",
        workflow_phase="implementation",
        finalized_at=None,
    )

    rc, output = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)
    assert rc == 2
    assert "AIWF-GUARD-004" in output
    assert "reason: status=done" in output


def test_guard_pre_edit_blocks_finalized_at_present(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        status="draft",
        workflow_phase="implementation",
        finalized_at="2026-05-21T00:00:00Z",
    )

    rc, output = ai_workflow.guard_pre_edit(root, str(task_dir), pre_edit=True)
    assert rc == 2
    assert "AIWF-GUARD-004" in output
    assert "reason: finalized_at present" in output


def test_guard_pre_edit_cli_pass(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "guard", "--pre-edit", "--path", str(task_dir)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF-GUARD-PASS" in out
    assert f"task_path: {ai_workflow.rel(root, task_dir)}" in out


def test_guard_pre_edit_cli_block_exit_code(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)

    capsys.readouterr()
    rc = ai_workflow.main(["--repo-root", str(root), "guard", "--pre-edit"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "AIWF-GUARD-900" in out


def test_next_id_allocation_correctness(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _create_task(root, name="task_one", date="20260509")
    _create_task(root, name="task_two", date="20260509")

    capsys.readouterr()
    rc = ai_workflow.next_id_command(root, "20260509")
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "003"


def test_doctor_output_includes_suggested_fix(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    (task_dir / "review_final.md").unlink()

    rc = ai_workflow.doctor_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "Suggested Fix:" in out
    assert "AIWF-FILE-001" in out


def test_structured_diagnostics_format_in_check(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", status="not_allowed")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-META-007" in out
    assert "Suggested Fix:" in out


def test_placeholder_detection_blocks_bullet_placeholder(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _write_finalize_ready_docs(task_dir)
    (task_dir / "self_validation.md").write_text(
        "## Commands Run\n- x\n## Results\n- TBD\n## Known Limitations\n- none\n",
        encoding="utf-8",
    )

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PLACEHOLDER-001" in out


def test_placeholder_detection_blocks_star_bullet_placeholder(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _write_finalize_ready_docs(task_dir)
    (task_dir / "self_validation.md").write_text(
        "## Commands Run\n- x\n## Results\n* TODO\n## Known Limitations\n- none\n",
        encoding="utf-8",
    )

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PLACEHOLDER-001" in out


def test_finalize_success_path_updates_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0
    metadata, _ = ai_workflow.parse_front_matter((task_dir / "task.md").read_text(encoding="utf-8"))
    assert metadata["status"] == "done"
    assert metadata["workflow_phase"] == "finalized"
    assert metadata["updated_at"]
    assert "status: Done" in _task_index_line(task_dir)
    assert ai_workflow.check_path(root, str(task_dir), strict=False) == 0


def test_finalize_dry_run_does_not_mutate_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)
    before = (task_dir / "task.md").read_text(encoding="utf-8")

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    after = (task_dir / "task.md").read_text(encoding="utf-8")
    assert rc == 0
    assert before == after


def test_finalize_prints_mutation_summary(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Applied Metadata Changes:" in out
    assert "Applied Index Projection:" in out
    assert "status: review -> done" in out


def test_finalize_blocked_by_missing_file(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    (task_dir / "review_final.md").unlink()

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 2


def test_finalize_blocked_by_invalid_review_status(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pending", status="review", workflow_phase="validation")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 2


def test_finalize_prevents_premature_done_state(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", status="done", workflow_phase="implementation", review_status="pass")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_placeholder_detection_allows_non_placeholder_reference(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)
    (task_dir / "task_record.md").write_text(
        "\n".join(
            [
                "# Task Record",
                "## Changed",
                "- Completed implementation.",
                "## Why",
                "- This section mentions TODO from upstream history but not as placeholder sentence.",
                "## Compatibility Notes",
                "- none",
                "## Files Modified",
                "- .aiwf/bin/ai_workflow.py",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    assert rc == 0


def test_finalize_blocks_pending_validation_residue(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)
    (task_dir / "task_record.md").write_text(ai_workflow.task_record_md("sample"), encoding="utf-8")

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-020" in out


def test_finalize_blocks_pending_review_residue(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)
    (task_dir / "review_final.md").write_text(ai_workflow.review_final_md("sample"), encoding="utf-8")

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-021" in out


def test_finalize_blocks_default_template_residue_in_task_section(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(
        task_dir,
        background="Describe the source of this task, including bug report, review finding, historical record, or user request.",
    )
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-022" in out


def test_finalize_blocks_acceptance_criteria_without_closure_decision(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(
        task_dir,
        acceptance_lines=[
            "- [ ] Required workflow files exist.",
            "- [ ] Validation results are documented.",
        ],
    )
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-023" in out


def test_finalize_blocks_mixed_unresolved_acceptance_criteria(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(
        task_dir,
        acceptance_lines=[
            "- [x] Required workflow files exist.",
            "- [ ] Validation results are documented.",
        ],
    )
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-024" in out


def test_finalize_allows_deferred_and_not_applicable_acceptance_criteria(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _write_task_body(
        task_dir,
        acceptance_lines=[
            "- [x] Required workflow files exist.",
            "- [ ] Deferred until follow-up task 002 with scope rationale.",
            "- [ ] Not applicable for this documentation-only change.",
        ],
    )
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    assert rc == 0


def test_list_command_filtering(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    t1 = _create_task(root, name="task_one", date="20260509")
    t2 = _create_task(root, name="task_two", date="20260509")
    _rewrite_task_metadata(t1 / "task.md", status="blocked", blocked_reason="waiting", workflow_phase="implementation")
    _rewrite_task_metadata(t2 / "task.md", status="review", review_status="pending", workflow_phase="validation")

    capsys.readouterr()
    rc = ai_workflow.list_command(root, status="blocked", review_status=None, workflow_phase=None, date="20260509")
    out = capsys.readouterr().out
    assert rc == 0
    assert "task_one" in out
    assert "task_two" not in out


def test_schema_version_v12_compatibility(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        schema_version="ai-workflow-v1.2",
    )
    text = (task_dir / "task.md").read_text(encoding="utf-8")
    metadata, body = ai_workflow.parse_front_matter(text)
    metadata.pop("workflow_phase", None)
    (task_dir / "task.md").write_text(ai_workflow.format_front_matter(metadata) + body.lstrip("\n"), encoding="utf-8")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_schema_version_v12_with_explicit_optional_extension_null_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        schema_version="ai-workflow-v1.2",
        workflow_phase=None,
    )
    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 2


def test_schema_version_v14_compatibility(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _rewrite_task_metadata(
        task_dir / "task.md",
        schema_version="ai-workflow-v1.4",
    )

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_finalize_sets_finalized_fields(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0
    metadata, _ = ai_workflow.parse_front_matter((task_dir / "task.md").read_text(encoding="utf-8"))
    assert metadata["finalized_at"]
    assert metadata["finalized_by"] == "tool"


def test_finalize_is_idempotent_no_mutation_on_second_run(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)

    rc1 = ai_workflow.finalize_command(root, str(task_dir))
    first = (task_dir / "task.md").read_text(encoding="utf-8")
    rc2 = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    second = (task_dir / "task.md").read_text(encoding="utf-8")

    assert rc1 == 0
    assert rc2 == 0
    assert first == second
    assert "AIWF-FINALIZE-001" in out
    assert "No changes applied" in out


def test_finalize_dry_run_on_finalized_task_reports_noop(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)
    ai_workflow.finalize_command(root, str(task_dir))
    before = (task_dir / "task.md").read_text(encoding="utf-8")

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    after = (task_dir / "task.md").read_text(encoding="utf-8")
    assert rc == 0
    assert before == after
    assert "Task already finalized." in out
    assert "No changes would be applied." in out


def test_finalize_blocks_already_finalized_task_with_stale_index(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    _record_v16_finalize_evidence(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0
    _set_index_status_for_task(task_dir, "Review")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "INDEX_STATUS_STALE" in out


def test_finalized_task_modified_after_timestamp_warns(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root)
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", schema_version="ai-workflow-v1.5", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    ai_workflow.finalize_command(root, str(task_dir))
    _sync_index(root, task_dir)

    target = task_dir / "task_record.md"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\npost finalize note\n", encoding="utf-8")
    future = time.time() + 2
    os.utime(target, (future, future))

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF-FINALIZED-001" in out


def test_required_doc_sections_registry_is_centralized():
    assert ai_workflow.REQUIRED_DOC_SECTIONS["task_record.md"] == ("Changed", "Why")
    assert ai_workflow.REQUIRED_DOC_SECTIONS["self_validation.md"] == ("Commands Run", "Results")
    assert ai_workflow.REQUIRED_DOC_SECTIONS["review_final.md"] == ("Final Result",)


def test_diagnostics_registry_consistency():
    required_codes = {
        "AIWF-META-001",
        "AIWF-FILE-001",
        "AIWF-SECTION-001",
        "AIWF-PLACEHOLDER-001",
        "AIWF-REVIEW-002",
    }
    for code in required_codes:
        assert code in ai_workflow.DIAGNOSTICS
        spec = ai_workflow.DIAGNOSTICS[code]
        assert "severity" in spec and "message" in spec and "suggested_fix" in spec


def test_load_aiwf_env_precedence(tmp_path: Path):
    root = _init_repo(tmp_path)
    (root / ".env").write_text(
        "\n".join(
            [
                "AIWF_EVENT_LOG=0",
                "AIWF_WORKFLOW_MODE=from_env_file",
                'AIWF_MODEL_NAME="env-model"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    old = dict(os.environ)
    try:
        os.environ["AIWF_EVENT_LOG"] = "1"
        os.environ["AIWF_MODEL_NAME"] = "process-model"
        loaded = ai_workflow.load_aiwf_env(root)
        assert loaded["AIWF_EVENT_LOG"] == "1"
        assert loaded["AIWF_WORKFLOW_MODE"] == "from_env_file"
        assert loaded["AIWF_MODEL_NAME"] == "process-model"
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_event_logging_disabled_by_default(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, name="sample_task", date="20260510")
    rc = ai_workflow.doctor_command(root, str(task_dir))
    assert rc == 2
    assert not (task_dir / ".aiwf" / "events.jsonl").exists()


def test_event_logging_enabled_and_export_experiment(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, name="sample_task", date="20260510")
    (root / ".env").write_text(
        "\n".join(
            [
                "AIWF_EVENT_LOG=1",
                "AIWF_WORKFLOW_MODE=aiwf_deterministic",
                "AIWF_MODEL_NAME=test-model",
                "AIWF_MODEL_CLASS=local_quantized",
                "AIWF_MODEL_PROVIDER=test-provider",
                "AIWF_ACTOR=codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc1 = ai_workflow.doctor_command(root, str(task_dir))
    assert rc1 == 2
    rc2 = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    assert rc2 == 2

    event_path = task_dir / ".aiwf" / "events.jsonl"
    assert event_path.exists()
    lines = [line for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["schema_version"] == "aiwf-event-v0.1"
    assert first["tool_version"] == ai_workflow.AIWF_TOOL_VERSION
    assert ai_workflow.WORKFLOW_PROTOCOL_VERSION == "1.7.8"
    assert first["command"] == "doctor"
    assert first["workflow_mode"] == "aiwf_deterministic"
    assert first["model"]["name"] == "test-model"
    assert first["model"]["class"] == "local_quantized"
    assert first["model"]["provider"] == "test-provider"
    assert second["command"] == "finalize_dry_run"
    assert second["tool_version"] == ai_workflow.AIWF_TOOL_VERSION

    events = ai_workflow._load_events(task_dir)
    assert len(events) == 2
    doctor_count = sum(1 for e in events if e.get("command") == "doctor")
    dry_run_count = sum(1 for e in events if e.get("command") == "finalize_dry_run")
    assert doctor_count == 1
    assert dry_run_count == 1


def test_export_experiment_missing_log_returns_zero_summary(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, name="sample_task", date="20260510")
    capsys.readouterr()
    rc = ai_workflow.export_experiment_command(root, str(task_dir))
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["schema_version"] == "aiwf-experiment-v0.1"
    assert payload["run_summary"]["event_count"] == 0
    assert payload["context"]["source"] == "current_env"
    assert payload["context"]["consistent"] is True


def test_check_path_logs_event_and_repo_wide_does_not_append(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, name="sample_task", date="20260510")
    (root / ".env").write_text(
        "\n".join(
            [
                "AIWF_EVENT_LOG=1",
                "AIWF_WORKFLOW_MODE=aiwf_deterministic",
                "AIWF_MODEL_NAME=test-model",
                "AIWF_MODEL_CLASS=local_quantized",
                "AIWF_MODEL_PROVIDER=test-provider",
                "AIWF_ACTOR=codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc_task = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc_task == 0
    event_path = task_dir / ".aiwf" / "events.jsonl"
    lines_after_task_check = [line for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines_after_task_check) == 1
    task_event = json.loads(lines_after_task_check[0])
    assert task_event["command"] == "check"

    rc_repo = ai_workflow.check_repo(root, strict=False)
    assert rc_repo == 0
    lines_after_repo_check = [line for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines_after_repo_check) == 1


def test_export_experiment_uses_event_context_when_events_exist(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, name="sample_task", date="20260510")
    (root / ".env").write_text(
        "\n".join(
            [
                "AIWF_EVENT_LOG=1",
                "AIWF_WORKFLOW_MODE=aiwf_deterministic",
                "AIWF_MODEL_NAME=test-model",
                "AIWF_MODEL_CLASS=local_quantized",
                "AIWF_MODEL_PROVIDER=test-provider",
                "AIWF_ACTOR=codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ai_workflow.doctor_command(root, str(task_dir))
    (root / ".env").write_text(
        "\n".join(
            [
                "AIWF_EVENT_LOG=1",
                "AIWF_WORKFLOW_MODE=prompt_only",
                "AIWF_MODEL_NAME=changed-model",
                "AIWF_MODEL_CLASS=cheap_api",
                "AIWF_MODEL_PROVIDER=changed-provider",
                "AIWF_ACTOR=codex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    rc = ai_workflow.export_experiment_command(root, str(task_dir))
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["context"]["source"] == "events"
    assert payload["context"]["consistent"] is True
    assert payload["context"]["workflow_mode"] == "aiwf_deterministic"
    assert payload["context"]["model"]["name"] == "test-model"
    assert payload["context"]["model"]["class"] == "local_quantized"
    assert payload["context"]["model"]["provider"] == "test-provider"


def test_sync_index_repairs_active_status_and_keeps_unrelated_entries(tmp_path: Path):
    root = _init_repo(tmp_path)
    t1 = _create_task(root, name="task_one", date="20260511")
    t2 = _create_task(root, name="task_two", date="20260511")
    _rewrite_task_metadata(t1 / "task.md", status="active")
    _set_index_status_for_task(t1, "Done")
    before_other = _task_index_line(t2)

    rc = ai_workflow.sync_index_command(root, str(t1))
    assert rc == 0
    assert "status: Active" in _task_index_line(t1)
    assert _task_index_line(t2) == before_other


def test_check_detects_stale_index_status(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260511")
    _rewrite_task_metadata(task_dir / "task.md", status="review", workflow_phase="validation")
    _set_index_status_for_task(task_dir, "Done")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    out = capsys.readouterr().out
    assert rc == 2
    assert "INDEX_STATUS_STALE" in out


def test_finalize_blocked_by_stale_index_without_mutating_index(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260511")
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _set_index_status_for_task(task_dir, "Done")
    before = (task_dir.parent / "index.md").read_text(encoding="utf-8")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    after = (task_dir.parent / "index.md").read_text(encoding="utf-8")
    assert rc == 2
    assert before == after


def test_done_requires_finalized_at_for_done_index_projection(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260511")
    _rewrite_task_metadata(
        task_dir / "task.md",
        status="done",
        review_status="pass",
        workflow_phase="finalized",
        finalized_at=None,
        finalized_by=None,
    )
    _set_index_status_for_task(task_dir, "Done")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    out = capsys.readouterr().out
    assert rc == 2
    assert "INDEX_STATUS_INVALID_DONE" in out


def test_check_passes_when_index_projection_matches(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260511")
    _rewrite_task_metadata(task_dir / "task.md", status="review", workflow_phase="validation")
    _set_index_status_for_task(task_dir, "Review")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def _read_task_metadata(task_dir: Path) -> dict[str, object]:
    metadata, _body = ai_workflow.parse_front_matter((task_dir / "task.md").read_text(encoding="utf-8"))
    return metadata


def _events_lines(task_dir: Path) -> list[dict[str, object]]:
    event_path = task_dir / ".aiwf" / "events.jsonl"
    if not event_path.exists():
        return []
    out: list[dict[str, object]] = []
    for line in event_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        out.append(json.loads(raw))
    return out


def _write_repo_event_log(root: Path, *lines: str) -> Path:
    event_path = root / ".aiwf" / "events" / "events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return event_path


def _write_task_event_log(task_dir: Path, *events_or_lines: object) -> Path:
    event_path = task_dir / ".aiwf" / "events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item) for item in events_or_lines]
    event_path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return event_path


def _run_dataset_export(root: Path, output_name: str = "dataset.json") -> dict[str, object]:
    output_path = root / output_name
    rc = ai_workflow.dataset_export_command(root, output_name, "json")
    assert rc == 0
    return json.loads(output_path.read_text(encoding="utf-8"))


def _run_package_records_dry_run(
    root: Path,
    output_name: str = "package_manifest.json",
    extra_args: list[str] | None = None,
) -> dict[str, object]:
    output_path = _run_package_records_dry_run_file(root, output_name, extra_args)
    return json.loads(output_path.read_text(encoding="utf-8"))


def _run_package_records_dry_run_file(
    root: Path,
    output_name: str = "package_manifest.json",
    extra_args: list[str] | None = None,
) -> Path:
    output_path = root / output_name
    args = [
        "--repo-root",
        str(root),
        "package",
        "records",
        "--dry-run",
        "--output",
        str(output_path),
    ]
    if extra_args:
        args.extend(extra_args)
    rc = ai_workflow.main(args)
    assert rc == 0
    return output_path


def _event_result_status(event: dict[str, object]) -> str:
    result = event.get("result")
    if isinstance(result, dict):
        return str(result.get("status", ""))
    return str(result)


def test_transition_valid_implementation_to_validation(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")

    rc = ai_workflow.transition_command(root, str(task_dir), "validation")
    assert rc == 0
    metadata = _read_task_metadata(task_dir)
    assert metadata["workflow_phase"] == "validation"
    assert metadata["phase_entered_at"]
    events = _events_lines(task_dir)
    assert any(e.get("event") == "phase_transition" and e.get("from") == "implementation" and e.get("to") == "validation" for e in events)


def test_transition_invalid_implementation_to_finalized(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")

    rc = ai_workflow.transition_command(root, str(task_dir), "finalized")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PHASE-002" in out
    metadata = _read_task_metadata(task_dir)
    assert metadata["workflow_phase"] == "implementation"


def test_transition_after_finalized_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="ok") == 0
    _sync_index(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0

    rc = ai_workflow.transition_command(root, str(task_dir), "validation")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PHASE-004" in out


def test_record_validation_pass_event(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    marker = tmp_path / "aiwf_command_marker"

    rc = ai_workflow.record_command(
        root,
        str(task_dir),
        kind="validation",
        result="pass",
        command=f"echo SHOULD_NOT_RUN > {marker}",
        reviewer=None,
        summary=None,
    )
    assert rc == 0
    assert not marker.exists()
    events = _events_lines(task_dir)
    assert any(e.get("event") == "validation_recorded" and _event_result_status(e) == "pass" for e in events)


def test_record_review_fail_event(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")

    rc = ai_workflow.record_command(root, str(task_dir), kind="review", result="fail", command=None, reviewer="codex", summary="blocker")
    assert rc == 0
    events = _events_lines(task_dir)
    assert any(e.get("event") == "review_recorded" and _event_result_status(e) == "fail" for e in events)


def test_record_fix_event(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")

    rc = ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="fixed issue")
    assert rc == 0
    events = _events_lines(task_dir)
    assert any(e.get("event") == "fix_recorded" for e in events)


def test_record_invalid_kind_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")

    rc = ai_workflow.record_command(root, str(task_dir), kind="unknown", result=None, command=None, reviewer=None, summary=None)
    assert rc == 2


def test_record_invalid_result_fails(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")

    rc_validation = ai_workflow.record_command(root, str(task_dir), kind="validation", result="bad", command=None, reviewer=None, summary=None)
    rc_review = ai_workflow.record_command(root, str(task_dir), kind="review", result="bad", command=None, reviewer=None, summary=None)
    assert rc_validation == 2
    assert rc_review == 2


def test_v16_finalize_without_validation_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-010" in out


def test_v16_finalize_without_review_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-014" in out


def test_v16_finalize_with_validation_and_review_pass_succeeds(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="review passed") == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0
    metadata = _read_task_metadata(task_dir)
    assert metadata["status"] == "done"
    assert metadata["workflow_phase"] == "finalized"
    assert metadata["finalized_at"]
    events = _events_lines(task_dir)
    finalize_success = [e for e in events if e.get("event") == "finalize_success"]
    assert finalize_success
    assert isinstance(finalize_success[-1].get("artifact_manifest"), dict)


def test_review_fail_without_fix_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="fail", command=None, reviewer="codex", summary="fail") == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-011" in out


def test_fix_without_revalidation_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="fail", command=None, reviewer="codex", summary="fail") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="fixed") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass") == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-012" in out


def test_review_fail_fix_revalidation_review_pass_finalize_succeeds(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="fail", command=None, reviewer="codex", summary="fail") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="fixed") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass") == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0


def test_v16_stale_review_pass_after_fix_blocks_finalize(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass before fix") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="follow-up change") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-014" in out


def test_v16_review_pass_after_fix_can_finalize(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass before fix") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="follow-up change") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass after fix") == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0


def test_v16_review_fail_fix_revalidation_without_new_review_pass_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="fail", command=None, reviewer="codex", summary="fail") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="fixed") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0

    before_task = (task_dir / "task.md").read_text(encoding="utf-8")
    before_index = (task_dir.parent / "index.md").read_text(encoding="utf-8")
    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    after_task = (task_dir / "task.md").read_text(encoding="utf-8")
    after_index = (task_dir.parent / "index.md").read_text(encoding="utf-8")

    assert rc == 2
    assert "AIWF-PATH-014" in out
    assert before_task == after_task
    assert before_index == after_index
    metadata = _read_task_metadata(task_dir)
    assert metadata["status"] != "done"
    assert metadata["workflow_phase"] != "finalized"
    assert metadata["finalized_at"] is None
    assert metadata["finalized_by"] is None


def test_v16_latest_review_fail_blocks_finalize_even_with_old_review_pass(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="fail", command=None, reviewer="codex", summary="fail") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="fixed") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-014" in out


def test_v16_finalize_failure_does_not_partially_finalize_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)

    before_task = (task_dir / "task.md").read_text(encoding="utf-8")
    before_index = (task_dir.parent / "index.md").read_text(encoding="utf-8")
    rc = ai_workflow.finalize_command(root, str(task_dir))
    after_task = (task_dir / "task.md").read_text(encoding="utf-8")
    after_index = (task_dir.parent / "index.md").read_text(encoding="utf-8")

    assert rc == 2
    assert before_task == after_task
    assert before_index == after_index
    metadata = _read_task_metadata(task_dir)
    assert metadata["status"] != "done"
    assert metadata["workflow_phase"] != "finalized"
    assert metadata["finalized_at"] is None
    assert metadata["finalized_by"] is None
    events = _events_lines(task_dir)
    assert not any(e.get("event") == "finalize_success" for e in events)


def test_v16_review_status_fail_blocks_finalize(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass") == 0
    _rewrite_task_metadata(task_dir / "task.md", review_status="fail")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-018" in out
    metadata = _read_task_metadata(task_dir)
    assert metadata["status"] != "done"
    assert metadata["workflow_phase"] != "finalized"


def test_v16_review_status_not_required_mismatch_with_latest_pass_blocks_finalize(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="pass") == 0
    _rewrite_task_metadata(task_dir / "task.md", review_status="not_required", review_not_required_reason="manual override")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-018" in out


def test_v16_review_status_pass_mismatch_with_latest_not_required_blocks_finalize(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="not_required", command=None, reviewer="human", summary="doc-only") == 0
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-018" in out


def test_v16_review_not_required_before_fix_does_not_allow_finalize(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(
        root,
        str(task_dir),
        kind="review",
        result="not_required",
        command=None,
        reviewer="human",
        summary="doc-only change",
    ) == 0
    assert ai_workflow.record_command(
        root,
        str(task_dir),
        kind="fix",
        result=None,
        command=None,
        reviewer=None,
        summary="changed after review not_required decision",
    ) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0

    before_task = (task_dir / "task.md").read_text(encoding="utf-8")
    before_index = (task_dir.parent / "index.md").read_text(encoding="utf-8")
    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    after_task = (task_dir / "task.md").read_text(encoding="utf-8")
    after_index = (task_dir.parent / "index.md").read_text(encoding="utf-8")
    assert rc == 2
    assert "AIWF-PATH-014" in out
    assert before_task == after_task
    assert before_index == after_index
    metadata = _read_task_metadata(task_dir)
    assert metadata["status"] != "done"
    assert metadata["workflow_phase"] != "finalized"
    assert metadata["finalized_at"] is None
    assert metadata["finalized_by"] is None
    events = _events_lines(task_dir)
    assert not any(e.get("event") == "finalize_success" for e in events)


def test_v16_review_not_required_after_fix_can_finalize(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="not_required", command=None, reviewer="human", summary="doc-only change") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="post-review doc update") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="not_required", command=None, reviewer="human", summary="still doc-only after fix") == 0

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0
    metadata = _read_task_metadata(task_dir)
    assert metadata["status"] == "done"
    assert metadata["workflow_phase"] == "finalized"


def test_v16_finalized_metadata_without_finalize_success_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _rewrite_task_metadata(
        task_dir / "task.md",
        status="done",
        review_status="pass",
        workflow_phase="finalized",
        finalized_at="2026-05-12T00:00:00Z",
        finalized_by="tool",
    )
    _sync_index(root, task_dir)

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-013" in out


def test_v16_manifest_hash_mismatch_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="ok") == 0
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0
    (task_dir / "review_final.md").write_text("changed after finalize\n", encoding="utf-8")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-015" in out
    assert "Revert post-finalize edits" in out
    assert "controlled amend/reopen command if supported" in out


def test_v15_missing_path_events_warn_only(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _rewrite_task_metadata(task_dir / "task.md", schema_version="ai-workflow-v1.5", review_status="pass", status="review", workflow_phase="validation")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)

    rc_check = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc_check == 0
    rc_finalize = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc_finalize == 0
    assert "AIWF-PATH-013" not in out


def test_legacy_task_warns_not_errors(tmp_path: Path):
    root = _init_repo(tmp_path)
    day_dir = root / "docs" / "ai_20260512"
    task_dir = day_dir / "001_legacy_case"
    task_dir.mkdir(parents=True)
    (task_dir / "task.md").write_text("# legacy\n", encoding="utf-8")
    for name in ["agent.md", "task_record.md", "self_validation.md", "review_codex.md", "review_final.md"]:
        (task_dir / name).write_text("ok\n", encoding="utf-8")
    (day_dir / "index.md").write_text("- `001` `001_legacy_case` | status: Draft\n", encoding="utf-8")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_v16_finalize_with_malformed_event_log_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    _write_finalize_ready_docs(task_dir)
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="ok") == 0
    event_path = task_dir / ".aiwf" / "events.jsonl"
    with event_path.open("a", encoding="utf-8") as f:
        f.write("{bad json line}\n")

    rc = ai_workflow.finalize_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-016" in out


def test_export_experiment_with_malformed_event_log_warns(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260512")
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    event_path = task_dir / ".aiwf" / "events.jsonl"
    with event_path.open("a", encoding="utf-8") as f:
        f.write("{bad json line}\n")

    capsys.readouterr()
    rc = ai_workflow.export_experiment_command(root, str(task_dir))
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0
    assert payload["run_summary"]["event_count"] >= 1
    assert "malformed event line" in captured.err.lower()


def test_record_fix_after_finalized_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0

    rc = ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="post-finalize fix")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-FINALIZED-002" in out


def test_record_validation_after_finalized_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0

    rc = ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-FINALIZED-002" in out


def test_record_review_after_finalized_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0

    rc = ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="post-finalize review")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-FINALIZED-002" in out


def test_record_safety_ack_after_finalized_fails(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0

    rc = ai_workflow.record_command(root, str(task_dir), kind="safety_ack", result=None, command=None, reviewer=None, summary="post-finalize ack")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-FINALIZED-002" in out


def test_post_finalize_fix_event_blocks_finalize_ready(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0
    ai_workflow._append_raw_event(
        root,
        task_dir,
        {
            "event": "fix_recorded",
            "result": "ok",
        },
    )

    rc = ai_workflow.check_path(root, str(task_dir), strict=False, finalize_ready=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-019" in out


def test_post_finalize_review_event_blocks_doctor(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0
    ai_workflow._append_raw_event(
        root,
        task_dir,
        {
            "event": "review_recorded",
            "result": "pass",
        },
    )

    rc = ai_workflow.doctor_command(root, str(task_dir))
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-019" in out


def test_legacy_post_finalize_event_format_is_detected(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    assert ai_workflow.finalize_command(root, str(task_dir)) == 0
    ai_workflow._append_raw_event(
        root,
        task_dir,
        {
            "event": "validation_recorded",
            "result": "pass",
        },
    )

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-019" in out


def test_check_finalize_ready_catches_stale_review(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="initial pass") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="fix", result=None, command=None, reviewer=None, summary="follow-up change") == 0
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest -q", reviewer=None, summary=None) == 0

    rc = ai_workflow.check_path(root, str(task_dir), strict=False, finalize_ready=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-014" in out


def test_check_finalize_ready_catches_missing_validation(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="review pass") == 0

    rc = ai_workflow.check_path(root, str(task_dir), strict=False, finalize_ready=True)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-PATH-010" in out


def test_check_default_behavior_unchanged(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")

    rc = ai_workflow.check_path(root, str(task_dir), strict=False)
    assert rc == 0


def test_evidence_event_schema_v02_contains_required_fields(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_v2_task(root, date="20260513")

    rc = ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="review passed")
    assert rc == 0
    events = _events_lines(task_dir)
    event = events[-1]
    assert event["schema_version"] == "aiwf-event-v0.2"
    assert event["tool_version"] == ai_workflow.AIWF_TOOL_VERSION
    assert ai_workflow.WORKFLOW_PROTOCOL_VERSION == "1.7.8"
    assert event["event_type"] == "review_recorded"
    assert event["event_group"] == "evidence"
    assert event["task_path"].startswith(".aiwf/records/ai_")
    assert isinstance(event["result"], dict)
    assert event["result"]["status"] == "pass"
    assert isinstance(event["payload"], dict)
    assert event["payload"]["kind"] == "review"


def test_historical_event_records_are_not_rewritten(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    # Legacy layout compatibility assertion.
    legacy_event = {
        "schema_version": "aiwf-event-v0.1",
        "timestamp": "2026-05-13T00:00:00Z",
        "tool_version": "1.6.1",
        "command": "legacy_check",
        "task_path": f"docs/ai_20260513/{task_dir.name}",
        "workflow_mode": "legacy_mode",
        "actor": "legacy_actor",
        "model": {"name": "legacy", "class": "legacy", "provider": "legacy"},
        "result": {"exit_code": 0, "status": "ok"},
        "diagnostics": {"errors": 0, "warnings": 0, "finalize_blockers": 0, "codes": []},
    }
    ai_workflow._append_raw_event(root, task_dir, legacy_event)

    assert ai_workflow.record_command(root, str(task_dir), kind="review", result="pass", command=None, reviewer="human", summary="new review") == 0
    events = _events_lines(task_dir)
    assert len(events) == 2
    assert events[0]["tool_version"] == "1.6.1"
    assert events[0]["command"] == "legacy_check"
    assert events[1]["tool_version"] == ai_workflow.AIWF_TOOL_VERSION


def test_review_freshness_accepts_legacy_and_v02_events(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _write_finalize_ready_docs(task_dir)
    _rewrite_task_metadata(task_dir / "task.md", review_status="pass", status="review", workflow_phase="validation")
    _sync_index(root, task_dir)
    ai_workflow._append_raw_event(root, task_dir, {"event": "validation_recorded", "result": "pass"})
    ai_workflow._append_evidence_event(
        root,
        task_dir,
        {
            "event_type": "review_recorded",
            "result": "pass",
            "kind": "review",
            "summary": "mixed-format review pass",
        },
    )

    rc = ai_workflow.finalize_command(root, str(task_dir), dry_run=True)
    assert rc == 0


def test_report_json_contains_summary_metrics(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    assert ai_workflow.record_command(root, str(task_dir), kind="validation", result="pass", command="pytest", reviewer=None, summary=None) == 0

    capsys.readouterr()
    rc = ai_workflow.report_command(root, "docs", "json")
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    summary = payload["summary"]
    assert "task_count" in summary
    assert "event_backed_task_count" in summary
    assert "post_finalize_event_count" in summary
    assert "diagnostic_code_ranking" in payload


def test_report_markdown_contains_summary_table(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    _create_task(root, date="20260513")

    capsys.readouterr()
    rc = ai_workflow.report_command(root, "docs", "markdown")
    out = capsys.readouterr().out
    assert rc == 0
    assert "# AIWF Report" in out
    assert "| Metric | Value |" in out
    assert "| Code | Count |" in out
    assert "| Date | Task | Status | Phase | Review | Events |" in out


def test_report_counts_malformed_events_without_crash(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    event_path = task_dir / ".aiwf" / "events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text("{broken-json}\n", encoding="utf-8")

    capsys.readouterr()
    rc = ai_workflow.report_command(root, "docs", "json")
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["summary"]["malformed_event_count"] == 1


def test_finalize_appends_implicit_phase_transition(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)

    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 0
    events = _events_lines(task_dir)
    transition_events = [e for e in events if e.get("event_type") == "phase_transition" and bool(e.get("implicit"))]
    assert transition_events
    assert transition_events[-1]["from"] == "validation"
    assert transition_events[-1]["to"] == "finalized"
    assert transition_events[-1]["reason"] == "finalize"


def test_finalize_blocks_malformed_related_tasks_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(
        root,
        "finalize_bad_related_tasks",
        "20260604",
        update_existing=False,
        allow_non_today_date=True,
    )
    assert rc == 0
    task_dir = root / "docs" / "ai_20260604" / "001_finalize_bad_related_tasks"
    _prepare_finalize_ready_task(root, task_dir)
    metadata = ai_workflow.load_task_metadata(task_dir)["metadata"]
    metadata["related_tasks"] = ['\\"014\\"']
    ai_workflow._rewrite_task_metadata_file(task_dir, metadata)
    rc = ai_workflow.finalize_command(root, str(task_dir))
    assert rc == 2
    metadata_after = ai_workflow.load_task_metadata(task_dir)["metadata"]
    assert metadata_after["workflow_phase"] != "finalized"
    assert metadata_after["finalized_at"] is None


def test_finalize_rolls_back_metadata_when_index_sync_fails(tmp_path: Path, monkeypatch):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    _prepare_finalize_ready_task(root, task_dir)
    before = (task_dir / "task.md").read_text(encoding="utf-8")

    def _raise_sync_error(_root: Path, _task_dir: Path):
        raise ai_workflow.SyncIndexError("INDEX_ENTRY_MISSING", "simulated sync failure")

    monkeypatch.setattr(ai_workflow, "_sync_index_entry_status", _raise_sync_error)
    rc = ai_workflow.finalize_command(root, str(task_dir))
    after = (task_dir / "task.md").read_text(encoding="utf-8")
    metadata = _read_task_metadata(task_dir)

    assert rc == 2
    assert before == after
    assert metadata["status"] == "review"
    assert metadata["workflow_phase"] == "validation"


def test_resolve_ai_agent_metadata_order_shell_over_local_over_profile(tmp_path: Path):
    root = _init_repo(tmp_path)
    profiles_dir = root / ".aiwf" / "metadata_profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "base.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=cline",
                "AIWF_MODEL_PROVIDER=anthropic",
                "AIWF_MODEL_NAME=claude-sonnet",
                "AIWF_REASONING_EFFORT=medium",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=medium",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("base\n", encoding="utf-8")
    (root / ".aiwf" / "metadata.local.env").write_text(
        "\n".join(
            [
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_METADATA_SOURCE=local_env",
                "AIWF_METADATA_CONFIDENCE=high",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    metadata = ai_workflow.resolve_ai_agent_metadata(
        root,
        shell_env={
            "AIWF_AGENT_TOOL": "codex",
            "AIWF_MODEL_NAME": "gpt-5.3-codex",
            "AIWF_METADATA_SOURCE": "shell_env",
        },
    )
    assert metadata["tool"] == "codex"
    assert metadata["provider"] == "openai"
    assert metadata["model_name"] == "gpt-5.3-codex"
    assert metadata["reasoning_effort"] == "medium"
    assert metadata["source"] == "shell_env"
    assert metadata["confidence"] == "high"


def _set_metadata_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tool: str = "copilot",
    provider: str = "openai",
    model_name: str = "test-model",
    reasoning_effort: str = "high",
    source: str = "explicit_env",
    confidence: str = "medium",
) -> None:
    monkeypatch.setenv("AIWF_AGENT_TOOL", tool)
    monkeypatch.setenv("AIWF_MODEL_PROVIDER", provider)
    monkeypatch.setenv("AIWF_MODEL_NAME", model_name)
    monkeypatch.setenv("AIWF_REASONING_EFFORT", reasoning_effort)
    monkeypatch.setenv("AIWF_METADATA_SOURCE", source)
    monkeypatch.setenv("AIWF_METADATA_CONFIDENCE", confidence)


def test_metadata_allowed_values_lists_fields(capsys):
    rc = ai_workflow.metadata_allowed_values_command(Path("."), field=None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "provider" in out
    assert "tool" in out
    assert "source" in out
    assert "confidence" in out
    assert "reasoning_effort" in out
    assert "model_name" in out
    assert "default:" in out


def test_metadata_allowed_values_field_provider(capsys):
    rc = ai_workflow.metadata_allowed_values_command(Path("."), field="provider")
    out = capsys.readouterr().out
    assert rc == 0
    assert "deepseek" in out
    assert "openai" in out
    assert "custom" in out
    assert "other" in out
    assert "default: unknown" in out


def test_metadata_allowed_values_field_source_explains_values(capsys):
    rc = ai_workflow.metadata_allowed_values_command(Path("."), field="source")
    out = capsys.readouterr().out
    assert rc == 0
    assert "explicit_env" in out
    assert "shell_env" in out
    assert "local_env" in out
    assert "profile" in out
    assert "Where AIWF obtained the metadata" in out


@pytest.mark.parametrize("token", ["?", ":list", ":help", "L", "l"])
def test_metadata_init_help_token_predicates(token: str):
    assert ai_workflow._is_metadata_init_field_help_token(token)
    assert not ai_workflow._is_metadata_init_all_help_token(token)


def test_metadata_init_field_help_reprompts_and_does_not_persist_control_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    root = _init_repo(tmp_path)
    prompts: list[str] = []
    responses = iter(["?", "codex", "", "", "", "", ""])

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    rc = ai_workflow.metadata_init_command(root)
    out = capsys.readouterr().out
    metadata_text = (root / ".aiwf" / "metadata.local.env").read_text(encoding="utf-8")

    assert rc == 0
    assert "Allowed values for AIWF_AGENT_TOOL:" in out
    assert "Description:" in out
    assert "Current default:" in out
    assert prompts[0] == "AIWF_AGENT_TOOL [unknown] (? for allowed values): "
    assert prompts[1] == prompts[0]
    assert "AIWF_AGENT_TOOL=codex" in metadata_text
    assert "AIWF_AGENT_TOOL=?" not in metadata_text


def test_metadata_init_all_help_reprompts_same_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    root = _init_repo(tmp_path)
    prompts: list[str] = []
    responses = iter([":all", "", "", "", "", "", ""])

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    rc = ai_workflow.metadata_init_command(root)
    out = capsys.readouterr().out
    metadata_text = (root / ".aiwf" / "metadata.local.env").read_text(encoding="utf-8")

    assert rc == 0
    assert "tool" in out
    assert "provider" in out
    assert "model_name" in out
    assert prompts[0] == "AIWF_AGENT_TOOL [unknown] (? for allowed values): "
    assert prompts[1] == prompts[0]
    assert ":all" not in metadata_text


def test_metadata_init_model_name_help_reports_free_form_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    root = _init_repo(tmp_path)
    responses = iter(["", "", "?", "gpt-5.6", "", "", ""])

    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))

    rc = ai_workflow.metadata_init_command(root)
    out = capsys.readouterr().out
    metadata_text = (root / ".aiwf" / "metadata.local.env").read_text(encoding="utf-8")

    assert rc == 0
    assert "Allowed values for AIWF_MODEL_NAME:" in out
    assert "This field may be free-form or model-specific." in out
    assert "AIWF_MODEL_NAME=gpt-5.6" in metadata_text


def test_metadata_validate_reports_invalid_values(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata.local.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=bad_tool",
                "AIWF_MODEL_PROVIDER=bad_provider",
                "AIWF_MODEL_NAME=any",
                "AIWF_REASONING_EFFORT=maximum",
                "AIWF_METADATA_SOURCE=bad_source",
                "AIWF_METADATA_CONFIDENCE=bad_confidence",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    rc = ai_workflow.metadata_validate_command(root)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-META-001" in out
    assert "AIWF-META-002" in out
    assert "AIWF-META-003" in out
    assert "AIWF-META-004" in out
    assert "AIWF-META-012" in out
    assert "allowed-values --field provider" in out
    assert "allowed-values --field tool" in out
    assert "allowed-values --field source" in out
    assert "allowed-values --field confidence" in out
    assert "allowed-values --field reasoning_effort" in out


@pytest.mark.parametrize(
    "provider",
    [
        "openai",
        "anthropic",
        "google",
        "azure",
        "deepseek",
        "mistral",
        "qwen",
        "baidu",
        "zhipu",
        "moonshot",
        "minimax",
        "openrouter",
        "ollama",
        "local",
        "self_hosted",
        "custom",
        "other",
    ],
)
def test_metadata_validate_allows_common_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str):
    _set_metadata_env(monkeypatch, provider=provider)
    assert ai_workflow.metadata_validate_command(tmp_path) == 0


def test_metadata_validate_invalid_provider_shows_allowed_values_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    _set_metadata_env(monkeypatch, provider="deepseak")
    rc = ai_workflow.metadata_validate_command(tmp_path)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-META-003" in out
    assert "allowed-values --field provider" in out


@pytest.mark.parametrize(
    "tool",
    [
        "codex",
        "chatgpt",
        "copilot",
        "cursor",
        "cline",
        "claude_code",
        "aider",
        "continue",
        "openhands",
        "opencode",
        "custom_agent",
        "script",
        "manual",
        "other",
    ],
)
def test_metadata_validate_allows_common_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str):
    _set_metadata_env(monkeypatch, tool=tool)
    assert ai_workflow.metadata_validate_command(tmp_path) == 0


def test_metadata_validate_invalid_tool_shows_allowed_values_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    _set_metadata_env(monkeypatch, tool="vscode-agent")
    rc = ai_workflow.metadata_validate_command(tmp_path)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-META-004" in out
    assert "allowed-values --field tool" in out


@pytest.mark.parametrize("effort", ["unknown", "none", "low", "medium", "high", "auto"])
def test_metadata_validate_allows_reasoning_effort_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effort: str,
):
    _set_metadata_env(
        monkeypatch,
        provider="deepseek",
        model_name="deepseek-v4-flash",
        reasoning_effort=effort,
    )
    assert ai_workflow.metadata_validate_command(tmp_path) == 0


def test_metadata_validate_rejects_invalid_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    _set_metadata_env(
        monkeypatch,
        provider="deepseek",
        model_name="deepseek-v4-flash",
        reasoning_effort="maximum",
    )
    rc = ai_workflow.metadata_validate_command(tmp_path)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-META-012" in out
    assert "allowed-values --field reasoning_effort" in out


def test_metadata_value_registry_defaults_are_documented():
    assert ai_workflow.METADATA_VALUE_REGISTRY["tool"]["default"] == "unknown"
    assert ai_workflow.METADATA_VALUE_REGISTRY["provider"]["default"] == "unknown"
    assert ai_workflow.METADATA_VALUE_REGISTRY["model_name"]["default"] == "unknown"
    assert ai_workflow.METADATA_VALUE_REGISTRY["reasoning_effort"]["default"] == "unknown"
    assert ai_workflow.METADATA_VALUE_REGISTRY["source"]["default"] == "explicit_env"
    assert ai_workflow.METADATA_VALUE_REGISTRY["confidence"]["default"] == "medium"


def test_metadata_profile_lifecycle_commands(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata.local.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.3-codex",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert ai_workflow.metadata_profile_create_command(root, "codex_high") == 0
    profile_text = (root / ".aiwf" / "metadata_profiles" / "codex_high.env").read_text(encoding="utf-8")
    assert "AIWF_AGENT_TOOL=codex" in profile_text
    assert "AIWF_MODEL_PROVIDER=openai" in profile_text
    assert "AIWF_METADATA_SOURCE=profile" in profile_text
    assert "AIWF_EVENT_LOG=1" in profile_text
    capsys.readouterr()
    assert ai_workflow.metadata_profile_list_command(root) == 0
    listed = capsys.readouterr().out
    assert "codex_high" in listed
    assert ai_workflow.metadata_profile_use_command(root, "codex_high") == 0
    capsys.readouterr()
    assert ai_workflow.metadata_profile_current_command(root) == 0
    current = capsys.readouterr().out.strip()
    assert current == "codex_high"


def test_load_aiwf_env_active_profile_event_log_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _init_repo(tmp_path)
    profiles_dir = root / ".aiwf" / "metadata_profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "base.env").write_text("AIWF_EVENT_LOG=1\n", encoding="utf-8")
    (root / ".aiwf" / "metadata.current").write_text("base\n", encoding="utf-8")
    (root / ".env").write_text("AIWF_EVENT_LOG=0\n", encoding="utf-8")
    monkeypatch.setenv("AIWF_EVENT_LOG", "1")

    loaded = ai_workflow.load_aiwf_env(root)
    assert loaded["AIWF_EVENT_LOG"] == "1"

    monkeypatch.delenv("AIWF_EVENT_LOG")
    loaded = ai_workflow.load_aiwf_env(root)
    assert loaded["AIWF_EVENT_LOG"] == "0"

    (root / ".env").unlink()
    loaded = ai_workflow.load_aiwf_env(root)
    assert loaded["AIWF_EVENT_LOG"] == "1"


def test_metadata_profile_show_current_profile(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")

    rc = ai_workflow.metadata_profile_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Current Profile: gpt_5_4_high" in out
    assert "Profile File Exists: yes" in out
    assert "Model: gpt-5.4" in out
    assert "AIWF_EVENT_LOG: 1" in out


def test_metadata_profile_show_specified_profile(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "deepseek_v4_flash.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=copilot",
                "AIWF_MODEL_PROVIDER=deepseek",
                "AIWF_MODEL_NAME=deepseek-v4-flash",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=medium",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = ai_workflow.metadata_profile_show_command(root, "deepseek_v4_flash")
    out = capsys.readouterr().out
    assert rc == 0
    assert "Profile: deepseek_v4_flash" in out
    assert "Provider: deepseek" in out
    assert "Model: deepseek-v4-flash" in out


def test_metadata_profile_show_missing_current_profile_warns(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata.current").write_text("missing_profile\n", encoding="utf-8")

    rc = ai_workflow.metadata_profile_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF-META-PROFILE-004" in out
    assert "Profile File Exists: no" in out


def test_metadata_show_compact_active_profile_uniform_source(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")

    rc = ai_workflow.metadata_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Active Profile: gpt_5_4_high" in out
    assert "Resolution: effective metadata comes from active profile." in out
    assert "Source: .aiwf/metadata_profiles/gpt_5_4_high.env" in out
    assert out.count("Source: .aiwf/metadata_profiles/gpt_5_4_high.env") == 1
    assert "Effective Metadata:" in out
    assert "Tool: codex" in out
    assert "Provider: openai" in out
    assert "Model: gpt-5.4" in out
    assert "from: .aiwf/metadata_profiles/gpt_5_4_high.env" not in out


def test_metadata_show_compact_local_override_uniform_source(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=medium",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")
    (root / ".aiwf" / "metadata.local.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.5",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = ai_workflow.metadata_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Active Profile: gpt_5_4_high" in out
    assert "Resolution: effective metadata is overridden by .aiwf/metadata.local.env." in out
    assert "Source: .aiwf/metadata.local.env" in out
    assert out.count("Source: .aiwf/metadata.local.env") == 1
    assert "Model: gpt-5.5" in out
    assert "from: .aiwf/metadata.local.env" not in out


def test_metadata_show_compact_shell_override_uniform_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=medium",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")
    _set_metadata_env(
        monkeypatch,
        tool="copilot",
        provider="deepseek",
        model_name="deepseek-v4-flash",
        reasoning_effort="high",
        source="explicit_env",
        confidence="medium",
    )

    rc = ai_workflow.metadata_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Active Profile: gpt_5_4_high" in out
    assert "Resolution: effective metadata is overridden by shell env." in out
    assert "Source: shell env" in out
    assert out.count("Source: shell env") == 1
    assert "Tool: copilot" in out
    assert "Model: deepseek-v4-flash" in out
    assert "from: shell env" not in out


def test_metadata_show_compact_default_uniform_source(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)

    rc = ai_workflow.metadata_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Active Profile: none" in out
    assert "Resolution: effective metadata comes from built-in defaults." in out
    assert "Source: built-in default" in out
    assert out.count("Source: built-in default") == 1
    assert "Model: unknown" in out


def test_metadata_show_mixed_source_keeps_per_field_from_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")
    monkeypatch.setenv("AIWF_MODEL_NAME", "deepseek-v4-flash")

    rc = ai_workflow.metadata_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Resolution: effective metadata has mixed sources." in out
    assert "Source: .aiwf/metadata_profiles/gpt_5_4_high.env" not in out
    assert "Model: deepseek-v4-flash" in out
    assert "from: shell env" in out
    assert "Tool: codex" in out
    assert "from: .aiwf/metadata_profiles/gpt_5_4_high.env" in out


def test_metadata_status_compact_uniform_source_and_runtime_option(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")

    rc = ai_workflow.metadata_status_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Active Profile:" in out
    assert "Effective Metadata:" in out
    assert "Runtime Options:" in out
    assert "AIWF_EVENT_LOG: 1" in out
    assert "  Source: .aiwf/metadata_profiles/gpt_5_4_high.env" in out
    assert out.count("from: .aiwf/metadata_profiles/gpt_5_4_high.env") == 1
    assert "active profile provides the effective metadata baseline" in out


def test_metadata_status_mixed_source_keeps_per_field_from_lines(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_4_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.4",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_4_high\n", encoding="utf-8")
    (root / ".aiwf" / "metadata.local.env").write_text(
        "\n".join(
            [
                "AIWF_MODEL_NAME=gpt-5.5",
                "AIWF_METADATA_SOURCE=explicit_env",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = ai_workflow.metadata_status_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Effective Metadata:" in out
    assert "  Model: gpt-5.5" in out
    assert "    from: .aiwf/metadata.local.env" in out
    assert "    from: .aiwf/metadata_profiles/gpt_5_4_high.env" in out
    assert "active profile is overridden by .aiwf/metadata.local.env" in out


def test_metadata_status_reports_dangling_profile(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata.current").write_text("missing_profile\n", encoding="utf-8")

    rc = ai_workflow.metadata_status_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF-META-PROFILE-004" in out
    assert "no usable profile, local override, or shell override found" in out


def test_metadata_show_does_not_treat_event_log_as_attribution(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "gpt_5_5_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.5",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("gpt_5_5_high\n", encoding="utf-8")

    rc = ai_workflow.metadata_show_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF_EVENT_LOG" not in out


def test_metadata_validate_rejects_invalid_runtime_option(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "bad_runtime.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.5",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=yes",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.current").write_text("bad_runtime\n", encoding="utf-8")

    rc = ai_workflow.metadata_validate_command(root)
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-META-RUNTIME-001" in out


def test_metadata_profile_use_warns_about_local_and_shell_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    root = _init_repo(tmp_path)
    (root / ".aiwf" / "metadata_profiles").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata_profiles" / "codex_high.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.5",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=profile",
                "AIWF_METADATA_CONFIDENCE=high",
                "AIWF_EVENT_LOG=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf" / "metadata.local.env").write_text("AIWF_MODEL_NAME=gpt-5.6\n", encoding="utf-8")
    monkeypatch.setenv("AIWF_MODEL_NAME", "deepseek-v4-flash")

    rc = ai_workflow.metadata_profile_use_command(root, "codex_high")
    out = capsys.readouterr().out
    assert rc == 0
    assert ".aiwf/metadata.local.env exists and may override the active profile" in out
    assert "shell AIWF_* metadata variables are present and may override the active profile" in out


def test_event_logging_includes_ai_agent_metadata(tmp_path: Path):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    (root / ".env").write_text(
        "\n".join(
            [
                "AIWF_EVENT_LOG=1",
                "AIWF_WORKFLOW_MODE=aiwf_deterministic",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".aiwf").mkdir(parents=True, exist_ok=True)
    (root / ".aiwf" / "metadata.local.env").write_text(
        "\n".join(
            [
                "AIWF_AGENT_TOOL=codex",
                "AIWF_MODEL_PROVIDER=openai",
                "AIWF_MODEL_NAME=gpt-5.3-codex",
                "AIWF_REASONING_EFFORT=high",
                "AIWF_METADATA_SOURCE=explicit_env",
                "AIWF_METADATA_CONFIDENCE=high",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert ai_workflow.doctor_command(root, str(task_dir)) == 2
    events = _events_lines(task_dir)
    assert events
    first = events[0]
    assert "ai_agent" in first
    assert first["ai_agent"]["tool"] == "codex"
    assert first["ai_agent"]["provider"] == "openai"
    assert first["ai_agent"]["model_name"] == "gpt-5.3-codex"
    assert first["ai_agent"]["reasoning_effort"] == "high"
    assert first["ai_agent"]["source"] == "explicit_env"
    assert first["ai_agent"]["confidence"] == "high"


def test_metadata_report_counts_known_and_unknown_model(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    task_dir = _create_task(root, date="20260513")
    ai_workflow._append_raw_event(
        root,
        task_dir,
        {
            "schema_version": "aiwf-event-v0.2",
            "event_type": "review_recorded",
            "ai_agent": {
                "tool": "codex",
                "provider": "openai",
                "model_name": "gpt-5.3-codex",
                "reasoning_effort": "high",
                "source": "explicit_env",
                "confidence": "high",
            },
        },
    )
    ai_workflow._append_raw_event(
        root,
        task_dir,
        {
            "schema_version": "aiwf-event-v0.1",
            "model": {"name": "unknown", "class": "unknown", "provider": "unknown"},
        },
    )
    capsys.readouterr()
    rc = ai_workflow.metadata_report_command(root)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["metadata_coverage"]["total_events"] == 2
    assert payload["metadata_coverage"]["known_model"] == 1
    assert payload["metadata_coverage"]["unknown_model"] == 1
    assert payload["metadata_coverage"]["coverage"] == 0.5
