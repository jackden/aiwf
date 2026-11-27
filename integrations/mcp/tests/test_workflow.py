"""Full-workflow adapter tests. Every mutation and simulated operator decision targets a temporary fixture."""

import asyncio
import io
import json
import os
from pathlib import Path

import anyio
from mcp import MCPError
import pytest
import yaml

from test_stdio import PACKAGE, ROOT, TOOLS, cli, connect, inventory, note, project, successful


WRITES = {"aiwf_new_task", "aiwf_guard", "aiwf_transition", "aiwf_sync_index", "aiwf_record", "aiwf_finalize"}
FLAGS = ("--mode", "read-write", "--binding-id", "synthetic-project", "--recorder", "fixture-recorder")
BIND = {"binding_id": "synthetic-project"}


def envelope(response):
    data = response.structured_content
    assert isinstance(data, dict)
    assert json.loads(response.content[0].text) == data
    expected_error = data["operation_status"] != "succeeded" or data["requires_reconciliation"]
    assert response.is_error is expected_error
    return data


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@pytest.mark.skipif(os.name != "posix", reason="uses POSIX TZ rules")
def test_deployment_timezone_matches_cli_for_explicit_and_implicit_task_dates(project, monkeypatch):
    root, _ = project

    async def run():
        days = []
        for zone in ("UTC-14", "UTC+12"):
            monkeypatch.setenv("TZ", zone)
            native = cli(root, "mutate", "new-task", "native implicit")
            assert native.returncode == 0, native.stdout
            directory = Path(json.loads(native.stdout)["target"]).parent
            day = directory.name.removeprefix("ai_")
            days.append(day)
            explicit = cli(root, "mutate", "new-task", "native explicit", "--date", day)
            assert explicit.returncode == 0 and Path(json.loads(explicit.stdout)["target"]).parent == directory
            async with connect(root, *FLAGS, env={"TZ": zone}) as client:
                for name, date in [("adapter implicit", {}), ("adapter explicit", {"date": day})]:
                    created = envelope(await client.call_tool("aiwf_new_task", {**BIND, "name": name, **date}))
                    assert created["operation_status"] == "succeeded", created
                    assert Path(created["target"]).parent == directory
                    assert (root / created["target"] / "task.md").is_file()
        assert days[0] != days[1]
    asyncio.run(run())


def test_read_only_tools_and_modern_discovery(project):
    root, task = project
    before = inventory(root)

    async def run():
        async with connect(root) as client:
            assert {tool.name for tool in (await client.list_tools()).tools} == TOOLS
            context = successful(await client.call_tool("aiwf_context", {}))
            assert context["interface"] == {"mode": "read-only", "mutation_contract_version": 1, "write_operations": []}
            assert context["result"]["capabilities"]["write_operations"] is False
            for name in [*sorted(WRITES), "aiwf_correct_finalized"]:
                with pytest.raises(MCPError, match="Unknown AIWF tool"):
                    await client.call_tool(name, {**BIND, "task_path": task})
            for mode, flag in [("finalize_preview", "--preview"), ("finalize_readiness", "--finalize-ready")]:
                result = successful(await client.call_tool("aiwf_check_task", {"task_path": task, "mode": mode}))
                expected = json.loads(cli(root, "query", "check", "--path", task, flag).stdout)
                assert result["result"] == expected["result"]
                assert result["result"]["mode"] == mode
    asyncio.run(run())
    assert inventory(root) == before


