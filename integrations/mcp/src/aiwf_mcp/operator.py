"""One confirmed operator action over a private, in-process MCP connection."""

import argparse
import asyncio
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from mcp import Client, MCPError, types
from mcp.server.lowlevel import Server

from .mutations import MUTATION_OUTPUT, parameters, text_field
from .runtime import IDENTIFIER, OUTPUT_BYTES, BoundRepository, QueryError, mutation_error, parse_json


CORRECTIONS = ["implementation_reverted", "scope_reclassified", "conclusion_corrected",
               "evidence_superseded", "current_state_clarification"]
OPERATIONS = {
    "review": ("aiwf_record", "record", parameters(
        {"task_path": text_field(), "result": {"enum": ["pass", "fail"]}, "summary": text_field(4096)},
        ["task_path", "result", "summary"])),
    "correction": ("aiwf_correct_finalized", "correct-finalized", parameters(
        {"task_path": text_field(), "type": {"enum": CORRECTIONS}, "current_state": text_field(1024),
         "reason": text_field(4096)}, ["task_path", "type", "current_state", "reason"])),
}


class OperatorRefusal(ValueError):
    """Fixed, display-safe explanation for the operator."""


def protected(path, uid):
    """The operator or OS must control the files and directories supplying the runtime and policy."""
    info = path.lstat()
    if (info.st_uid not in (0, uid) or info.st_mode & 0o022 or
            not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
        raise OperatorRefusal("Operator policy, repository root and installed runtime must be protected from other writers.")


def operator_grant(root):
    if os.name != "posix":
        raise OperatorRefusal("The operator channel requires a verified POSIX deployment.")
    import pwd

    uid = os.geteuid()
    home = Path(pwd.getpwuid(uid).pw_dir).resolve(strict=True)
    config = home / ".config" / "aiwf" / "mcp-operator.json"
    for path in [*config.parents, config]:
        protected(path, uid)
    info = config.lstat()
    if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 65536:
        raise OperatorRefusal("The operator policy must be an operator-owned, mode-0600 file.")
    entries = parse_json(config.read_bytes())
    if not isinstance(entries, list):
        raise OperatorRefusal("Expected a list of operator grants.")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("root") == str(root)]
    if len(matches) != 1:
        raise OperatorRefusal("No unique operator grant for this canonical worktree.")
    grant = matches[0]
    if (set(grant) != {"root", "binding_id", "agent_uid", "recorder", "correction_authority"} or
            type(grant["agent_uid"]) is not int or grant["agent_uid"] < 0 or grant["agent_uid"] == uid or
            not all(isinstance(grant[k], str) and IDENTIFIER.fullmatch(grant[k])
                    for k in ("binding_id", "recorder", "correction_authority")) or
            not re.fullmatch(r"human_[a-z0-9_]+", grant["correction_authority"])):
        raise OperatorRefusal("The grant must identify a separate Agent UID, a recorder and a human correction authority.")
    if root.stat().st_uid != uid:
        raise OperatorRefusal("The bound worktree must belong to the operator.")
    for parent in [root, *root.parents]:
        protected(parent, uid)
    managed = root / ".aiwf"
    protected(managed, uid)
    protected(managed / "config.yaml", uid)
    for path in (root / ".env", managed / "metadata.local.env", managed / "metadata.current"):
        if os.path.lexists(path):
            protected(path, uid)
    for folder in [managed / "bin", managed / "docs" / "schemas"]:
        protected(folder.parent, uid)
        protected(folder, uid)
        for child in folder.rglob("*"):
            protected(child, uid)
    return grant


def confirm(reader, writer, repo, grant, operation, arguments):
    if not reader.isatty() or not writer.isatty():
        raise OperatorRefusal("A human-controlled local terminal is required.")
    nonce = secrets.token_hex(3)
    writer.write(json.dumps({"bound_root": str(repo.root), "binding_id": repo.binding_id,
                          "operation": operation, "recorder": grant["recorder"],
                          "decision_authority": "human" if operation == "record" else grant["correction_authority"],
                          "arguments": arguments}, ensure_ascii=True, indent=2))
    writer.write(f"\nReview this exact action, then type CONFIRM {nonce} to submit it once: ")
    writer.flush()
    if reader.readline().rstrip("\r\n") != f"CONFIRM {nonce}":
        raise OperatorRefusal("Operator declined the action.")


