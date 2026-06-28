from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_aiwf_runtime():
    spec = importlib.util.spec_from_file_location("aiwf_layout_runtime_under_test", REPO_ROOT / ".aiwf" / "bin" / "ai_workflow.py")
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


def _write_config(root: Path, records_root: str) -> None:
    cfg_dir = root / ".aiwf"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "\n".join(
            [
                "layout:",
                f"  records_root: {records_root}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_v2_config(root: Path, *, docs_root: str, record_root: str, event_log: str, legacy_enabled: bool) -> None:
    cfg_dir = root / ".aiwf"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "\n".join(
            [
                "aiwf_layout_version: 2",
                f"docs_root: {docs_root}",
                f"record_root: {record_root}",
                f"event_log: {event_log}",
                f"legacy_enabled: {'true' if legacy_enabled else 'false'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_records_root_defaults_to_docs_when_config_missing(tmp_path: Path):
    root = _init_repo(tmp_path)
    config = ai_workflow.load_aiwf_config(root)
    assert config.layout.records_root == "docs"
    assert ai_workflow.resolve_records_root(root) == (root / "docs").resolve()


def test_records_root_reads_aiwf_config(tmp_path: Path):
    root = _init_repo(tmp_path)
    _write_config(root, "aiwf-docs")
    config = ai_workflow.load_aiwf_config(root)
    assert config.layout.records_root == "aiwf-docs"
    assert ai_workflow.resolve_records_root(root) == (root / "aiwf-docs").resolve()


def test_records_root_reads_v2_aiwf_config(tmp_path: Path):
    root = _init_repo(tmp_path)
    _write_v2_config(
        root,
        docs_root=".aiwf/docs",
        record_root=".aiwf/records",
        event_log=".aiwf/events/events.jsonl",
        legacy_enabled=False,
    )
    config = ai_workflow.load_aiwf_config(root)
    assert config.layout.aiwf_layout_version == 2
    assert config.layout.docs_root == ".aiwf/docs"
    assert config.layout.records_root == ".aiwf/records"
    assert config.layout.event_log == ".aiwf/events/events.jsonl"
    assert config.layout.legacy_enabled is False
    assert ai_workflow.resolve_records_root(root) == (root / ".aiwf/records").resolve()
    assert ai_workflow.get_event_log_path(root) == (root / ".aiwf/events/events.jsonl").resolve()


def test_records_root_ignores_unknown_config_keys(tmp_path: Path):
    root = _init_repo(tmp_path)
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
                "project_note: keep-me",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = ai_workflow.load_aiwf_config(root)
    assert config.layout.aiwf_layout_version == 2
    assert config.layout.records_root == ".aiwf/records"
    assert ai_workflow.resolve_records_root(root) == (root / ".aiwf/records").resolve()


def test_new_task_uses_configured_records_root(tmp_path: Path):
    root = _init_repo(tmp_path)
    _write_config(root, "aiwf-docs")
    rc = ai_workflow.create_task(root, "resolver_smoke", "20260529", update_existing=False, allow_non_today_date=True)
    assert rc == 0
    assert (root / "aiwf-docs" / "ai_20260529").is_dir()
    assert (root / "aiwf-docs" / "ai_20260529" / "001_resolver_smoke").is_dir()


def test_safe_write_path_allows_configured_records_root(tmp_path: Path):
    root = _init_repo(tmp_path)
    _write_config(root, "aiwf-docs")
    ai_workflow.safe_write_path(root, root / "aiwf-docs" / "ai_20260529" / "001_demo" / "task.md")


def test_safe_write_path_rejects_unrelated_paths(tmp_path: Path):
    root = _init_repo(tmp_path)
    _write_config(root, "aiwf-docs")
    with pytest.raises(SystemExit):
        ai_workflow.safe_write_path(root, root / "random" / "ai_20260529" / "001_demo" / "task.md")


def test_report_works_with_default_docs_root(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    rc = ai_workflow.create_task(root, "default_docs_report", "20260529", update_existing=False, allow_non_today_date=True)
    assert rc == 0

    capsys.readouterr()
    rc = ai_workflow.report_command(root, None, "json")
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["summary"]["task_count"] == 1
