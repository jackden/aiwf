"""Check stdio bytes directly, including fields that a typed SDK could fill or discard."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
import sys

import anyio
from jsonschema import Draft202012Validator
import pytest

from test_stdio import PACKAGE, TOOLS, inventory, project
from test_workflow import BIND, FLAGS, WRITES


MODERN = "2026-07-28"
LEGACY = "2025-11-25"
VERSION = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO = "io.modelcontextprotocol/serverInfo"
META = {VERSION: MODERN, CAPABILITIES: {}}
INITIALIZE = {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}


class WirePeer:
    def __init__(self, process):
        self.process = process
        self.next_id = 1

    async def send(self, method, params, request_id=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params):
        request_id = self.next_id
        self.next_id += 1
        await self.send(method, params, request_id)
        line = await asyncio.wait_for(self.process.stdout.readline(), 15)
        assert line.endswith(b"\n"), f"Missing stdout response to {method}"
        response = json.loads(line)
        assert response["jsonrpc"] == "2.0" and response["id"] == request_id, response
        return response


@asynccontextmanager
async def wire(root, *flags):
    installed = os.environ.get("AIWF_MCP_TEST_INSTALLED") == "1"
    env = {**os.environ, "AIWF_EVENT_LOG": "1"}
    python_flags = ["-B"]
    if installed:
        python_flags.append("-I")
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(PACKAGE / "src")
    child = await asyncio.create_subprocess_exec(
        sys.executable, *python_flags, "-m", "aiwf_mcp", "--repo-root", str(root), *flags,
        cwd=root.parent, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=1024 * 1024,
    )
    try:
        yield WirePeer(child)
    finally:
        child.stdin.close()
        try:
            await asyncio.wait_for(child.wait(), 5)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()
            raise
        assert child.returncode == 0
        assert await child.stdout.read() == b"", "Unexpected trailing stdio frame"


def params(name, arguments):
    return {"name": name, "arguments": arguments, "_meta": META}


def tool_result(response, error=False, *, modern=True):
    result = response["result"]
    if modern:
        assert result["resultType"] == "complete"
        assert result["_meta"][SERVER_INFO]["name"] == "aiwf-mcp"
    else:
        assert "resultType" not in result
    assert result.get("isError", False) is error
    payload = result["structuredContent"]
    assert json.loads(result["content"][0]["text"]) == payload
    return payload


def test_first_request_tool_call_read_write_and_blocked_results(project):
    root, target = project

    async def run():
        async with wire(root, *FLAGS) as peer:
            context = tool_result(await peer.request("tools/call", params("aiwf_context", {})))
            assert context["repository"]["binding_id"] == BIND["binding_id"]
            listing = (await peer.request("tools/list", {"_meta": META}))["result"]
            assert listing["resultType"] == "complete" and listing["ttlMs"] == 0
            assert listing["cacheScope"] == "private" and "nextCursor" not in listing
            specs = {entry["name"]: entry for entry in listing["tools"]}
            assert set(specs) == TOOLS | WRITES and len(listing["tools"]) == len(specs)
            for name, spec in specs.items():
                assert spec["inputSchema"]["type"] == "object"
                Draft202012Validator.check_schema(spec["inputSchema"])
                Draft202012Validator.check_schema(spec["outputSchema"])
                assert spec["annotations"]["readOnlyHint"] is (name in TOOLS)
            Draft202012Validator(specs["aiwf_context"]["outputSchema"]).validate(context)

            created = tool_result(await peer.request("tools/call", params("aiwf_new_task", {**BIND, "name": "wire"})))
            assert created["operation_status"] == "succeeded" and (root / created["target"] / "task.md").is_file()
            Draft202012Validator(specs["aiwf_new_task"]["outputSchema"]).validate(created)

            args = {"task_path": target, "mode": "finalize_readiness"}
            ready = tool_result(await peer.request("tools/call", params("aiwf_check_task", args)))
            assert ready["result"]["workflow_result"] == "BLOCKED" and ready["exit_code"] == 2
            close = tool_result(await peer.request("tools/call", params("aiwf_finalize", {**BIND, "task_path": target})),
                                error=True)
            assert close["operation_status"] == "blocked" and close["result"]["finalized"] is False
            assert close["mutation_state"] == ("applied" if close["result"]["audit_written"] else "not_applied")
            Draft202012Validator(specs["aiwf_finalize"]["outputSchema"]).validate(close)

    asyncio.run(run())


def test_discovery_metadata_errors_and_recovery(project):
    root, _ = project
    before = inventory(root)

    async def run():
        async with wire(root, *FLAGS) as peer:
            discovery = (await peer.request("server/discover", {"_meta": META}))["result"]
            assert MODERN in discovery["supportedVersions"]
            assert "tools" in discovery["capabilities"]
            assert discovery["resultType"] == "complete" and discovery["ttlMs"] == 0
            assert discovery["cacheScope"] == "private" and discovery["_meta"][SERVER_INFO]["version"]
            # Metadata on discovery must never authorize the next invocation.
            create = {"name": "aiwf_new_task", "arguments": {**BIND, "name": "unrequested"}}
            for meta in ({}, {VERSION: MODERN}, {CAPABILITIES: {}}, {VERSION: MODERN, CAPABILITIES: "invalid"}):
                reply = await peer.request("tools/call", {**create, "_meta": meta})
                assert reply["error"]["code"] == -32602, (meta, reply)
            unsupported = {**META, VERSION: "1900-01-01"}
            rejected = (await peer.request("tools/call", {**create, "_meta": unsupported}))["error"]
            assert rejected["code"] == -32022
            assert rejected["data"]["requested"] == unsupported[VERSION]
            assert MODERN in rejected["data"]["supported"]
            for cursor in ("", "unknown-page"):
                reply = await peer.request("tools/list", {"_meta": META, "cursor": cursor})
                assert reply["error"]["code"] == -32602
            assert (await peer.request("prompts/list", {"_meta": META}))["error"]["code"] == -32601
            for invalid in (params("absent_tool", {}), {"_meta": META}, params("aiwf_context", []),
                            params("aiwf_context", None)):
                assert (await peer.request("tools/call", invalid))["error"]["code"] == -32602
            assert (await peer.request("initialize", INITIALIZE))["error"]["code"] == -32022
            recovered = tool_result(await peer.request("tools/call", params("aiwf_context", {})))
            assert recovered["repository"]["root_verified"]
    asyncio.run(run())
    assert inventory(root) == before


def test_legacy_handshake_list_call_and_mixed_era_refusal(project):
    root, _ = project

    async def run():
        async with wire(root, *FLAGS) as peer:
            response = (await peer.request("initialize", INITIALIZE))["result"]
            assert response["protocolVersion"] == LEGACY and "tools" in response["capabilities"]
            assert response["serverInfo"]["name"] == "aiwf-mcp"
            await peer.send("notifications/initialized", {})
            listing = (await peer.request("tools/list", {}))["result"]
            assert "resultType" not in listing and "ttlMs" not in listing and "cacheScope" not in listing
            assert {tool["name"] for tool in listing["tools"]} == TOOLS | WRITES
            modern = await peer.request("server/discover", {"_meta": META})
            assert modern["error"]["code"] == -32600
            ctx = tool_result(await peer.request("tools/call", {"name": "aiwf_context", "arguments": {}}), modern=False)
            assert ctx["repository"]["root_verified"]
            write = {"name": "aiwf_new_task", "arguments": {**BIND, "name": "legacy wire"}}
            created = tool_result(await peer.request("tools/call", write), modern=False)
            assert created["operation_status"] == "succeeded" and (root / created["target"] / "task.md").is_file()
    asyncio.run(run())


def test_rate_limited_invocations_do_not_reach_workflow(project):
    root, _ = project
    before = inventory(root)

    async def run():
        async with wire(root, *FLAGS) as peer:
            invalid = params("aiwf_inspect_task", {})
            for _ in range(60):
                result = tool_result(await peer.request("tools/call", invalid), error=True)
                assert result["error"]["code"] == "invalid_input"
            limited = tool_result(await peer.request("tools/call", params("aiwf_context", {})), error=True)
            assert limited["error"]["code"] == "rate_limited"
            limited = tool_result(await peer.request("tools/call", params("aiwf_new_task", {**BIND, "name": "limited"})),
                                  error=True)
            assert limited["diagnostics"][0]["code"] == "rate_limited"
            assert limited["mutation_state"] == "not_applied" and not limited["requires_reconciliation"]
    asyncio.run(run())
    assert inventory(root) == before


@pytest.mark.skipif(os.name != "posix", reason="uses a POSIX process-existence probe")
@pytest.mark.parametrize("modern", [True, False], ids=["modern", "legacy"])
def test_wire_cancellation_reaps_original_mutation_and_keeps_server_available(project, modern):
    root, target = project
    runtime = root / ".aiwf/bin/ai_workflow.py"
    pid_file = root / "fixture-mutation.pid"
    source = runtime.read_text()
    launch = 'if __name__ == "__main__":\n    raise SystemExit(main())\n'
    assert source.endswith(launch)
    runtime.write_text(source.removesuffix(launch) + """if __name__ == "__main__" and "mutate" in sys.argv:
    import time
    with open("fixture-mutation.pid", "a") as stream:
        print(os.getpid(), file=stream)
    time.sleep(15)
""" + launch)

    async def run():
        async with wire(root, *FLAGS, "--timeout-seconds", "30") as peer:
            metadata = {"_meta": META} if modern else {}
            if not modern:
                reply = await peer.request("initialize", INITIALIZE)
                assert reply["result"]["protocolVersion"] == LEGACY
                await peer.send("notifications/initialized", {})
            await peer.send("tools/call", {**metadata, "name": "aiwf_guard",
                                          "arguments": {**BIND, "task_path": target}}, "cancel-me")
            with anyio.fail_after(8):
                while not pid_file.exists() or not pid_file.stat().st_size:
                    await asyncio.sleep(0.02)
            pid = int(pid_file.read_text())
            await peer.send("notifications/cancelled", {"requestId": "cancel-me", "reason": "synthetic test"})
            with anyio.fail_after(5):
                while True:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    await asyncio.sleep(0.02)
            assert pid_file.read_text().splitlines() == [str(pid)]
            response = await peer.request("tools/call", {**metadata, "name": "aiwf_context", "arguments": {}})
            reply = tool_result(response, modern=modern)
            assert reply["repository"]["root_verified"]
    asyncio.run(run())
