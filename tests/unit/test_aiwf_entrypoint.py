from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "aiwf"
RUNTIME = REPO_ROOT / ".aiwf" / "bin" / "ai_workflow.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_with_env(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [*args],
        cwd=REPO_ROOT,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_python_shim(path: Path, marker_log: Path, marker: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"echo \"{marker}\" >> \"{marker_log}\"\n"
        f"exec \"{sys.executable}\" \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_old_python_shim(path: Path, marker_log: Path, marker: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"echo \"{marker}\" >> \"{marker_log}\"\n"
        "if [ \"${1:-}\" = \"-\" ]; then\n"
        "  cat >/dev/null\n"
        "  echo \"ERROR: AIWF requires Python >= 3.10, got 3.9.0\" >&2\n"
        "  exit 1\n"
        "fi\n"
        f"exec \"{sys.executable}\" \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_aiwf_runtime(repo: Path) -> None:
    runtime = repo / ".aiwf" / "bin" / "ai_workflow.py"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        "import json\n"
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    print('usage: fake-aiwf')\n"
        "    raise SystemExit(0)\n"
        "if len(sys.argv) >= 5 and sys.argv[1] == 'report' and sys.argv[2] == '--path':\n"
        "    print(json.dumps({'ok': True}))\n"
        "    raise SystemExit(0)\n"
        "print('ok')\n",
        encoding="utf-8",
    )


def _make_fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    entrypoint_text = ENTRYPOINT.read_text(encoding="utf-8")
    (repo / "aiwf").write_text(entrypoint_text, encoding="utf-8")
    (repo / "aiwf").chmod(0o755)

    _write_fake_aiwf_runtime(repo)

    runtime = repo / "tools" / "ai_workflow.py"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        "import json\n"
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    print('usage: fake-aiwf')\n"
        "    raise SystemExit(0)\n"
        "if len(sys.argv) >= 5 and sys.argv[1] == 'report' and sys.argv[2] == '--path':\n"
        "    print(json.dumps({'ok': True}))\n"
        "    raise SystemExit(0)\n"
        "print('ok')\n",
        encoding="utf-8",
    )
    return repo


