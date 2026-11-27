"""Explicit daily workflow operations. Tool input cannot select an executable or add CLI flags."""

from .runtime import QueryError


def parameters(properties, required=(), **constraints):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False, **constraints}


def text_field(length=512):
    return {"type": "string", "minLength": 1, "maxLength": length, "pattern": r"\S", "not": {"pattern": "\u0000"}}


def metadata_text(length=512):
    return {**text_field(length), "not": {"pattern": r"[\x00-\x1f\x7f-\x9f\u2028\u2029]"}}


TASK_PATH = text_field()
BINDING = {"type": "string", "minLength": 1, "maxLength": 128}
DATE = {"type": "string", "pattern": "^[0-9]{8}$", "maxLength": 8}
PHASE = ["init", "implementation", "validation", "review"]
LIST_FILTERS = {
    "date": DATE, "status": {"enum": ["draft", "active", "review", "blocked", "done", "archived"]},
    "review_status": {"enum": ["pending", "pass", "fail", "not_required"]},
    "workflow_phase": {"enum": [*PHASE, "finalized"]},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
}


def task_parameters(properties=None, required=()):
    return parameters({"binding_id": BINDING, "task_path": TASK_PATH, **(properties or {})},
                      ["binding_id", "task_path", *required])


REPEATED_OPTIONS = {"related_tasks": "related-task", "blocked_by": "blocked-by", "supersedes": "supersedes",
                    "tags": "tag", "related_files": "related-file"}
NEW_TASK = parameters({
    "binding_id": BINDING, "name": metadata_text(128), "title": metadata_text(), "date": DATE,
    "priority": {"enum": ["P0", "P1", "P2", "P3"]}, "risk": {"enum": ["low", "medium", "high", "critical"]},
    "project": metadata_text(128), "parent_task": metadata_text(128),
    **{k: {"type": "array", "maxItems": 40, "items": metadata_text()} for k in REPEATED_OPTIONS},
}, ["binding_id", "name"])
RECORD_KINDS = {
    "validation": ({"result": {"enum": ["pass", "fail", "not_run"]}, "command": text_field(4096)}, ["result"]),
    "review": ({"result": {"enum": ["pass", "fail", "not_required"]}, "summary": text_field(4096)}, ["result"]),
    "fix": ({"summary": text_field(4096)}, ["summary"]),
    "safety_ack": ({"summary": text_field(4096)}, ["summary"]),
}
RECORD = task_parameters({"kind": {"enum": list(RECORD_KINDS)}, "result": text_field(32),
                          "summary": text_field(4096), "command": text_field(4096)}, ["kind"])
RECORD["oneOf"] = [task_parameters({"kind": {"const": kind}, **props}, ["kind", *required])
                   for kind, (props, required) in RECORD_KINDS.items()]
RECORD["allOf"] = [{"if": {"required": ["result"], "properties": {"result": {"const": "not_required"}}},
                    "then": {"required": ["summary"], "properties": {"summary": metadata_text(4096)}}}]
WRITE_TOOLS = {
    "aiwf_new_task": ("new-task", "Create one task. Read its allocated canonical path from the result. "
                      "Do not replay an uncertain create.", NEW_TASK),
    "aiwf_guard": ("guard", "Run the Runtime pre-edit guard for one open task; it may record an event.", task_parameters()),
    "aiwf_transition": ("transition", "Request a Runtime phase transition for one task.",
                        task_parameters({"to": {"enum": PHASE}}, ["to"])),
    "aiwf_sync_index": ("sync-index", "Synchronize the task's status in the daily index using the Runtime.",
                        task_parameters()),
    "aiwf_record": ("record", "Record validation, agent review, a fix, or an existing safety acknowledgement. "
                    "Command text is evidence only. Human decisions require the operator channel.", RECORD),
    "aiwf_finalize": ("finalize", "Request actual workflow closure. The Runtime checks fresh evidence and review "
                      "authority under its writer lock. Reconcile an uncertain result before another attempt.",
                      task_parameters()),
}
MUTATION_OUTPUT = {
    "type": "object",
    "required": ["contract_version", "operation", "operation_status", "mutation_state", "runtime_exit_code",
                 "target", "diagnostics", "requires_reconciliation", "result"],
    "properties": {
        "contract_version": {"const": 1}, "operation": {"type": "string"},
        "operation_status": {"enum": ["succeeded", "blocked", "rejected", "failed", "timeout", "unsupported"]},
        "mutation_state": {"enum": ["not_applied", "applied", "already_applied", "partially_applied", "unknown"]},
        "runtime_exit_code": {"type": ["integer", "null"]}, "target": {"type": ["string", "null"]},
        "diagnostics": {"type": "array"}, "requires_reconciliation": {"type": "boolean"},
        "result": {"type": ["object", "null"]},
    },
}


def enabled_writes(repo, context):
    if (repo.mode != "read-write" or context.get("mutation_contract_version") != 1
            or context.get("mutation_root_writable") is not True):
        return []
    try:
        repo.contract_script(write=True)
        repo.validator(write=True)
    except QueryError:
        return []
    return [name for name, (op, _, _) in WRITE_TOOLS.items() if op in context.get("mutation_operations", [])]


async def apply(repo, name, arguments, context):
    if arguments["binding_id"] != repo.binding_id:
        raise QueryError("binding_mismatch", "The requested binding differs from this server's bound worktree.")
    if context.get("mutation_root_writable") is False:
        raise QueryError("AIWF-LOCK-UNSUPPORTED", "The Runtime process cannot manage its recovery marker "
                         "at the worktree root. Use read-only mode for this account.")
    if name not in enabled_writes(repo, context):
        raise QueryError("unsupported", "The installed Runtime does not support this write operation.")
    op = WRITE_TOOLS[name][0]
    target = arguments.get("task_path")
    if target:
        repo.task(target, context["records_root"])
    return await repo.mutate(op, mutation_argv(repo, op, arguments), target, context["records_root"])


def mutation_argv(repo, op, arguments):
    if op == "new-task":
        args = []
        for key in ("title", "priority", "risk", "project", "parent_task", "date"):
            if key in arguments:
                args.append(f"--{key.replace('_', '-')}={arguments[key]}")
        for key, flag in REPEATED_OPTIONS.items():
            for value in arguments.get(key, []):
                if key == "related_files":
                    repo.path(value)
                args.append(f"--{flag}={value}")
        return [*args, "--", arguments["name"]]
    args = ["--path", arguments["task_path"]]
    if op == "transition":
        return [*args, "--to", arguments["to"]]
    if op == "record":
        args.extend(["--agent-channel", "--kind", arguments["kind"]])
        for key in ("result", "command", "summary"):
            if key in arguments:
                args.append(f"--{key}={arguments[key]}")
        if arguments["kind"] == "review":
            authority = "not_required" if arguments["result"] == "not_required" else "ai-agent"
            args.extend(["--decision-authority", authority, "--recorded-by", repo.recorder, "--reviewer", "ai-agent"])
        return args
    if op == "guard":
        return [*args, "--pre-edit"]
    if op in ("sync-index", "finalize"):
        return args
    raise QueryError("unsupported", "No mapping exists for this mutation.")
