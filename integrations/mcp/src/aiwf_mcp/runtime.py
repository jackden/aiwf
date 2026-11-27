"""Bounded invocations of a trusted, explicitly bound AIWF installation."""

import asyncio
import hashlib
import json
import os
import re
import signal
import stat
import sys
from pathlib import Path

import anyio
from jsonschema import Draft202012Validator
from referencing import Registry


OUTPUT_BYTES = 128 * 1024
CLEANUP_SECONDS = 1.0
SCHEMA_PATH = ".aiwf/docs/schemas/query_result_v1.schema.json"
MUTATION_SCHEMA_PATH = ".aiwf/docs/schemas/mutation_result_v1.schema.json"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class QueryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def error_result(operation, exc):
    return {"contract_version": 1, "operation": operation, "execution": "error",
            "exit_code": None, "result": None, "error": {"code": exc.code, "message": str(exc)}}


def invalid_response():
    return QueryError("invalid_response", "The installed runtime returned an invalid query result.")


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON key")
    return result


def parse_json(data):
    def reject_constant(_):
        raise ValueError("non-finite JSON number")

    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


async def read_limited(reader):
    data = bytearray()
    while chunk := await reader.read(8192):
        if len(data) + len(chunk) > OUTPUT_BYTES:
            raise QueryError("output_limit", "Runtime output exceeded the byte limit.")
        data.extend(chunk)
    return bytes(data)


async def stop_process(child):
    group_confirmed = True
    if os.name == "posix":
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            group_confirmed = False
    if child.returncode is None and (os.name != "posix" or not group_confirmed):
        try:
            child.kill()
        except OSError:
            pass  # The final wait can still confirm a direct child's natural exit.

    # Process.wait() can hang on a full or inherited pipe after the child exits.
    # The high-level Process exposes no close method for its read pipe transports.
    for fd in (1, 2):
        child._transport.get_pipe_transport(fd).close()
    try:
        await asyncio.wait_for(child.wait(), CLEANUP_SECONDS)
    except (asyncio.TimeoutError, OSError):
        return False
    return group_confirmed


async def run_process(argv, cwd, timeout, *, write=False):
    # Keep host credentials, event flags, and user-supplied Python import paths
    # out of the child. The caller supplies a fixed interpreter and argv.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TZ") if k in os.environ}
    env["PATH"] = os.defpath
    if write:
        for key in ("AIWF_ACTOR", "AIWF_ACTOR_IDENTITY", "AIWF_EVENT_LOG", "AIWF_WORKFLOW_MODE",
                    "AIWF_MODEL_NAME", "AIWF_MODEL_CLASS", "AIWF_MODEL_PROVIDER", "AIWF_AGENT_TOOL",
                    "AIWF_REASONING_EFFORT", "AIWF_METADATA_SOURCE", "AIWF_METADATA_CONFIDENCE"):
            if key in os.environ:
                env[key] = os.environ[key]
    else:
        env["AIWF_EVENT_LOG"] = "0"
    # Observe a pending cancellation before dispatch. Once the OS spawn starts,
    # retain that one launch through pipe setup so cleanup can own its handle.
    await anyio.lowlevel.checkpoint()
    launch = asyncio.create_task(asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == "posix",
    ))
    try:
        child = await asyncio.shield(launch)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            try:
                child = await launch
            except OSError:
                pass  # Launch failed before handing back a process.
            else:
                await stop_process(child)
        raise
    except OSError:
        raise QueryError("launch_failed", "Could not launch the bound runtime.") from None

    pending = [asyncio.create_task(read_limited(pipe)) for pipe in (child.stdout, child.stderr)]
    pending.append(asyncio.create_task(child.wait()))
    try:
        with anyio.fail_after(timeout):
            stdout, _, code = await asyncio.gather(*pending)
        return stdout, code
    except BaseException as exc:
        # MCP cancels the handler's AnyIO scope. Its next await can be
        # cancelled again, even after we have caught the initial exception.
        with anyio.CancelScope(shield=True):
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            confirmed = await stop_process(child)
        if isinstance(exc, (QueryError, TimeoutError)):
            failure = (QueryError("timeout", "The bound runtime exceeded its time limit.")
                       if isinstance(exc, TimeoutError) else exc)
            if not confirmed:
                raise QueryError(failure.code, f"{failure} Runtime cleanup could not be confirmed.") from None
            raise failure from None
        raise


