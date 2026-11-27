"""Compare independent synthetic CLI and MCP worktrees, including their full workflow records."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import shutil

from test_stdio import ROOT, cli, connect, inventory, project, successful
from test_workflow import BIND, FLAGS, envelope


def test_daily_writes_match_cli_files_events_index_and_manifest(project, tmp_path, monkeypatch):
    first, _ = project
    # Use a shared clock for the two copied runtimes so event and manifest comparisons
    # can keep every field, including hashes, decision authority and event sequence.
    runtime = first / ".aiwf/bin/ai_workflow.py"
    clock = 'return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")'
    source = runtime.read_text()
    assert source.count(clock) == 1
    stamp = (datetime.now(timezone.utc) + timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    runtime.write_text(source.replace(clock, f"return {stamp!r}"))
    second = tmp_path / "native"
    shutil.copytree(first, second)
    monkeypatch.syspath_prepend(str(ROOT / "tests/unit"))
    from test_ai_workflow import _rewrite_task_metadata, _set_index_status_for_task, _write_finalize_ready_docs

    def same():
        for area in (".aiwf/records", ".aiwf/events"):
            assert inventory(first / area) == inventory(second / area)

    async def compare():
        async with connect(first, *FLAGS) as session:
            async def paired(tool, fields, *argv):
                native = cli(second, *argv)
                assert native.returncode == 0, native.stdout + native.stderr
                receipt = envelope(await session.call_tool("aiwf_" + tool, {**BIND, **fields}))
                assert receipt["operation_status"] == "succeeded", receipt
                same()
                return receipt
            created = await paired("new_task", {"name": "parity", "title": "Parity sample", "risk": "low"},
                                   "new-task", "parity", "--title", "Parity sample", "--risk", "low")
            path = created["target"]
            fields = {"task_path": path}
            await paired("guard", fields, "guard", "--path", path, "--pre-edit")
            await paired("transition", {**fields, "to": "validation"}, "transition", "--path", path, "--to", "validation")
            # Declare synthetic agent-review policy before any review, provide engineering
            # evidence via Host files, and introduce the same repairable index drift.
            for root in (first, second):
                target = root / path
                _write_finalize_ready_docs(target)
                _rewrite_task_metadata(target / "task.md", required_review_authority="ai-agent")
                _set_index_status_for_task(target, "blocked")
            await paired("sync_index", fields, "sync-index", "--path", path)
            for kind, extra in (("fix", {"summary": "synthetic repair"}), ("safety_ack", {"summary": "fixture acknowledged"}),
                                ("validation", {"result": "pass", "command": "synthetic test | text"}),
                                ("review", {"result": "pass", "summary": "synthetic\u0085agent\u2028review\u2029PASS"})):
                argv = ["record", "--path", path, "--kind", kind]
                for key, value in extra.items():
                    argv.extend(["--" + key, value])
                if kind == "review":
                    argv.extend(["--decision-authority", "ai-agent", "--recorded-by", "fixture-recorder", "--reviewer", "ai-agent"])
                await paired("record", {**fields, "kind": kind, **extra}, *argv)
            before = inventory(first)
            ready = successful(await session.call_tool("aiwf_check_task", {**fields, "mode": "finalize_readiness"}))
            assert ready["result"]["workflow_result"] == "PASS", ready["result"]["diagnostics"]
            preview = successful(await session.call_tool("aiwf_check_task", {**fields, "mode": "finalize_preview"}))["result"]
            dry = cli(second, "finalize", "--dry-run", "--path", path)
            assert dry.returncode == 0 and preview["workflow_result"] == "PASS", (dry.stdout, preview)
            for key, value in preview["projected_metadata"].items():
                assert any(line.startswith("- " + key + ": ") and line.endswith(" -> " + value)
                           for line in dry.stdout.splitlines())
            assert before == inventory(first)
            await paired("finalize", fields, "finalize", "--path", path)
            closed = successful(await session.call_tool("aiwf_inspect_task", fields))["result"]
            assert closed["closure_preserved"] and closed["workflow_phase"] == "finalized"
            # Both guards must reject the same closed task without new workflow writes.
            blocked = envelope(await session.call_tool("aiwf_guard", {**BIND, **fields}))
            native = cli(second, "guard", "--path", path, "--pre-edit")
            assert native.returncode == 2 and blocked["operation_status"] == "blocked"
            assert all(d["code"] in native.stdout for d in blocked["diagnostics"])
            same()
    asyncio.run(compare())


def test_list_rejects_in_repository_aliases_at_each_level(project):
    root, raw = project
    task = root / raw
    outside = root / "other-project"
    outside.mkdir()
    for path in (task / "task.md", task, task.parent):
        original = outside / path.name
        path.rename(original)
        path.symlink_to(original, target_is_directory=original.is_dir())
        before = inventory(root)
        result = cli(root, "query", "list")
        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["execution"] == "error" and data["result"] is None
        assert inventory(root) == before
        path.unlink()
        original.rename(path)


def test_mixed_layout_lists_and_reads_legacy_tasks_under_their_own_paths(project):
    root, original = project
    config = root / ".aiwf/config.yaml"
    custom = "workflow/records"
    original_config = config.read_text().replace('record_root: ".aiwf/records"', f'record_root: "{custom}"')
    config.write_text(original_config)
    primary = root / custom
    primary.parent.mkdir()
    (root / ".aiwf/records").rename(primary)
    shutil.copytree(primary, root / "docs")
    suffix = original.removeprefix(".aiwf/records/")
    legacy = f"docs/{suffix}"
    scopes = [f"{custom}/{suffix}", legacy]
    # Project-owned documents may happen to match either directory pattern.
    (root / "docs/ai_20000101").write_text("meeting notes")
    (root / legacy).parent.joinpath("002_notes").write_text("project notes")

    async def check():
        async with connect(root, *FLAGS) as session:
            async def paths(**filters):
                rows = successful(await session.call_tool("aiwf_list_tasks", filters))["result"]
                return [row["task_path"] for row in rows["tasks"]], rows["truncated"]

            native = json.loads(cli(root, "export-json").stdout)["tasks"]
            assert [row["path"] for row in native] == scopes
            context = successful(await session.call_tool("aiwf_context", {}))["result"]
            assert context["readable_records_roots"] == [custom, "docs"]
            assert context["records_root"] == custom
            assert "Total: 2" in cli(root, "list").stdout
            assert await paths(status="draft") == (scopes, False)
            assert await paths(limit=1) == (scopes[:1], True)
            assert legacy in cli(root, "inspect", "--path", legacy).stdout
            for tool in ("aiwf_inspect_task", "aiwf_check_task", "aiwf_diagnostics"):
                result = successful(await session.call_tool(tool, {"task_path": legacy}))
                assert result["result"]["task_path"] == legacy

            before = inventory(root)
            args = {"task_path": legacy, "kind": "fix", "summary": "fixture"}
            denied = envelope(await session.call_tool("aiwf_record", {**BIND, **args}))
            assert denied["operation_status"] == "rejected" and denied["mutation_state"] == "not_applied"
            native_denial = cli(root, "mutate", "record", "--path", legacy, "--kind", "fix", "--summary", "fixture")
            assert json.loads(native_denial.stdout)["mutation_state"] == "not_applied"
            assert inventory(root) == before

            config.write_text(original_config.replace("legacy_enabled: true", "legacy_enabled: false"))
            assert await paths() == (scopes[:1], False)
            rejected = await session.call_tool("aiwf_inspect_task", {"task_path": legacy})
            assert rejected.is_error
            assert cli(root, "query", "inspect", "--path", legacy).returncode == 2

            config.write_text(original_config.replace(f'record_root: "{custom}"', 'record_root: "docs"'))
            assert await paths() == ([legacy], False)

            config.write_text(original_config)
            (root / "docs").rename(root / "aliased")
            (root / "docs").symlink_to(root / "aliased", target_is_directory=True)
            assert cli(root, "query", "context", "--full-workflow").returncode == 2
            for tool, fields in [("aiwf_list_tasks", {}), ("aiwf_inspect_task", {"task_path": legacy})]:
                assert (await session.call_tool(tool, fields)).is_error

    asyncio.run(check())


def test_machine_contract_rejects_invalid_inputs_without_writes(project):
    from jsonschema import Draft202012Validator
    root, task = project
    schema = json.loads((root / ".aiwf/docs/schemas/mutation_result_v1.schema.json").read_bytes())
    validator = Draft202012Validator(schema)
    before = inventory(root)
    for args in [("new-task", "sample", "--priority", "unrecognized"),
                 ("new-task", "bad", "--title", "two\nlines"),
                 ("record", "--path", task, "--agent-channel", "--kind", "review", "--result", "not_required",
                  "--decision-authority", "not_required", "--reviewer", "ai-agent", "--summary", "two\u2028lines")]:
        result = cli(root, "mutate", *args)
        receipt = json.loads(result.stdout)
        validator.validate(receipt)
        assert result.returncode == 2 and receipt["mutation_state"] == "not_applied"
        assert receipt["operation_status"] == "rejected" and receipt["diagnostics"]
        assert inventory(root) == before
    for status, bad_state in [("succeeded", "unknown"), ("timeout", "applied"), ("failed", "already_applied")]:
        assert not validator.is_valid({**receipt, "operation_status": status, "mutation_state": bad_state})
