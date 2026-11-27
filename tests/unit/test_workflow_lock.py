import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

from test_ai_workflow import REPO_ROOT, _prepare_finalize_ready_task, _snapshot_tree


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "synthetic"
    shutil.copytree(REPO_ROOT / ".aiwf/bin", root / ".aiwf/bin", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(REPO_ROOT / ".aiwf/config.yaml", root / ".aiwf/config.yaml")
    return root


def run(root, *argv, source=None):
    if source is None:
        command = [sys.executable, "-B", str(root / ".aiwf/bin/ai_workflow.py"), "--repo-root", str(root), *argv]
    else:
        command = [sys.executable, "-B", "-c", source, *argv]
    return subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=20)


def create(root, name="task"):
    response = run(root, "mutate", "new-task", name)
    assert response.returncode == 0, response.stdout + response.stderr
    return json.loads(response.stdout)["target"]


def parallel(count, operation):
    start = threading.Barrier(count)

    def invoke(number):
        start.wait()
        return operation(number)

    with concurrent.futures.ThreadPoolExecutor(count) as pool:
        return list(pool.map(invoke, range(count)))


def test_native_and_structured_writers_serialize_ids_index_and_both_event_logs(project):
    root = project
    n = 8
    created = parallel(n, lambda i: run(root, *(("mutate",) if i % 2 else ()), "new-task", f"fixture_{i}"))
    assert [res.returncode for res in created] == [0] * n
    day, = (root / ".aiwf/records").iterdir()
    tasks = sorted(p.name for p in day.iterdir() if p.is_dir())
    assert len(tasks) == len({name[:3] for name in tasks}) == n
    index = (day / "index.md").read_text()
    assert all(index.count(name) == 1 for name in tasks)
    duplicates = parallel(4, lambda i: run(root, *(("mutate",) if i % 2 else ()), "new-task", "shared_name"))
    assert sorted(res.returncode for res in duplicates) == [0, 2, 2, 2]
    path = (day / tasks[0]).relative_to(root).as_posix()
    events = parallel(n, lambda i: run(root, *(("mutate",) if i % 2 else ()), "record", "--path", path,
                                       "--kind", "validation", "--result", "pass", "--command", f"check-{i}"))
    assert [res.returncode for res in events] == [0] * n
    local = (root / path / ".aiwf/events.jsonl").read_text().splitlines()
    global_log = (root / ".aiwf/events/events.jsonl").read_text().splitlines()
    assert local == global_log and len(local) == n
    assert {json.loads(line)["command"] for line in local} == {f"check-{i}" for i in range(n)}
    assert not (root / ".aiwf-mutation-pending").exists()


IMPORT = """import os, sys
from pathlib import Path
sys.path.insert(0, str(Path('.aiwf/bin').resolve()))
import ai_workflow as runtime
from lib import workflow_lock as locks
"""