def _make_bootstrap_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "bootstrap_repo"
    repo.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("# bootstrap repo\n", encoding="utf-8")
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    entrypoint_text = ENTRYPOINT.read_text(encoding="utf-8")
    (repo / "aiwf").write_text(entrypoint_text, encoding="utf-8")
    (repo / "aiwf").chmod(0o755)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "tools" / "ai_workflow.py").write_text(
        "\n".join(
            [
                'AIWF_TOOL_VERSION = "1.7.5.post5"',
                'WORKFLOW_PROTOCOL_VERSION = "1.7.5"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return repo


def _run_in_repo(repo: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [str(repo / "aiwf"), *args],
        cwd=repo,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_aiwf_entrypoint_exists():
    assert ENTRYPOINT.exists()
    assert ENTRYPOINT.is_file()


def test_aiwf_entrypoint_is_executable():
    assert os.access(ENTRYPOINT, os.X_OK)


def test_aiwf_entrypoint_help_works():
    result = _run(str(ENTRYPOINT), "--help")
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_aiwf_entrypoint_honors_aiwf_python_env():
    result = _run_with_env(str(ENTRYPOINT), "--help", env={"AIWF_PYTHON": sys.executable})
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_aiwf_entrypoint_rejects_too_old_python(tmp_path: Path):
    fake_python = tmp_path / "python_old"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"ERROR: AIWF requires Python >= 3.10, got 3.9.0\" >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    result = _run_with_env(str(ENTRYPOINT), "--help", env={"AIWF_PYTHON": str(fake_python)})
    assert result.returncode != 0
    assert "ERROR: AIWF requires Python >= 3.10, got 3.9.0" in result.stderr


def test_aiwf_entrypoint_forwards_to_runtime_report_json():
    via_entrypoint = _run(str(ENTRYPOINT), "report", "--path", ".aiwf/docs", "--format", "json")
    via_runtime = _run(sys.executable, str(RUNTIME), "report", "--path", ".aiwf/docs", "--format", "json")
    assert via_entrypoint.returncode == 0
    assert via_runtime.returncode == 0
    assert json.loads(via_entrypoint.stdout) == json.loads(via_runtime.stdout)


def test_aiwf_entrypoint_prefers_repo_windows_venv_over_windowsapps_python3(tmp_path: Path):
    repo = _make_fake_repo(tmp_path)
    marker_log = tmp_path / "markers.log"

    repo_python = repo / ".venv" / "Scripts" / "python"
    _write_python_shim(repo_python, marker_log, "repo_scripts")

    windowsapps_python3 = tmp_path / "Users" / "demo" / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "python3"
    _write_python_shim(windowsapps_python3, marker_log, "windowsapps_python3")

    result = _run_in_repo(
        repo,
        "--help",
        env={"PATH": f"{windowsapps_python3.parent}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0
    assert "usage: fake-aiwf" in result.stdout
    markers = [line.strip() for line in marker_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert markers
    assert all(marker == "repo_scripts" for marker in markers)


def test_aiwf_entrypoint_prefers_python_over_python3_from_path(tmp_path: Path):
    repo = _make_fake_repo(tmp_path)
    marker_log = tmp_path / "markers.log"
    bin_dir = tmp_path / "bin"

    _write_python_shim(bin_dir / "python", marker_log, "path_python")
    _write_python_shim(bin_dir / "python3", marker_log, "path_python3")

    result = _run_in_repo(repo, "--help", env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    assert result.returncode == 0
    markers = [line.strip() for line in marker_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert markers
    assert all(marker == "path_python" for marker in markers)


def test_aiwf_entrypoint_falls_back_when_path_python_is_too_old(tmp_path: Path):
    repo = _make_fake_repo(tmp_path)
    marker_log = tmp_path / "markers.log"
    bin_dir = tmp_path / "bin"

    _write_old_python_shim(bin_dir / "python", marker_log, "path_python_old")
    _write_python_shim(bin_dir / "python3", marker_log, "path_python3")

    result = _run_in_repo(repo, "--help", env={"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    assert result.returncode == 0
    assert "usage: fake-aiwf" in result.stdout
    markers = [line.strip() for line in marker_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert "path_python_old" in markers
    assert markers[-1] == "path_python3"


def test_aiwf_entrypoint_skips_windowsapps_python_and_uses_python3(tmp_path: Path):
    repo = _make_fake_repo(tmp_path)
    marker_log = tmp_path / "markers.log"

    windowsapps_python = tmp_path / "Users" / "demo" / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "python"
    _write_python_shim(windowsapps_python, marker_log, "windowsapps_python")

    bin_dir = tmp_path / "bin"
    _write_python_shim(bin_dir / "python3", marker_log, "path_python3")

    result = _run_in_repo(
        repo,
        "--help",
        env={"PATH": f"{windowsapps_python.parent}:{bin_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0
    markers = [line.strip() for line in marker_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert markers
    assert all(marker == "path_python3" for marker in markers)


def test_aiwf_entrypoint_rejects_windowsapps_only_aliases(tmp_path: Path):
    repo = _make_fake_repo(tmp_path)
    windowsapps_python = tmp_path / "Users" / "demo" / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "python"
    windowsapps_python3 = tmp_path / "Users" / "demo" / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "python3"
    marker_log = tmp_path / "markers.log"
    _write_python_shim(windowsapps_python, marker_log, "windowsapps_python")
    _write_python_shim(windowsapps_python3, marker_log, "windowsapps_python3")

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(parents=True, exist_ok=True)
    (fakebin / "bash").symlink_to(Path("/bin/bash"))

    result = _run_in_repo(repo, "--help", env={"PATH": f"{windowsapps_python.parent}:{fakebin}"})
    assert result.returncode != 0
    assert "WindowsApps aliases are ignored" in result.stderr


def test_bootstrap_upgrade_when_runtime_missing(tmp_path: Path):
    repo = _make_bootstrap_repo(tmp_path)

    result = _run_in_repo(
        repo,
        "upgrade",
        "--check",
        "--source",
        str(REPO_ROOT),
        env={"AIWF_PYTHON": sys.executable},
    )
    assert result.returncode == 0
    assert "[INFO] AIWF-UPGRADE-CHECK" in result.stdout
    assert "upgrade_required: yes" in result.stdout
    assert "relocation_required: no" in result.stdout


def test_aiwf_entrypoint_bootstrap_rejects_non_upgrade_command_when_runtime_missing(tmp_path: Path):
    repo = _make_bootstrap_repo(tmp_path)

    result = _run_in_repo(repo, "report", "--path", ".aiwf/docs", "--format", "json", env={"AIWF_PYTHON": sys.executable})
    assert result.returncode != 0
    assert "bootstrap mode only supports upgrade commands" in result.stderr
