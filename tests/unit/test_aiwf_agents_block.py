from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_aiwf_runtime():
    spec = importlib.util.spec_from_file_location("aiwf_agents_runtime_under_test", REPO_ROOT / ".aiwf" / "bin" / "ai_workflow.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ai_workflow = _load_aiwf_runtime()
AGENTS_TEMPLATE_TEXT = (REPO_ROOT / ".aiwf" / "templates" / "AGENTS.block.md").read_text(encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    template_path = tmp_path / ".aiwf" / "templates" / "AGENTS.block.md"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(AGENTS_TEMPLATE_TEXT, encoding="utf-8")
    return tmp_path


def test_agents_print_block_reads_template(tmp_path: Path, monkeypatch, capsys):
    root = _init_repo(tmp_path)
    (root / "AGENTS.md").write_text("# bootstrap repo\n", encoding="utf-8")
    monkeypatch.chdir(root)
    capsys.readouterr()
    rc = ai_workflow.agents_print_block_command(root)
    out = capsys.readouterr().out
    assert rc == 0
    assert out == AGENTS_TEMPLATE_TEXT


def test_agents_check_missing_file_reports_missing(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    capsys.readouterr()
    rc = ai_workflow.agents_check_command(root, "AGENTS.md")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-AGENTS-001" in out


def test_agents_check_existing_block_passes(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / "AGENTS.md").write_text(ai_workflow.aiwf_agents_managed_block(root), encoding="utf-8")
    capsys.readouterr()
    rc = ai_workflow.agents_check_command(root, "AGENTS.md")
    out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF-AGENTS-OK" in out
    assert "matches template" in out


def test_agents_check_template_change_reports_outdated(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    (root / "AGENTS.md").write_text(ai_workflow.aiwf_agents_managed_block(root), encoding="utf-8")
    (root / ".aiwf" / "templates" / "AGENTS.block.md").write_text(
        AGENTS_TEMPLATE_TEXT.replace("Use `./aiwf` for:", "Use `./aiwf` for:\n- template drift test"),
        encoding="utf-8",
    )
    capsys.readouterr()
    rc = ai_workflow.agents_check_command(root, "AGENTS.md")
    out = capsys.readouterr().out
    assert rc == 2
    assert "AIWF-AGENTS-OUTDATED" in out


def test_agents_install_preserves_existing_content(tmp_path: Path):
    root = _init_repo(tmp_path)
    path = root / "AGENTS.md"
    path.write_text("# Existing Agent Rules\n", encoding="utf-8")

    rc = ai_workflow.agents_install_command(root, "AGENTS.md", yes=True)
    assert rc == 0
    content = path.read_text(encoding="utf-8")
    assert "Existing Agent Rules" in content
    assert AGENTS_TEMPLATE_TEXT.strip() in content


def test_agents_install_is_idempotent(tmp_path: Path):
    root = _init_repo(tmp_path)
    path = root / "AGENTS.md"
    path.write_text("# Existing Agent Rules\n", encoding="utf-8")

    assert ai_workflow.agents_install_command(root, "AGENTS.md", yes=True) == 0
    assert ai_workflow.agents_install_command(root, "AGENTS.md", yes=True) == 0
    content = path.read_text(encoding="utf-8")
    assert content.count("AIWF:BEGIN") == 1
    assert AGENTS_TEMPLATE_TEXT.strip() in content


def test_agents_install_replaces_only_managed_block(tmp_path: Path):
    root = _init_repo(tmp_path)
    path = root / "AGENTS.md"
    path.write_text(
        "\n".join(
            [
                "# Existing Agent Rules",
                "Prefix line",
                "<!-- AIWF:BEGIN -->",
                "stale block content",
                "<!-- AIWF:END -->",
                "Suffix line",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = ai_workflow.agents_install_command(root, "AGENTS.md", yes=True)
    assert rc == 0
    content = path.read_text(encoding="utf-8")
    assert "Prefix line" in content
    assert "Suffix line" in content
    assert "stale block content" not in content
    assert content.count("AIWF:BEGIN") == 1
    assert AGENTS_TEMPLATE_TEXT.strip() in content