def test_agent_lifecycle_and_evidence_authority(project):
    root, original = project
    day = Path(original).parent.name.removeprefix("ai_")
    assert cli(root, "new-task", "historical", "--date", "20250101", "--allow-non-today-date").returncode == 0

    async def run():
        async with connect(root, *FLAGS) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == WRITES | TOOLS
            assert {tool.name for tool in tools if not tool.annotations.read_only_hint} == WRITES
            with pytest.raises(MCPError, match="Unknown AIWF tool"):
                await client.call_tool("aiwf_correct_finalized", {**BIND, "task_path": original})

            for call, args in [
                ("aiwf_new_task", {"binding_id": "wrong", "name": "wrong repo"}),
                ("aiwf_new_task", {**BIND, "name": "invalid", "update_existing": True}),
                ("aiwf_new_task", {**BIND, "name": "invalid", "related_files": ["../outside"]}),
                ("aiwf_transition", {**BIND, "task_path": original, "to": "finalized"}),
                ("aiwf_guard", {**BIND, "task_path": "001"}),
            ]:
                before = inventory(root)
                rejected = envelope(await client.call_tool(call, args))
                assert rejected["mutation_state"] == "not_applied" and not rejected["requires_reconciliation"]
                assert inventory(root) == before

            kwargs = {**BIND, "name": "Adapter Example", "title": "A synthetic case", "date": day,
                      "priority": "P2", "risk": "low", "tags": ["candidate"], "related_files": ["code/file.py"]}
            created = envelope(await client.call_tool("aiwf_new_task", kwargs))
            assert created["operation_status"] == "succeeded", created
            target = created["target"]
            assert target == f".aiwf/records/ai_{day}/002_adapter_example"
            assert created["result"]["task_path"] == target
            metadata = yaml.safe_load((root / target / "task.md").read_text().split("---")[1])
            assert metadata["title"] == kwargs["title"] and metadata["tags"] == kwargs["tags"]
            assert metadata["priority"] == "P2" and metadata["risk"] == "low"
            same = envelope(await client.call_tool("aiwf_new_task", {**kwargs, "name": "adapter_example"}))
            assert same["operation_status"] != "succeeded" and same["mutation_state"] == "not_applied"
            for filters, count, truncated in [({"date": "20250101"}, 1, False), ({"date": "19990101"}, 0, False),
                                              ({"limit": 1}, 1, True)]:
                rows = successful(await client.call_tool("aiwf_list_tasks", filters))["result"]
                assert len(rows["tasks"]) == count and rows["truncated"] is truncated
            common = {**BIND, "task_path": target}
            for call, fields in [("aiwf_guard", {}), ("aiwf_transition", {"to": "validation"}),
                                 ("aiwf_sync_index", {})]:
                outcome = envelope(await client.call_tool(call, {**common, **fields}))
                assert outcome["operation_status"] == "succeeded", outcome

            for extra in [{"decision_authority": "human"}, {"reviewer": "human"}, {"recorded_by": "human"}]:
                before = inventory(root)
                response = envelope(await client.call_tool("aiwf_record", {**common, "kind": "review", "result": "pass", **extra}))
                assert response["mutation_state"] == "not_applied" and inventory(root) == before
            for fields in [{"kind": "validation"}, {"kind": "fix", "command": "echo", "summary": "x"},
                           {"kind": "safety_ack", "summary": " "}, {"kind": "review", "result": "not_required"}]:
                response = envelope(await client.call_tool("aiwf_record", {**common, **fields}))
                assert response["diagnostics"][0]["code"] == "invalid_input"

            denial = envelope(await client.call_tool("aiwf_record", {**common, "kind": "review",
                                                                     "result": "not_required", "summary": "agent request"}))
            assert denial["mutation_state"] == "not_applied" and denial["operation_status"] != "succeeded"
            command = "printf should-not-run > synthetic-marker"
            for fields in [{"kind": "review", "result": "fail"}, {"kind": "fix", "summary": "Synthetic repair"},
                           {"kind": "safety_ack", "summary": "Received fixture acknowledgement"},
                           {"kind": "validation", "result": "pass", "command": command},
                           {"kind": "review", "result": "pass", "summary": "Agent observed PASS"}]:
                recorded = envelope(await client.call_tool("aiwf_record", {**common, **fields}))
                assert recorded["operation_status"] == "succeeded", recorded
            assert not (root / "synthetic-marker").exists()
            local = events(root / target / ".aiwf/events.jsonl")
            global_events = events(root / ".aiwf/events/events.jsonl")
            for kind in ("fix", "safety_ack", "validation", "review"):
                records = [e for e in local if e.get("event") == kind + "_recorded"]
                assert records, (kind, local)
                assert any(e.get("event") == kind + "_recorded" for e in global_events)
                if kind == "review":
                    last = records[-1]
                    assert last["decision_authority"] == "ai-agent" and last["recorded_by"] == "fixture-recorder"
                if kind == "validation":
                    assert records[-1]["command"] == command
            closure = envelope(await client.call_tool("aiwf_finalize", common))
            assert closure["operation_status"] == "blocked" and not closure["requires_reconciliation"]
            assert not any(e.get("event_type") == "finalize_success" for e in events(root / target / ".aiwf/events.jsonl"))
    asyncio.run(run())