def script_advertises(script, marker):
    with script.open("rb") as stream:
        return marker in stream.read(1024 * 1024).splitlines()


class BoundRepository:
    def __init__(self, root: Path, binding_id: str | None, timeout: float,
                 mode: str = "read-only", recorder: str = "aiwf-mcp"):
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("repo-root must be an existing absolute directory")
        self.root = root.resolve(strict=True)
        self.identity = self.root.stat()
        self.binding_id = binding_id or hashlib.sha256(os.fsencode(self.root)).hexdigest()[:16]
        if not IDENTIFIER.fullmatch(self.binding_id):
            raise ValueError("binding-id must be a nonempty ASCII identifier of at most 128 characters")
        if not 0.1 <= timeout <= 60:
            raise ValueError("timeout-seconds must be between 0.1 and 60")
        self.timeout = timeout
        if mode not in ("read-only", "read-write"):
            raise ValueError("invalid startup mode")
        if not IDENTIFIER.fullmatch(recorder):
            raise ValueError("recorder must be a nonempty identifier")
        self.mode = mode
        self.recorder = recorder

    def path(self, relative):
        parts = relative.split("/")
        if ("\\" in relative or ":" in relative
                or any(part in ("", ".", "..") or not part.isprintable() for part in parts)):
            raise QueryError("invalid_path", "Expected a canonical repository-relative path.")
        path = self.root
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise QueryError("unsafe_path", "A required repository path contains a symlink.")
        return path

    def verify_root(self):
        try:
            unchanged = self.root.resolve() == self.root and os.path.samestat(self.identity, self.root.stat())
        except (OSError, RuntimeError):
            unchanged = False
        if not unchanged:
            raise QueryError("binding_changed", "The bound directory changed. Restart the server.")

    def check_binding(self):
        self.verify_root()
        bin_dir = self.path(".aiwf/bin")
        if not bin_dir.exists():
            raise QueryError("unavailable", "The bound project has no installed AIWF runtime.")
        # Python imports sibling packages when starting a bound script.
        # Check every component before executing any repository-owned code.
        for directory, dirs, files in os.walk(bin_dir, onerror=_raise_walk_error):
            for name in dirs + files:
                mode = (Path(directory) / name).lstat().st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise QueryError("unsafe_path", "The runtime tree contains an unsupported file type.")
        config = self.path(".aiwf/config.yaml")
        if config.exists() and not config.is_file():
            raise QueryError("unsafe_path", "Expected a regular config file.")

    def contract_script(self, guidance=False, *, write=False):
        name = "guidance.py" if guidance else "ai_workflow.py"
        marker = b"GUIDANCE_QUERY_CONTRACT_VERSION = 1" if guidance else b"QUERY_CONTRACT_VERSION = 1"
        if write:
            marker = b"MUTATION_CONTRACT_VERSION = 1"
        script = self.path(".aiwf/bin/" + name)
        if not script.is_file():
            raise QueryError("unavailable", "The requested runtime component is missing.")
        if not script_advertises(script, marker):
            raise QueryError("unsupported", "The installed component does not advertise the required contract.")
        return script

    def validator(self, *, write=False):
        path = self.path(MUTATION_SCHEMA_PATH if write else SCHEMA_PATH)
        if not path.is_file():
            raise QueryError("unsupported", "The required installed result schema is missing.")
        try:
            with path.open("rb") as stream:
                data = stream.read(OUTPUT_BYTES + 1)
            if len(data) > OUTPUT_BYTES:
                raise ValueError("schema exceeds size limit")
            schema = parse_json(data)
            Draft202012Validator.check_schema(schema)
            # The installed contract uses internal references. External URIs
            # cannot initiate network or filesystem access through this registry.
            return Draft202012Validator(schema, registry=Registry())
        except Exception:
            raise QueryError("invalid_schema", "The installed result schema is invalid.") from None

    def task(self, path, *records_roots):
        target = self.path(path)
        if (target.parent.parent not in (self.path(name) for name in records_roots)
                or not re.fullmatch(r"ai_[0-9]{8}", target.parent.name)
                or not re.fullmatch(r"[0-9]{3}_[a-z0-9][a-z0-9_]*", target.name)):
            raise QueryError("invalid_path", "Expected a dated task path below an allowed records root.")
        if not target.is_dir():
            raise QueryError("task_missing", "The specified task directory does not exist.")
        return target

    async def query(self, operation, args, validator):
        guidance = operation == "guidance"
        script = self.contract_script(guidance)
        if (guidance and args[:1] == ["--scope"]
                and script_advertises(script, b"GUIDANCE_SCOPE_METADATA_VERSION = 1")):
            args = [*args, "--metadata-only"]
        if operation == "context":
            try:
                self.contract_script(write=True)
            except QueryError as exc:
                if exc.code != "unsupported":
                    raise
            else:
                args = [*args, "--full-workflow"]
        command = ["show", "--format", "json"] if guidance else ["query", operation]
        argv = [sys.executable, "-EsB", str(script), "--repo-root", str(self.root), *command, *args]
        stdout, code = await run_process(argv, self.root, self.timeout)
        if code not in (0, 1, 2):
            raise QueryError("process_failed", "The bound runtime terminated without a supported exit status.")
        try:
            response = parse_json(stdout)
            validator.validate(response)
            if response["contract_version"] != 1 or response["operation"] != operation or response["exit_code"] != code:
                raise ValueError("response does not match invocation")
        except Exception:
            raise invalid_response() from None
        return response

    async def mutate(self, operation, args, target, records_root):
        if self.mode != "read-write":
            raise QueryError("permission_denied", "This server was started in read-only mode.")
        try:
            self.check_binding()
            script = self.contract_script(write=True)
            validator = self.validator(write=True)
        except OSError:
            raise QueryError("preflight_failed", "The bound Runtime could not be verified before launch.") from None
        argv = [sys.executable, "-EsB", str(script), "--repo-root", str(self.root), "mutate", operation, *args]
        try:
            stdout, code = await run_process(argv, self.root, self.timeout, write=True)
        except QueryError as exc:
            return mutation_error(operation, exc, target, started=exc.code != "launch_failed")
        except (OSError, ValueError, RuntimeError):
            exc = QueryError("process_failed", "Communication failed after launching the mutation.")
            return mutation_error(operation, exc, target, started=True)
        try:
            reply = parse_json(stdout)
            validator.validate(reply)
            if (reply["contract_version"] != 1 or reply["operation"] != operation or
                    reply["runtime_exit_code"] != code or
                    (target and reply["target"] not in (None, target))):
                raise ValueError("mutation result does not match invocation")
            self.verify_root()
            if reply["operation_status"] == "succeeded":
                if target and reply["target"] != target:
                    raise ValueError("successful mutation omitted its confirmed target")
                self.task(reply["target"], records_root)
            return reply
        except Exception:
            return mutation_error(operation, invalid_response(), target, started=True, runtime_code=code)