async def approved_call(repo, grant, action, arguments):
    """Only the operator application holds this one-call channel. It has no listener."""
    name, op, schema = OPERATIONS[action]
    approved = dict(arguments)
    used = False

    async def list_tools(_ctx, _params):
        return types.ListToolsResult(tools=[types.Tool(
            name=name, description="Submit the locally confirmed operator action once.",
            input_schema=schema, output_schema=MUTATION_OUTPUT,
        )])

    async def dispatch(_ctx, params):
        nonlocal used
        if used or params.name != name or params.arguments != approved:
            raise MCPError(types.INVALID_PARAMS, "Outside the confirmed operator action.")
        used = True
        target = approved["task_path"]
        argv = ["--path", target]
        if action == "review":
            argv.extend(["--kind", "review", "--reviewer", "human", "--decision-authority", "human",
                         "--recorded-by", grant["recorder"], "--result", approved["result"],
                         "--summary=" + approved["summary"]])
        else:
            argv.extend(["--type", approved["type"], "--authority", grant["correction_authority"],
                         "--current-state=" + approved["current_state"], "--reason=" + approved["reason"]])
        try:
            repo.check_binding()
            context = await repo.query("context", [], repo.validator())
            if context["execution"] != "ok":
                raise QueryError(context["error"]["code"], "The bound Runtime rejected the pre-write context check.")
            native = context["result"]
            if native.get("mutation_contract_version") != 1 or op not in native.get("mutation_operations", []):
                raise QueryError("unsupported", "The installed runtime does not support this operator action.")
            repo.task(target, native["records_root"])
            reply = await repo.mutate(op, argv, target, native["records_root"])
        except QueryError as exc:
            # mutate returns an uncertainty envelope for failures after launch.
            reply = mutation_error(op, exc, target)
        encoded = json.dumps(reply, ensure_ascii=True)
        if len(encoded.encode()) > OUTPUT_BYTES:
            reply = mutation_error(op, QueryError("output_limit", "Operator response exceeded its limit."),
                                   target, started=True, runtime_code=reply["runtime_exit_code"])
            encoded = json.dumps(reply)
        return types.CallToolResult(
            structured_content=reply, content=[types.TextContent(type="text", text=encoded)],
            is_error=reply["operation_status"] != "succeeded" or reply["requires_reconciliation"],
        )

    server = Server("aiwf-operator", on_list_tools=list_tools, on_call_tool=dispatch)
    async with Client(server) as client:
        return (await client.call_tool(name, approved)).structured_content


def operator_parser(argv):
    # Locate the action even when an existing caller puts options before it.
    # Consume option values so a title such as "review" cannot select the action.
    locate = argparse.ArgumentParser(prog="aiwf-mcp-operator", add_help=False)
    fields = {"repo_root"}
    for _, _, schema in OPERATIONS.values():
        fields.update(schema["properties"])
    for field in sorted(fields):
        locate.add_argument("--" + field.replace("_", "-"))
    locate.add_argument("action", nargs="?")
    selection, _ = locate.parse_known_args(argv)
    action = selection.action
    descriptions = {
        "review": "Record the human reviewer's decision after reviewing this task and its validation evidence.",
        "correction": "Append a human-authorized correction to a finalized task.",
    }
    examples = {
        "review": '--result "$DECISION" --summary "$SUMMARY"',
        "correction": '--type "$CORRECTION_TYPE" --current-state "$CURRENT_STATE" --reason "$REASON"',
    }
    epilog = "Choose review --help or correction --help for the required fields and an example."
    if action in OPERATIONS:
        epilog = f'Example: aiwf-mcp-operator --repo-root "$PWD" {action} --task-path "$TASK" {examples[action]}'
    parser = argparse.ArgumentParser(
        prog="aiwf-mcp-operator", description=descriptions.get(action, "Confirm one human action from the operator account."),
        epilog=epilog,
    )
    parser.add_argument("--repo-root", type=Path, required=True, help="absolute path to the authorized worktree")
    parser.add_argument("action", choices=[action] if action in OPERATIONS else tuple(OPERATIONS))
    if action in OPERATIONS:
        parser.add_argument("--task-path", required=True, help="full dated task path relative to the worktree")
    if action == "review":
        parser.add_argument("--result", required=True, choices=OPERATIONS[action][2]["properties"]["result"]["enum"])
        parser.add_argument("--summary", required=True, help="what the reviewer decided and why")
    elif action == "correction":
        parser.add_argument("--type", required=True, choices=CORRECTIONS)
        parser.add_argument("--current-state", required=True, help="the corrected statement")
        parser.add_argument("--reason", required=True, help="why the statement needs correction")
    return parser


def main():
    parser = operator_parser(sys.argv[1:])
    args = parser.parse_args()
    arguments = {key: value for key, value in vars(args).items() if key not in ("action", "repo_root")
                 and value is not None}
    try:
        if not args.repo_root.is_absolute():
            raise OperatorRefusal("Specify an absolute worktree root.")
        root = args.repo_root.resolve(strict=True)
        grant = operator_grant(root)
        repo = BoundRepository(root, grant["binding_id"], 30, "read-write", grant["recorder"])
        _, op, schema = OPERATIONS[args.action]
        if not Draft202012Validator(schema).is_valid(arguments):
            raise OperatorRefusal("Operator inputs do not match the schema for the selected action.")
        with (open("/dev/tty", "r", encoding="utf-8") as reader,
              open("/dev/tty", "w", encoding="utf-8", buffering=1) as writer):
            confirm(reader, writer, repo, grant, op, arguments)
        reply = asyncio.run(approved_call(repo, grant, args.action, arguments))
    except OperatorRefusal as exc:
        parser.exit(2, f"Operator action rejected: {exc}\n")
    except FileNotFoundError:
        parser.exit(2, "Operator action rejected: a required policy, protected path or terminal is unavailable.\n")
    except Exception as exc:
        parser.exit(2, f"Operator action failed. Check policy, terminal and task state before retrying. {type(exc).__name__}\n")
    print(json.dumps(reply, indent=2, ensure_ascii=True))
    if not reply or reply["operation_status"] != "succeeded":
        sys.exit(2)