@pytest.mark.parametrize(("ending", "reason"), [
    ("print('incomplete response')", "invalid_response"),
    ("import time; time.sleep(5)", "timeout"),
    ("print('x' * 140000)", "output_limit"),
    ("import sys; sys.exit(9)", "invalid_response"),
])
def test_response_loss_never_replays_mutation(project, monkeypatch, ending, reason):
    root, task = project
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp.runtime import BoundRepository
    runtime = root / ".aiwf/bin/ai_workflow.py"
    runtime.write_text("MUTATION_CONTRACT_VERSION = 1\nfrom pathlib import Path\n"
                       "with Path('fixture-count').open('a') as out: out.write('one\\n')\n" + ending + "\n")
    repo = BoundRepository(root, "fixture", 0.5, "read-write")
    outcome = asyncio.run(repo.mutate("guard", ["--path", task], task, ".aiwf/records"))
    assert outcome["diagnostics"][0]["code"] == reason
    if reason == "invalid_response":
        assert outcome["runtime_exit_code"] == (9 if "sys.exit(9)" in ending else 0)
    assert outcome["requires_reconciliation"] and outcome["mutation_state"] == "unknown"
    assert (root / "fixture-count").read_text() == "one\n"


@pytest.mark.skipif(os.name != "posix", reason="injects a POSIX group signal denial")
@pytest.mark.parametrize("deny_direct", [False, True], ids=["direct-kill", "bounded-wait"])
def test_cleanup_signal_denial_preserves_output_limit(project, monkeypatch, deny_direct):
    root, task = project
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp import runtime
    script = root / ".aiwf/bin/ai_workflow.py"
    script.write_text("MUTATION_CONTRACT_VERSION = 1\nimport time\n"
                      "print('x' * 140000, flush=True)\ntime.sleep(30)\n")
    repo = runtime.BoundRepository(root, "fixture", 5, "read-write")
    processes = []
    create = asyncio.create_subprocess_exec

    def denied(*_):
        raise PermissionError("synthetic signal refusal")

    async def track(*args, **kwargs):
        child = await create(*args, **kwargs)
        processes.append(child)
        if deny_direct:
            monkeypatch.setattr(child, "kill", denied)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track)
    monkeypatch.setattr(os, "killpg", denied)
    monkeypatch.setattr(runtime, "CLEANUP_SECONDS", 0.25)

    async def run():
        try:
            response = await asyncio.wait_for(repo.mutate("guard", [], task, ".aiwf/records"), 4)
            assert response["diagnostics"][0]["code"] == "output_limit"
            assert "cleanup could not be confirmed" in response["diagnostics"][0]["message"]
            assert response["requires_reconciliation"] and response["mutation_state"] == "unknown"
            child, = processes
            assert (child.returncode is None) == deny_direct
        finally:
            for child in processes:
                if child.returncode is None:
                    asyncio.subprocess.Process.kill(child)
                await asyncio.wait_for(child.wait(), 2)
    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="uses POSIX process-existence probe")
