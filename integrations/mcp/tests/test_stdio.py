"""Exercise the optional server through its public stdio protocol on synthetic repos."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest
import yaml


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
TOOLS = {"aiwf_context", "aiwf_inspect_task", "aiwf_check_task", "aiwf_diagnostics",
         "aiwf_guidance_lookup", "aiwf_list_tasks"}


def inventory(root):
    state = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            value = ("link", os.readlink(path))
        elif path.is_dir():
            value = ("dir", "")
        else:
            value = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        state[str(path.relative_to(root))] = value
    return state


def cli(root, *args, helper=False):
    script = root / ".aiwf/bin" / ("guidance.py" if helper else "ai_workflow.py")
    return subprocess.run([sys.executable, "-B", str(script), "--repo-root", str(root), *args],
                          cwd=root, capture_output=True, text=True, check=False)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(ROOT / ".aiwf/bin", root / ".aiwf/bin", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "aiwf", root / "aiwf")
    shutil.copy2(ROOT / ".aiwf/config.yaml", root / ".aiwf/config.yaml")
    schemas = root / ".aiwf/docs/schemas"
    schemas.mkdir(parents=True)
    shutil.copy2(ROOT / ".aiwf/docs/schemas/query_result_v1.schema.json", schemas)
    shutil.copy2(ROOT / ".aiwf/docs/schemas/mutation_result_v1.schema.json", schemas)
    (root / ".env").write_text("AIWF_EVENT_LOG=1\n")
    create = cli(root, "new-task", "synthetic")
    assert create.returncode == 0, create.stderr
    task = next(x.removeprefix("Task directory: ") for x in create.stdout.splitlines()
                if x.startswith("Task directory: "))
    return root, task


def note(root, task, note_id, *, scopes, drift=False):
    evidence = root / task / "summary.log"
    evidence.write_text("synthetic pass\n")
    data = dict(id=note_id, title="Synthetic comparison", status="active", scope=scopes,
                review_ref="Synthetic review", sources=[dict(
                    task=task, artifact="summary.log", locator="L1",
                    sha256="0" * 64 if drift else hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    reviewed_corrections=[])])
    directory = root / ".aiwf/guidance"
    directory.mkdir(exist_ok=True)
    body = "\n".join("## " + title + "\n\nSynthetic evidence.\n" for title in (
        "Recommended Checks", "Applicability", "Inapplicable Cases",
        "Evidence and Limitations", "Recheck Triggers"))
    (directory / (note_id + ".md")).write_text("---\n" + yaml.safe_dump(data) + "---\n\n" + body)


@asynccontextmanager
async def connect(root, *server_flags, env=None):
    params = StdioServerParameters(
        command=sys.executable, args=["-B", "-m", "aiwf_mcp", "--repo-root", str(root), *server_flags],
        cwd=root.parent, env={"PYTHONPATH": str(PACKAGE / "src"), "AIWF_EVENT_LOG": "1", **(env or {})})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams, read_timeout_seconds=35) as session:
            discovery = await session.discover()
            assert "2026-07-28" in discovery.supported_versions
            yield session


def successful(response):
    assert not response.is_error, response.structured_content
    data = response.structured_content
    assert isinstance(data, dict)
    assert data["consistency"] == "unconfirmed"
    assert json.loads(response.content[0].text) == data
    return data


def age_seconds(formatted):
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(part[:-1]) * units[part[-1]] for part in formatted.split())


def test_discovery_cli_parity_and_concurrent_reads(project):
    root, task = project
    before = inventory(root)

    async def run():
        async with connect(root) as client:
            assert {t.name for t in (await client.list_tools()).tools} == TOOLS
            ctx = successful(await client.call_tool("aiwf_context", {}))
            assert ctx["repository"]["root_verified"]
            checks = [
                ("aiwf_inspect_task", "inspect", {}, []),
                ("aiwf_check_task", "check", {}, []),
                ("aiwf_check_task", "check", {"mode": "finalize_readiness"}, ["--finalize-ready"]),
                ("aiwf_diagnostics", "diagnostics", {}, []),
            ]
            started = time.monotonic()
            results = await asyncio.gather(*(client.call_tool(name, {"task_path": task, **extra})
                                             for name, _, extra, _ in checks))
            for (_, op, _, flags), result in zip(checks, results):
                wire = successful(result)
                raw = cli(root, "query", op, "--path", task, *flags)
                native = json.loads(raw.stdout)
                assert raw.returncode == native["exit_code"] == wire["exit_code"]
                if op == "diagnostics":
                    # These independent processes consult the wall clock. Verify the
                    # elapsed difference and compare the actual event timestamp below.
                    key = "age_since_last_activity"
                    a = wire["result"]["derived_evidence"]["activity"].pop(key)
                    b = native["result"]["derived_evidence"]["activity"].pop(key)
                    assert 0 <= age_seconds(b) - age_seconds(a) <= time.monotonic() - started + 1
                assert wire["result"] == native["result"]
            ready = successful(results[2])
            assert ready["result"]["workflow_result"] == "BLOCKED"
            assert ready["exit_code"] == 2

    asyncio.run(run())
    assert inventory(root) == before


@pytest.mark.parametrize("old_helper", [False, True], ids=["current", "query-v1-only"])
def test_guidance_preserves_each_scope_and_invalidates_bad_collection(project, old_helper):
    root, task = project
    if old_helper:
        helper = root / ".aiwf/bin/guidance.py"
        helper.write_text(helper.read_text().replace("GUIDANCE_SCOPE_METADATA_VERSION = 1",
                                                     "assert '--metadata-only' not in sys.argv"))
    note(root, task, "GUIDE-CURRENT", scopes=["validation", "regression"])
    note(root, task, "GUIDE-STALE", scopes=["regression"], drift=True)
    before = inventory(root)

    async def run():
        async with connect(root) as client:
            scopes = ["regression", "validation", "nothing"]
            got = successful(await client.call_tool("aiwf_guidance_lookup", {"scopes": scopes}))["result"]
            assert got["candidate_ids"] == ["GUIDE-CURRENT"]
            assert [q["exit_code"] for q in got["queries"]] == [1, 0, 0]
            for scope, query in zip(scopes, got["queries"]):
                native = cli(root, "show", "--format", "json", "--scope", scope, helper=True)
                assert query["exit_code"] == native.returncode
                expected = json.loads(native.stdout)["result"]["notes"]
                assert all(n["body"] is None for n in query["result"]["notes"])
                assert [(n["id"], n["eligible"], n["source_state"]) for n in query["result"]["notes"]] == [
                    (n["id"], n["eligible"], n["source_state"]) for n in expected]
            assert inventory(root) == before
            (root / ".aiwf/guidance/invalid.md").write_text("malformed fixture")
            changed = inventory(root)
            bad = await client.call_tool("aiwf_guidance_lookup", {"scopes": ["validation"]})
            assert bad.is_error
            assert "GUIDE-CURRENT" not in str(bad.content)
            assert inventory(root) == changed

    asyncio.run(run())


def test_guidance_scope_projects_large_bodies_before_the_output_limit(project):
    root, task = project
    ids = ["GUIDE-A", "GUIDE-B"]
    for note_id in ids:
        note(root, task, note_id, scopes=["regression"])
        with (root / ".aiwf/guidance" / (note_id + ".md")).open("a") as file:
            file.write("Synthetic evidence. " * 3600)
    native = cli(root, "show", "--format", "json", "--scope", "regression", helper=True)
    assert native.returncode == 0 and len(native.stdout.encode()) > 128 * 1024
    full_notes = json.loads(native.stdout)["result"]["notes"]

    async def run():
        async with connect(root) as client:
            lookup = successful(await client.call_tool("aiwf_guidance_lookup", {"scopes": ["regression"]}))
            assert lookup["result"]["candidate_ids"] == ids
            metadata = lookup["result"]["queries"][0]["result"]["notes"]
            assert metadata == [{**entry, "body": None} for entry in full_notes]
            for entry in full_notes:
                by_id = successful(await client.call_tool("aiwf_guidance_lookup", {"note_id": entry["id"]}))
                assert by_id["result"]["queries"][0]["result"]["notes"] == [entry]
    asyncio.run(run())


def test_rejects_invalid_inputs_and_unbound_paths(project, tmp_path):
    root, task = project
    other_repo = tmp_path / "other"
    shutil.copytree(root, other_repo)
    outside = other_repo / task
    with (outside / "task.md").open("a") as out:
        out.write("\nSynthetic outside marker\n")
    assert cli(other_repo, "query", "inspect", "--path", task).returncode == 0
    link = root / task
    link.rename(link.with_name("002_original"))
    link.symlink_to(outside, target_is_directory=True)
    before, other_before = inventory(root), inventory(other_repo)

    async def run():
        async with connect(root) as client:
            for name, args in [
                ("aiwf_context", {"repo_root": str(other_repo)}),
                ("aiwf_inspect_task", {"task_path": str(outside)}),
                ("aiwf_inspect_task", {"task_path": "../other"}),
                ("aiwf_inspect_task", {"task_path": task}),
                ("aiwf_check_task", {"task_path": "001"}),
                ("aiwf_check_task", {"task_path": 3}),
                ("aiwf_guidance_lookup", {"scopes": []}),
                ("aiwf_guidance_lookup", {"scopes": [" "]}),
                ("aiwf_guidance_lookup", {"scopes": ["regression"], "note_id": "GUIDE-CURRENT"}),
            ]:
                answer = await client.call_tool(name, args)
                assert answer.is_error, (name, args, answer)
                assert "Synthetic outside marker" not in str(answer.content)

    asyncio.run(run())
    assert inventory(root) == before
    assert inventory(other_repo) == other_before


def test_no_fallback_to_server_installation(project):
    root, task = project
    (root / ".aiwf/bin/guidance.py").unlink()
    before = inventory(root)

    async def run():
        async with connect(root) as client:
            response = await client.call_tool("aiwf_guidance_lookup", {"scopes": ["regression"]})
            assert response.is_error
            assert "unavailable" in str(response.content).lower()
            assert inventory(root) == before

    asyncio.run(run())


@pytest.mark.parametrize(("replacement", "expected"), [
    (None, "unavailable"),
    ("# legacy component without the query contract", "unsupported"),
    ("QUERY_CONTRACT_VERSION = 1\nprint('not JSON')", "invalid_response"),
    ("QUERY_CONTRACT_VERSION = 1\nimport sys\nsys.exit(9)", "process_failed"),
    ("QUERY_CONTRACT_VERSION = 1\nprint('x' * 140000)", "output_limit"),
    ("QUERY_CONTRACT_VERSION = 1\nimport time\ntime.sleep(5)", "timeout"),
])
def test_runtime_failure_does_not_produce_governance_result(project, replacement, expected):
    root, _ = project
    runtime = root / ".aiwf/bin/ai_workflow.py"
    if replacement is None:
        runtime.unlink()
    else:
        runtime.write_text(replacement)
    before = inventory(root)

    async def run():
        async with connect(root, "--timeout-seconds", "0.5") as client:
            response = await client.call_tool("aiwf_context", {})
            assert response.is_error
            assert response.structured_content["error"]["code"] == expected
            assert response.structured_content["result"] is None

    asyncio.run(run())
    assert inventory(root) == before


def test_correction_added_after_review_and_unavailable_source(project):
    root, task = project
    note(root, task, "GUIDE-PROJECT", scopes=["validation"])
    correction = root / task / "POST_FINALIZATION_CORRECTION.md"
    correction.write_text("# Post-finalization correction\n\n## reason\n\nA\n\n"
                          "## semantic_impact\n\nB\n\n## corrected_statement\n\nC\n")

    async def run():
        async with connect(root) as client:
            for phrase in ("corrections added", "source unavailable"):
                if phrase == "source unavailable":
                    (root / task / "summary.log").unlink()
                before = inventory(root)
                wire = successful(await client.call_tool("aiwf_guidance_lookup", {"note_id": "GUIDE-PROJECT"}))
                assert not wire["result"]["candidate_ids"]
                entry = wire["result"]["queries"][0]
                native = cli(root, "show", "--format", "json", "--id", "GUIDE-PROJECT", helper=True)
                assert native.returncode == entry["exit_code"] == 1
                assert entry["result"] == json.loads(native.stdout)["result"]
                guidance = entry["result"]["notes"][0]
                assert not guidance["eligible"] and phrase in " ".join(guidance["issues"])
                assert inventory(root) == before

    asyncio.run(run())


def test_bound_installation_cannot_launch_missing_interpreter(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp.runtime import QueryError, run_process

    with pytest.raises(QueryError) as error:
        asyncio.run(run_process([str(tmp_path / "missing-python")], tmp_path, 1))
    assert error.value.code == "launch_failed"


def test_detect_change_between_task_observations(project, monkeypatch):
    # Synchronize a synthetic external editor with the two observations.
    monkeypatch.syspath_prepend(str(PACKAGE / "src"))
    from aiwf_mcp.runtime import BoundRepository, QueryError
    from aiwf_mcp.server import invoke

    root, task = project
    repo = BoundRepository(root, "fixture", 2)
    original = repo.query

    async def run():
        started, edited = asyncio.Event(), asyncio.Event()

        async def query(operation, args, validator):
            if operation == "inspect":
                started.set()
                await edited.wait()
            return await original(operation, args, validator)

        async def editor():
            await started.wait()
            with (root / task / "task.md").open("a") as out:
                out.write("\nSynthetic external edit.\n")
            edited.set()

        monkeypatch.setattr(repo, "query", query)
        writer = asyncio.create_task(editor())
        with pytest.raises(QueryError) as error:
            await invoke(repo, "inspect", {"task_path": task})
        await writer
        assert error.value.code == "concurrent_change"

    asyncio.run(run())