def mutation_error(operation, exc, target=None, *, started=False, runtime_code=None):
    needs_reconciliation = started or exc.code == "AIWF-RECOVERY-REQUIRED"
    if exc.code in ("timeout", "AIWF-LOCK-BUSY"):
        status = "timeout"
    elif exc.code in ("unsupported", "unavailable", "AIWF-LOCK-UNSUPPORTED"):
        status = "unsupported"
    elif exc.code == "AIWF-RECOVERY-REQUIRED":
        status = "blocked"
    else:
        status = "failed" if started or exc.code == "launch_failed" else "rejected"
    message = str(exc)
    if needs_reconciliation:
        message += " Do not replay. Reconcile the task, index, events and closure evidence first."
    return {"contract_version": 1, "operation": operation, "operation_status": status,
            "mutation_state": "unknown" if started else "not_applied", "runtime_exit_code": runtime_code,
            "target": target, "diagnostics": [{"code": exc.code, "severity": "error", "message": message}],
            "requires_reconciliation": needs_reconciliation, "result": None}


def _raise_walk_error(exc):
    raise exc


def observation(paths):
    """Selected metadata can detect change, never establish a transaction."""
    observed = []
    for path in paths:
        try:
            info = path.lstat()
            observed.append((info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size))
        except FileNotFoundError:
            observed.append(None)
    return observed