@pytest.mark.parametrize("scope_cancel", [False, True], ids=["asyncio-task", "anyio-scope"])
@pytest.mark.parametrize("during_launch", [False, True], ids=["running", "during-launch"])
def test_cancellation_reaps_original_runtime_without_replay(project, monkeypatch, scope_cancel, during_launch):
    root, task = project
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp.runtime import BoundRepository
    script = root / ".aiwf/bin/ai_workflow.py"
    script.write_text("MUTATION_CONTRACT_VERSION = 1\nfrom pathlib import Path\nimport os, time\n"
                      "with Path('fixture-pids').open('a') as f: print(os.getpid(), file=f)\ntime.sleep(60)\n")
    repo = BoundRepository(root, "fixture", 15, "read-write")

    async def run():
        scope = anyio.CancelScope()
        release_handle = asyncio.Event()
        children = []
        create = asyncio.create_subprocess_exec

        async def track_launch(*args, **kwargs):
            child = await create(*args, **kwargs)
            children.append(child)
            if during_launch:
                await release_handle.wait()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", track_launch)

        async def invoke():
            with scope:
                await repo.mutate("guard", ["--path", task], task, ".aiwf/records")
            assert scope.cancelled_caught

        invocation = asyncio.create_task(invoke())
        pid_file = root / "fixture-pids"
        for _ in range(200):
            if pid_file.exists() and pid_file.stat().st_size:
                break
            await asyncio.sleep(0.01)
        pid, = pid_file.read_text().splitlines()
        try:
            if scope_cancel:
                scope.cancel()
            else:
                invocation.cancel()
            await asyncio.sleep(0)
            release_handle.set()
            with anyio.fail_after(3):
                if scope_cancel:
                    await invocation
                else:
                    with pytest.raises(asyncio.CancelledError):
                        await invocation
            child, = children
            assert child.returncode is not None
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid), 0)
            assert pid_file.read_text().splitlines() == [pid]
        finally:
            release_handle.set()
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
    asyncio.run(run())


def test_mutation_preserves_configured_host_metadata_without_attributing_a_worker(project, monkeypatch):
    root, task = project
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp.runtime import BoundRepository
    monkeypatch.setenv("AIWF_AGENT_TOOL", "codex")
    monkeypatch.setenv("AIWF_REASONING_EFFORT", "high")
    monkeypatch.setenv("AIWF_MODEL_NAME", "synthetic-model")
    monkeypatch.delenv("AIWF_ACTOR_IDENTITY", raising=False)
    repo = BoundRepository(root, "fixture", 10, "read-write")
    result = asyncio.run(repo.mutate("record", ["--path", task, "--kind", "validation", "--result", "pass",
                                                "--agent-channel"], task, ".aiwf/records"))
    assert result["operation_status"] == "succeeded"
    event = events(root / task / ".aiwf/events.jsonl")[-1]
    assert event["configured_context"]["metadata"]["tool"] == "codex"
    assert event["configured_context"]["metadata"]["reasoning_effort"] == "high"
    assert event["configured_context"]["metadata"]["model_name"] == "synthetic-model"
    assert "synthetic-model" not in json.dumps(event["actor_identity"])


