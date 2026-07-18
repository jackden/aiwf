from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Iterable

import pytest


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
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir()
    template_path = tmp_path / ".aiwf" / "templates" / "AGENTS.block.md"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(AGENTS_TEMPLATE_TEXT, encoding="utf-8")
    return tmp_path


def _run_agents_cli(root: Path, args: Iterable[str]) -> int:
    return ai_workflow.main(["--repo-root", str(root), "agents", *args])


def _snapshot_tree(root: Path) -> tuple[tuple[str, str, str], ...]:
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", str(path.readlink())))
        elif path.is_dir():
            entries.append((relative, "directory", ""))
        else:
            entries.append((relative, "file", path.read_bytes().hex()))
    return tuple(entries)


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


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


def test_agents_install_allows_repo_local_nested_path_via_cli(tmp_path: Path, capsys):
    root = _init_repo(tmp_path)
    nested_path = "docs/agents/AGENTS.md"

    rc = _run_agents_cli(root, ["install", "--path", nested_path, "--yes"])
    install_out = capsys.readouterr().out

    assert rc == 0
    assert "docs/agents/AGENTS.md" in install_out
    assert (root / nested_path).is_file()
    assert (root / nested_path).read_text(encoding="utf-8") == AGENTS_TEMPLATE_TEXT

    rc = _run_agents_cli(root, ["check", "--path", nested_path])
    check_out = capsys.readouterr().out
    assert rc == 0
    assert "AIWF-AGENTS-OK" in check_out


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [("check", []), ("install", ["--yes"])],
)
def test_agents_cli_rejects_absolute_path_outside_repo_without_side_effects(
    tmp_path: Path, capsys, command: str, extra_args: list[str]
):
    root = _init_repo(tmp_path / "repo")
    outside_file = tmp_path / "outside" / "AGENTS.md"
    outside_file.parent.mkdir()
    outside_file.write_text("outside content\n", encoding="utf-8")
    before_tree = _snapshot_tree(root)
    before_outside = outside_file.read_text(encoding="utf-8")

    rc = _run_agents_cli(root, [command, "--path", str(outside_file), *extra_args])
    out = capsys.readouterr().out

    assert rc == 2
    assert "AIWF-AGENTS-PATH-001" in out
    assert _snapshot_tree(root) == before_tree
    assert outside_file.read_text(encoding="utf-8") == before_outside


def test_agents_install_rejects_relative_traversal_without_side_effects(tmp_path: Path, capsys):
    root = _init_repo(tmp_path / "repo")
    outside_file = tmp_path / "outside" / "AGENTS.md"
    outside_file.parent.mkdir()
    outside_file.write_text("outside content\n", encoding="utf-8")
    before_tree = _snapshot_tree(root)

    rc = _run_agents_cli(root, ["install", "--path", "../outside/AGENTS.md", "--yes"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "AIWF-AGENTS-PATH-001" in out
    assert _snapshot_tree(root) == before_tree
    assert outside_file.read_text(encoding="utf-8") == "outside content\n"


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [("check", []), ("install", ["--yes"])],
)
def test_agents_cli_rejects_final_symlink_escape(
    tmp_path: Path, capsys, command: str, extra_args: list[str]
):
    root = _init_repo(tmp_path / "repo")
    outside_file = tmp_path / "outside" / "AGENTS.md"
    outside_file.parent.mkdir()
    outside_file.write_text("outside content\n", encoding="utf-8")
    link = root / "AGENTS_LINK.md"
    _symlink_or_skip(link, outside_file)
    before_tree = _snapshot_tree(root)

    rc = _run_agents_cli(root, [command, "--path", "AGENTS_LINK.md", *extra_args])
    out = capsys.readouterr().out

    assert rc == 2
    assert "AIWF-AGENTS-PATH-001" in out
    assert _snapshot_tree(root) == before_tree
    assert link.is_symlink()
    assert outside_file.read_text(encoding="utf-8") == "outside content\n"


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [("check", []), ("install", ["--yes"])],
)
def test_agents_cli_rejects_parent_directory_symlink_escape(
    tmp_path: Path, capsys, command: str, extra_args: list[str]
):
    root = _init_repo(tmp_path / "repo")
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    link = root / "external"
    _symlink_or_skip(link, outside_dir, target_is_directory=True)
    before_tree = _snapshot_tree(root)

    rc = _run_agents_cli(root, [command, "--path", "external/AGENTS.md", *extra_args])
    out = capsys.readouterr().out

    assert rc == 2
    assert "AIWF-AGENTS-PATH-001" in out
    assert _snapshot_tree(root) == before_tree
    assert link.is_symlink()
    assert not (outside_dir / "AGENTS.md").exists()


def test_agents_cli_rejects_repository_prefix_sibling(tmp_path: Path, capsys):
    root = _init_repo(tmp_path / "repo")
    prefix_sibling = tmp_path / "repo-evil" / "AGENTS.md"
    prefix_sibling.parent.mkdir()
    prefix_sibling.write_text("outside content\n", encoding="utf-8")
    before_tree = _snapshot_tree(root)

    rc = _run_agents_cli(root, ["install", "--path", str(prefix_sibling), "--yes"])
    out = capsys.readouterr().out

    assert rc == 2
    assert "AIWF-AGENTS-PATH-001" in out
    assert _snapshot_tree(root) == before_tree
    assert prefix_sibling.read_text(encoding="utf-8") == "outside content\n"