def test_contended_read_and_write_timeout_then_unlock_without_artifacts(project):
    root = project
    path = create(root)
    baseline = _snapshot_tree(root)
    holder = subprocess.Popen([sys.executable, "-B", "-c", IMPORT + """
with locks.workflow_lock(Path.cwd(), writer=True, operation='holder'):
    print('locked', flush=True)
    sys.stdin.readline()
"""], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        calls = [
            ["query", "check", "--path", path, "--finalize-ready"],
            ["mutate", "record", "--path", path, "--kind", "fix", "--summary", "test"],
        ]
        outcomes = parallel(2, lambda i: run(root, *calls[i]))
        assert all(p.returncode == 2 and "AIWF-LOCK-BUSY" in p.stdout for p in outcomes)
        assert json.loads(outcomes[0].stdout)["result"] is None
        assert json.loads(outcomes[1].stdout)["mutation_state"] == "not_applied"
    finally:
        holder.kill()
        holder.communicate(timeout=5)
    assert _snapshot_tree(root) == baseline
    assert run(root, "query", "inspect", "--path", path).returncode == 0
    assert _snapshot_tree(root) == baseline


@pytest.mark.parametrize("point", ["metadata", "local_event", "finalized_metadata", "finalized_index", "before_manifest"])
def test_crashed_writer_preserves_partial_evidence_and_blocks_restart(project, point):
    root = project
    path = create(root)
    if point.startswith("finalized") or point == "before_manifest":
        _prepare_finalize_ready_task(root, root / path)
        args = ["mutate", "finalize", "--path", path]
    else:
        args = ["mutate", "record", "--path", path, "--kind", "validation", "--result", "pass", "--command", "checked"]
    # Only the synthetic process is instrumented; the product has no fault-injection flags.
    child = IMPORT + """
point = sys.argv[1]
if point in {'metadata', 'finalized_metadata', 'finalized_index'}:
    fn = {'metadata': '_rewrite_task_metadata_file', 'finalized_metadata': '_finalize_task_metadata',
          'finalized_index': '_sync_index_entry_status'}[point]
    original = getattr(runtime, fn)
    def cut(*args, **kw):
        original(*args, **kw)
        os._exit(83)
    setattr(runtime, fn, cut)
elif point == 'local_event':
    original = Path.open
    def cut(self, mode='r', *args, **kw):
        if self == Path.cwd() / '.aiwf/events/events.jsonl' and mode == 'a':
            os._exit(83)
        return original(self, mode, *args, **kw)
    Path.open = cut
else:
    original = runtime._append_evidence_event
    def cut(root, task, event, **kw):
        if event.get('event_type') == 'finalize_success':
            os._exit(83)
        return original(root, task, event, **kw)
    runtime._append_evidence_event = cut
sys.exit(runtime.main(['--repo-root', str(Path.cwd()), *sys.argv[2:]]))
"""
    interrupted = run(root, point, *args, source=child)
    assert interrupted.returncode == 83, interrupted.stdout + interrupted.stderr
    marker = json.loads((root / ".aiwf-mutation-pending").read_text())
    assert marker == {"version": 1, "operation": args[1], "target": path}
    local_log = root / path / ".aiwf/events.jsonl"
    if point == "metadata":
        assert not local_log.exists()
    elif point == "local_event":
        assert local_log.exists() and not (root / ".aiwf/events/events.jsonl").exists()
    else:
        assert 'workflow_phase: "finalized"' in (root / path / "task.md").read_text()
        assert "finalize_success" not in local_log.read_text()
        assert ("status: Done" in (root / path).parent.joinpath("index.md").read_text()) == (point != "finalized_metadata")
    before = _snapshot_tree(root)
    rejected = run(root, "mutate", "new-task", "later")
    assert rejected.returncode == 2
    result = json.loads(rejected.stdout)
    assert result["mutation_state"] == "not_applied" and result["requires_reconciliation"]
    assert result["diagnostics"][0]["code"] == "AIWF-RECOVERY-REQUIRED"
    read = run(root, "query", "check", "--path", path, "--finalize-ready")
    assert json.loads(read.stdout)["error"]["code"] == "AIWF-RECOVERY-REQUIRED"
    assert _snapshot_tree(root) == before


def test_ambiguous_shared_storage_refuses_writes(project):
    root = project
    nested = root / "another"
    (nested / ".aiwf/records").mkdir(parents=True)
    (nested / ".aiwf/config.yaml").write_text("aiwf_layout_version: 2\n")
    (root / ".aiwf/config.yaml").write_text("aiwf_layout_version: 2\nrecord_root: another/.aiwf/records\n")
    before = _snapshot_tree(root)
    rejected = run(root, "mutate", "new-task", "wrong")
    assert rejected.returncode == 2 and json.loads(rejected.stdout)["diagnostics"][0]["code"] == "AIWF-LOCK-UNSUPPORTED"
    assert before == _snapshot_tree(root)


def test_legacy_root_override_cannot_lease_an_enclosing_projects_records(project):
    outer = project
    inner = outer / "inner"
    inner.mkdir()
    (outer / ".aiwf/config.yaml").write_text("aiwf_layout_version: 2\nrecord_root: inner/docs\n")
    task = create(outer)
    # A legacy CLI can supply a repo root that contains no runtime or config.
    # Both roots would otherwise allocate under the same inner/docs directory.
    before = _snapshot_tree(outer)
    result = subprocess.run([sys.executable, "-B", str(outer / ".aiwf/bin/ai_workflow.py"),
                             "--repo-root", str(inner), "new-task", "duplicate_lease"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "AIWF-LOCK-UNSUPPORTED" in result.stderr
    assert _snapshot_tree(outer) == before
    assert run(outer, "query", "inspect", "--path", task).returncode == 0


def test_nested_installed_projects_require_disjoint_storage_even_with_explicit_target(project):
    outer = project
    inner = outer / "inner"
    shutil.copytree(outer / ".aiwf", inner / ".aiwf")
    outer_task = create(outer, "outer")
    inner_task = create(inner, "inner")
    relative_inner = (inner / inner_task).relative_to(outer).as_posix()
    # Check an explicit legacy override while both project configs are disjoint.
    before = _snapshot_tree(outer)
    result = run(outer, "record", "--path", relative_inner, "--kind", "fix", "--summary", "cross_owner")
    assert result.returncode == 2 and "AIWF-LOCK-UNSUPPORTED" in result.stderr
    assert _snapshot_tree(outer) == before
    # Shared global events are also a conflicting layout even with disjoint task roots.
    (outer / ".aiwf/config.yaml").write_text("aiwf_layout_version: 2\nevent_log: inner/.aiwf/events/events.jsonl\n")
    before = _snapshot_tree(outer)
    for prefix in ([], ["mutate"]):
        result = run(outer, *prefix, "record", "--path", outer_task, "--kind", "fix", "--summary", "overlap")
        assert result.returncode == 2 and "AIWF-LOCK-UNSUPPORTED" in result.stderr + result.stdout
    assert _snapshot_tree(outer) == before
    assert run(inner, "mutate", "record", "--path", inner_task, "--kind", "fix", "--summary", "inner").returncode == 0


@pytest.mark.parametrize("fault", ["diagnostic_error", "read_error"])
def test_finalize_post_write_diagnostic_failure_preserves_manifest_and_requires_reconciliation(project, fault):
    root = project
    path = create(root)
    _prepare_finalize_ready_task(root, root / path)
    child = IMPORT + """
os.environ['AIWF_EVENT_LOG'] = '1'
original = runtime._collect_task_diagnostics
def fail_refresh(root, target, **kw):
    if kw['include_finalize_checks']:
        return original(root, target, **kw)
    if sys.argv[1] == 'read_error':
        raise OSError('synthetic post-write read error')
    return [runtime.Diagnostic('error', 'TEST-POSTWRITE', target.name,
                               'synthetic post-write finding', '', False)]
runtime._collect_task_diagnostics = fail_refresh
sys.exit(runtime.main(['--repo-root', str(Path.cwd()), 'mutate', 'finalize', '--path', sys.argv[2]]))
"""
    response = run(root, fault, path, source=child)
    receipt = json.loads(response.stdout)
    assert response.returncode == 2 and receipt["operation_status"] == "failed"
    expected_state = "unknown" if fault == "read_error" else "partially_applied"
    assert receipt["mutation_state"] == expected_state and receipt["requires_reconciliation"]
    assert receipt["target"] == path
    assert 'workflow_phase: "finalized"' in (root / path / "task.md").read_text()
    assert "status: Done" in (root / path).parent.joinpath("index.md").read_text()
    for log in (root / path / ".aiwf/events.jsonl", root / ".aiwf/events/events.jsonl"):
        events = [json.loads(line) for line in log.read_text().splitlines()]
        closure, = [e for e in events if e.get("event_type") == "finalize_success"]
        assert closure["artifact_manifest"]
        audits = [e for e in events if e.get("command") == "finalize"]
        if fault == "diagnostic_error":
            audit, = audits
            assert audit["result"] == {"exit_code": 2, "status": "error"}
            assert "TEST-POSTWRITE" in audit["diagnostics"]["codes"]
        else:
            assert not audits
    assert json.loads((root / ".aiwf-mutation-pending").read_text())["target"] == path
    before = _snapshot_tree(root)
    subsequent = run(root, "mutate", "finalize", "--path", path)
    assert json.loads(subsequent.stdout)["diagnostics"][0]["code"] == "AIWF-RECOVERY-REQUIRED"
    assert _snapshot_tree(root) == before


def test_hardlinked_index_and_symlinked_profile_are_rejected_before_evidence_writes(project, tmp_path):
    root = project
    path = create(root)
    index = (root / path).parent / "index.md"
    os.link(index, tmp_path / "other-index")
    before = _snapshot_tree(root)
    rejected = run(root, "mutate", "new-task", "later")
    assert json.loads(rejected.stdout)["diagnostics"][0]["code"] == "AIWF-LOCK-UNSUPPORTED"
    assert _snapshot_tree(root) == before
    (tmp_path / "other-index").unlink()
    (root / ".aiwf/metadata.current").symlink_to(tmp_path / "other-profile")
    before = _snapshot_tree(root)
    rejected = run(root, "mutate", "record", "--path", path, "--kind", "fix", "--summary", "text")
    assert json.loads(rejected.stdout)["diagnostics"][0]["code"] == "AIWF-LOCK-UNSUPPORTED"
    assert _snapshot_tree(root) == before


def test_reentrant_writer_permits_nested_reads_but_read_promotion_is_rejected(project):
    observed = run(project, source=IMPORT + """
root = Path.cwd()
with locks.workflow_lock(root, writer=True, operation='outer'):
    with locks.workflow_lock(root, writer=True, operation='nested-write'):
        with locks.workflow_lock(root, writer=False, operation='nested-read'):
            assert not locks.mutation_started()
with locks.workflow_lock(root, writer=False, operation='outer-read'):
    try:
        with locks.workflow_lock(root, writer=True, operation='upgrade'):
            raise AssertionError('unexpected promotion')
    except locks.WorkflowLockError as error:
        assert error.code == 'AIWF-LOCK-UNSUPPORTED'
""")
    assert observed.returncode == 0, observed.stderr


def test_unknown_platform_allows_only_legacy_observation_without_pending_recovery(project):
    task = create(project)
    simulation = IMPORT + """
import guidance
locks.sys.platform = 'unknown_platform'
entrypoint = guidance if sys.argv[1] == 'guidance' else runtime
sys.exit(entrypoint.main(['--repo-root', str(Path.cwd()), *sys.argv[2:]]))
"""
    before = _snapshot_tree(project)
    for args in (["core", "inspect", "--path", task], ["core", "guard", "--pre-edit", "--path", task],
                 ["guidance", "show", "--scope", "validation"]):
        observed = run(project, *args, source=simulation)
        assert observed.returncode == 0 and observed.stdout, (args, observed.stderr)
        assert "Unconfirmed observation" in observed.stderr
    for args in (["core", "mutate", "new-task", "wrong"], ["core", "query", "inspect", "--path", task],
                 ["core", "check", "--finalize-ready", "--path", task], ["core", "finalize", "--dry-run", "--path", task],
                 ["guidance", "show", "--format", "json", "--scope", "validation"]):
        refused = run(project, *args, source=simulation)
        assert refused.returncode == 2 and "AIWF-LOCK-UNSUPPORTED" in refused.stdout + refused.stderr
        assert "Unconfirmed observation" not in refused.stderr
    assert _snapshot_tree(project) == before
    (project / ".aiwf-mutation-pending").write_text("{}\n")
    refused = run(project, "core", "inspect", "--path", task, source=simulation)
    assert refused.returncode == 2 and "AIWF-RECOVERY-REQUIRED" in refused.stderr
    assert not refused.stdout