def test_older_query_contract_is_usable_without_writes(project):
    root, task = project
    runtime = root / ".aiwf/bin/ai_workflow.py"
    runtime.write_text(runtime.read_text().replace("MUTATION_CONTRACT_VERSION = 1", "MUTATION_CONTRACT_VERSION = 0"))
    (root / ".aiwf/docs/schemas/mutation_result_v1.schema.json").unlink()
    before = inventory(root)

    async def run():
        async with connect(root, *FLAGS) as client:
            assert {t.name for t in (await client.list_tools()).tools} == (TOOLS - {"aiwf_list_tasks"})
            context = successful(await client.call_tool("aiwf_context", {}))
            assert context["interface"]["write_operations"] == []
            assert "readable_records_roots" not in context["result"]
            assert successful(await client.call_tool("aiwf_inspect_task", {"task_path": task}))["result"]["task_path"] == task
            denied = envelope(await client.call_tool("aiwf_guard", {**BIND, "task_path": task}))
            assert denied["operation_status"] == "unsupported" and denied["mutation_state"] == "not_applied"
    asyncio.run(run())
    assert inventory(root) == before


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="requires an unprivileged POSIX writer")
def test_discovery_tracks_root_permissions_before_any_marker_or_task_write(project):
    root, task = project
    (root / ".aiwf/events").mkdir(exist_ok=True)
    previous_mode = root.stat().st_mode

    async def run():
        async with connect(root, *FLAGS) as client:
            assert {t.name for t in (await client.list_tools()).tools} == (WRITES | TOOLS)
            root.chmod(0o555)
            try:
                assert os.access(root / task, os.W_OK) and os.access(root / ".aiwf/events", os.W_OK)
                before = inventory(root)
                mtime = root.stat().st_mtime_ns
                ctx = successful(await client.call_tool("aiwf_context", {}))
                assert ctx["result"]["mutation_root_writable"] is False
                assert ctx["result"]["mutation_operations"] == ctx["interface"]["write_operations"] == []
                assert {t.name for t in (await client.list_tools()).tools} == TOOLS
                assert successful(await client.call_tool("aiwf_inspect_task", {"task_path": task}))
                denied = envelope(await client.call_tool("aiwf_new_task", {**BIND, "name": "protected"}))
                assert denied["runtime_exit_code"] is None
                child = cli(root, "mutate", "new-task", "protected")
                assert child.returncode == 2
                for reply in [denied, json.loads(child.stdout)]:
                    assert reply["operation_status"] == "unsupported"
                    assert reply["mutation_state"] == "not_applied" and not reply["requires_reconciliation"]
                    assert reply["diagnostics"][0]["code"] == "AIWF-LOCK-UNSUPPORTED"
                    assert "worktree root" in reply["diagnostics"][0]["message"]
                assert root.stat().st_mtime_ns == mtime and inventory(root) == before
            finally:
                root.chmod(previous_mode)
            mtime = root.stat().st_mtime_ns
            ctx = successful(await client.call_tool("aiwf_context", {}))
            assert ctx["result"]["mutation_root_writable"] is True
            assert set(ctx["interface"]["write_operations"]) == WRITES
            assert root.stat().st_mtime_ns == mtime
            created = envelope(await client.call_tool("aiwf_new_task", {**BIND, "name": "writable"}))
            assert created["mutation_state"] == "applied" and (root / created["target"]).is_dir()
    asyncio.run(run())


def test_two_stdio_servers_and_cli_share_create_record_index_lock(project):
    root, original = project
    common = {**BIND, "task_path": original}

    async def run():
        async with connect(root, *FLAGS) as first, connect(root, *FLAGS) as second:
            left, right, native = await asyncio.gather(
                first.call_tool("aiwf_new_task", {**BIND, "name": "parallel left"}),
                second.call_tool("aiwf_new_task", {**BIND, "name": "parallel right"}),
                asyncio.to_thread(cli, root, "new-task", "parallel native"))
            assert all(envelope(r)["operation_status"] == "succeeded" for r in [left, right])
            assert native.returncode == 0
            left, right, native = await asyncio.gather(
                first.call_tool("aiwf_new_task", {**BIND, "name": "identical"}),
                second.call_tool("aiwf_new_task", {**BIND, "name": "identical"}),
                asyncio.to_thread(cli, root, "new-task", "identical"))
            assert sum([envelope(left)["operation_status"] == "succeeded",
                        envelope(right)["operation_status"] == "succeeded", native.returncode == 0]) == 1
            got = successful(await first.call_tool("aiwf_list_tasks", {}))["result"]
            rows = got["tasks"]
            assert len({row["task_path"] for row in rows}) == len({row["task_id"] for row in rows}) == 5
            index = (root / original).parent / "index.md"
            text = index.read_text()
            assert all(text.count(f"`{Path(row['task_path']).name}`") == 1 for row in rows)
            writes = await asyncio.gather(
                first.call_tool("aiwf_record", {**common, "kind": "fix", "summary": "from first"}),
                second.call_tool("aiwf_sync_index", common),
                asyncio.to_thread(cli, root, "record", "--path", original, "--kind", "fix", "--summary", "from native"))
            assert all(envelope(r)["operation_status"] == "succeeded" for r in writes[:2])
            assert writes[2].returncode == 0
            for path in [root / original / ".aiwf/events.jsonl", root / ".aiwf/events/events.jsonl"]:
                fixes = [e["summary"] for e in events(path) if e.get("event") == "fix_recorded"]
                assert sorted(fixes) == ["from first", "from native"]
    asyncio.run(run())


def test_freshness_and_concurrent_finalize_fix(project, monkeypatch):
    root, task = project
    monkeypatch.syspath_prepend(str(ROOT / "tests/unit"))
    from test_ai_workflow import _rewrite_task_metadata, _write_finalize_ready_docs
    target = root / task
    _write_finalize_ready_docs(target)
    _rewrite_task_metadata(target / "task.md", required_review_authority="ai-agent", status="review", workflow_phase="review")
    assert cli(root, "sync-index", "--path", task).returncode == 0
    common = {**BIND, "task_path": task}

    async def run():
        async with connect(root, *FLAGS) as first, connect(root, *FLAGS) as second:
            async def record(**fields):
                entry = envelope(await first.call_tool("aiwf_record", {**common, **fields}))
                assert entry["operation_status"] == "succeeded", entry

            async def readiness(expected):
                entry = successful(await first.call_tool("aiwf_check_task", {"task_path": task, "mode": "finalize_readiness"}))
                assert entry["result"]["workflow_result"] == expected, entry["result"]["diagnostics"]

            await record(kind="validation", result="pass")
            await record(kind="review", result="fail")
            await readiness("BLOCKED")
            await record(kind="fix", summary="Synthetic repair for failed review")
            await readiness("BLOCKED")
            await record(kind="validation", result="pass")
            await readiness("BLOCKED")
            await record(kind="review", result="pass")
            await readiness("PASS")
            closure, fix = await asyncio.gather(
                first.call_tool("aiwf_finalize", common),
                second.call_tool("aiwf_record", {**common, "kind": "fix", "summary": "Concurrent synthetic fix"}))
            closed, fixed = envelope(closure), envelope(fix)
            state = successful(await first.call_tool("aiwf_inspect_task", {"task_path": task}))["result"]
            if closed["operation_status"] == "succeeded":
                assert state["closure_preserved"] and fixed["operation_status"] == "blocked"
            else:
                assert closed["operation_status"] == "blocked" and fixed["operation_status"] == "succeeded"
                assert state["workflow_phase"] != "finalized"
                await readiness("BLOCKED")
    asyncio.run(run())


def test_interrupted_writer_blocks_new_session_and_prevents_retry(project):
    root, task = project
    marker = root / ".aiwf-mutation-pending"
    marker.write_text(json.dumps({"version": 1, "operation": "record", "target": task}))
    before = inventory(root)

    async def run():
        for _ in range(2):
            async with connect(root, *FLAGS) as client:
                result = envelope(await client.call_tool("aiwf_record", {**BIND, "task_path": task, "kind": "fix",
                                                                         "summary": "Must never run"}))
                assert result["operation_status"] == "blocked" and result["mutation_state"] == "not_applied"
                assert result["requires_reconciliation"] and result["diagnostics"][0]["code"] == "AIWF-RECOVERY-REQUIRED"
    asyncio.run(run())
    assert inventory(root) == before


@pytest.mark.skipif(os.name != "posix", reason="holds the same POSIX repository lock as the Runtime")
def test_external_writer_lock_timeout_before_mutation(project):
    import fcntl
    root, task = project
    before = inventory(root)

    async def run():
        async with connect(root, *FLAGS, "--timeout-seconds", "9") as client:
            await client.list_tools()
            fd = os.open(root, os.O_DIRECTORY | os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                refused = envelope(await client.call_tool("aiwf_guard", {**BIND, "task_path": task}))
                assert refused["operation_status"] == "timeout" and refused["mutation_state"] == "not_applied"
                assert refused["diagnostics"][0]["code"] == "AIWF-LOCK-BUSY" and not refused["requires_reconciliation"]
            finally:
                os.close(fd)
    asyncio.run(run())
    assert inventory(root) == before


def test_operator_help_and_option_order(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp.operator import operator_parser

    for action, required, unrelated in [("review", "--result", "--current-state"),
                                        ("correction", "--current-state", "--summary")]:
        argv = [action, "--help"]
        with pytest.raises(SystemExit) as helped:
            operator_parser(argv).parse_args(argv)
        assert helped.value.code == 0
        text = capsys.readouterr().out
        assert required in text and unrelated not in text and "Example:" in text

    # Positional action may follow option values that themselves look like actions.
    argv = ["--summary", "correction", "--repo-root", "/worktree", "--task-path", "task",
            "--result", "pass", "review"]
    parsed = operator_parser(argv).parse_args(argv)
    assert parsed.action == "review" and parsed.summary == "correction"
    argv = ["review", "--repo-root", "/worktree", "--task-path", "task", "--result", "pass"]
    with pytest.raises(SystemExit) as missing:
        operator_parser(argv).parse_args(argv)
    assert missing.value.code == 2 and "--summary" in capsys.readouterr().err


def test_operator_requires_separate_identity_protected_policy_and_per_action_confirmation(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX operator policy only")
    import pwd
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp import operator

    # Temporary fixture stands in for a separate home; apply real ownership and permissions below that directory.
    home = tmp_path / "operator-home"
    policy = home / ".config/aiwf/mcp-operator.json"
    policy.parent.mkdir(parents=True)
    root = home / "worktree"
    (root / ".aiwf/bin").mkdir(parents=True)
    (root / ".aiwf/docs/schemas").mkdir(parents=True)
    (root / ".aiwf/config.yaml").write_text("version: 1")
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(home)))
    verify = operator.protected
    monkeypatch.setattr(operator, "protected", lambda path, uid: verify(path, uid) if path.is_relative_to(home) else None)
    grant = {"root": str(root), "agent_uid": os.geteuid() + 1, "binding_id": "project",
             "recorder": "fixture_operator", "correction_authority": "human_fixture"}
    policy.write_text(json.dumps([grant]))
    policy.chmod(0o644)
    with pytest.raises(operator.OperatorRefusal, match="0600"):
        operator.operator_grant(root)
    policy.chmod(0o600)
    assert operator.operator_grant(root) == grant
    policy.write_text(json.dumps([{**grant, "agent_uid": os.geteuid()}]))
    with pytest.raises(operator.OperatorRefusal, match="separate Agent UID"):
        operator.operator_grant(root)
    policy.write_text(json.dumps([grant, grant]))
    with pytest.raises(operator.OperatorRefusal, match="unique"):
        operator.operator_grant(root)
    repo = SimpleNamespace(root=root, binding_id="project")
    class FixtureTTY(io.StringIO):
        def isatty(self):
            return True
    output = FixtureTTY()
    monkeypatch.setattr(operator.secrets, "token_hex", lambda _: "fixture")
    args = {"task_path": ".aiwf/records/ai_20260101/001_case", "result": "fail", "summary": "synthetic"}
    with pytest.raises(operator.OperatorRefusal, match="terminal"):
        operator.confirm(io.StringIO("CONFIRM fixture\n"), output, repo, grant, "record", args)
    with pytest.raises(operator.OperatorRefusal, match="declined"):
        operator.confirm(FixtureTTY("CONFIRM stale\n"), output, repo, grant, "record", args)
    operator.confirm(FixtureTTY("CONFIRM fixture\n"), output, repo, grant, "record", args)
    assert all(value in output.getvalue() for value in [str(root), "human", args["task_path"], "synthetic"])


def test_synthetic_operator_channel_can_only_add_correction_after_finalize(project, monkeypatch):
    root, task = project
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    monkeypatch.syspath_prepend(str(ROOT / "tests/unit"))
    from aiwf_mcp import operator
    from aiwf_mcp.runtime import BoundRepository
    from test_ai_workflow import _rewrite_task_metadata, _write_finalize_ready_docs
    class ProbeClient(operator.Client):
        async def call_tool(self, name, approved):
            assert self.protocol_version == "2026-07-28"
            assert [tool.name for tool in (await self.list_tools()).tools] == [name]
            for tool, fields in [("aiwf_finalize", approved), (name, {**approved, "task_path": "another-task"})]:
                with pytest.raises(MCPError, match="Outside the confirmed operator action") as refusal:
                    await super().call_tool(tool, fields)
                assert refusal.value.code == -32602
            result = await super().call_tool(name, approved)
            envelope(result)
            with pytest.raises(MCPError, match="Outside the confirmed operator action") as replay:
                await super().call_tool(name, approved)
            assert replay.value.code == -32602
            return result

    monkeypatch.setattr(operator, "Client", ProbeClient)
    target = root / task
    _write_finalize_ready_docs(target)
    _rewrite_task_metadata(target / "task.md", status="review", workflow_phase="validation")
    note(root, task, "GUIDE-OPERATOR", scopes=["synthetic"])
    for op in [("sync-index",),
               ("record", "--kind", "validation", "--result", "pass", "--command", "fixture")]:
        result = cli(root, op[0], "--path", task, *op[1:])
        assert result.returncode == 0, result.stdout + result.stderr
    repo = BoundRepository(root, "synthetic-project", 10, "read-write", "fixture-operator")
    grant = {"recorder": repo.recorder, "correction_authority": "human_fixture"}
    review = {"task_path": task, "result": "pass", "summary": "Simulated human decision for disposable fixture"}
    correction = {"task_path": task, "type": "current_state_clarification",
                  "current_state": "Fixture revised", "reason": "Synthetic evidence after closure"}

    async def run():
        too_early = await operator.approved_call(repo, grant, "correction", correction)
        assert too_early["operation_status"] != "succeeded"
        assert (await operator.approved_call(repo, grant, "review", review))["operation_status"] == "succeeded"
        review_event = [e for e in events(target / ".aiwf/events.jsonl") if e.get("event") == "review_recorded"][-1]
        assert review_event["decision_authority"] == "human" and review_event["recorded_by"] == "fixture-operator"
        async with connect(root, *FLAGS) as client:
            closed = envelope(await client.call_tool("aiwf_finalize", {**BIND, "task_path": task}))
            assert closed["operation_status"] == "succeeded", closed
            duplicate = envelope(await client.call_tool("aiwf_finalize", {**BIND, "task_path": task}))
            assert duplicate["mutation_state"] == "already_applied"
            before = inventory(root)
            added = await operator.approved_call(repo, grant, "correction", correction)
            assert added["operation_status"] == "succeeded", added
            after = inventory(root)
            assert all(after.get(key) == old for key, old in before.items())
            assert added["result"]["path"] in after
            observed = successful(await client.call_tool("aiwf_inspect_task", {"task_path": task}))["result"]
            assert observed["closure_preserved"] and observed["latest_correction"]["current_effective_state"] == "Fixture revised"
            lookup = successful(await client.call_tool("aiwf_guidance_lookup", {"note_id": "GUIDE-OPERATOR"}))
            assert lookup["result"]["queries"][0]["exit_code"] == 1 and not lookup["result"]["candidate_ids"]
    asyncio.run(run())
