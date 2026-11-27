# Optional AIWF MCP adapter

The server exposes AIWF queries over local stdio. Operators can enable daily workflow mutations for one bound worktree. Core supplies the governance rules, result contracts and shared writer lock.

## Install and bind a worktree

Use a separate Python 3.10+ virtual environment outside the target worktree. The adapter pins the official MCP Python SDK to `2.3.0`. The `guidance` extra installs PyYAML for the bound helper. Ordinary AIWF Core setup and upgrade have no MCP dependency.

Adapter 0.3.2 targets MCP revision `2026-07-28` and also serves hosts that negotiate `2025-11-25`. Both use the same command, binding, tool handlers and Core authorization rules. Modern discovery reports the available modern revision. A legacy client negotiates its version through `initialize`. The tested Core baseline is AIWF Tool 1.7.17.post3, AIWF Workflow Protocol 1.7.10, Query Contract v1 and Mutation Contract v1. Stock Tool 1.7.16 predates the query contract. An installation with only the earlier read contract continues to serve its supported queries.

On the tested Core baseline, both read-only and read-write modes require local storage with a supported POSIX file lock. Native Windows lacks that backend. On unsupported storage, `aiwf_context` reports the lock error and daily workflow tools are unavailable. Check the bound Runtime with `aiwf_context` before relying on its tools. The Core CLI reference lists supported filesystems and traditional CLI observations available on other storage. [Core CLI storage requirements](../../.aiwf/docs/cli_reference.md)

```sh
python3 -m venv /absolute/path/to/adapter-venv
/absolute/path/to/adapter-venv/bin/python -m pip install '/absolute/path/to/AIWF/integrations/mcp[guidance]'
/absolute/path/to/adapter-venv/bin/aiwf-mcp --repo-root /absolute/path/to/trusted-project --binding-id project-a
```

The last command waits for an MCP client on stdin. Examples for Codex CLI, Copilot CLI and VS Code are installed under the adapter environment's `share/aiwf-mcp/examples/`. Choose a distinct binding ID per worktree and give the agent the expected ID. The default ID is the first 16 hexadecimal digits of the SHA-256 digest of the filesystem-encoded canonical absolute path. [Codex](examples/codex.toml) · [Copilot CLI](examples/copilot.mcp.json) · [VS Code](examples/vscode.mcp.json)

Bind only an installation whose runtime, imports and schema you trust. The child process runs the bound `.aiwf/bin/ai_workflow.py` or `.aiwf/bin/guidance.py` with the adapter's Python interpreter, explicit `--repo-root`, and bytecode generation disabled. If the CLI uses `TZ` to select a workflow day, give the server process the same `TZ` at startup. Local execution has the operator's filesystem privileges. Use host/OS isolation if the worktree can contain hostile programs. The host can forward returned text to its model provider.

## Tool inputs

| Tool | Arguments | Result |
| --- | --- | --- |
| `aiwf_context` | `{}` | Fixed binding ID, Runtime Tool and Protocol versions, configured records root and capabilities. Compare the returned ID before using evidence. |
| `aiwf_inspect_task` | `{"task_path":"<canonical path>"}` | Historical workflow state, preservation of closure evidence and latest effective correction. |
| `aiwf_check_task` | `{"task_path":"<canonical path>","mode":"finalize_readiness"}` | Runtime decision and diagnostics. Use `standard` for an ordinary check, or `finalize_preview` for the Runtime's dry-run projection. |
| `aiwf_list_tasks` | Optional `date`, `status`, `review_status`, `workflow_phase`, `limit` | Canonical task paths. Check the truncation flag for bounded result sets. |
| `aiwf_diagnostics` | `{"task_path":"<canonical path>"}` | Diagnostics and derived workflow evidence for the selected task. |
| `aiwf_guidance_lookup` | `{"scopes":["validation","regression"]}` or `{"note_id":"GUIDE-EXAMPLE"}` | Per-selector results and de-duplicated eligible candidate IDs. Use the explicit ID for the selected note's full checks and applicability restrictions. |

Use the canonical task path returned by `aiwf_list_tasks`. For example, with legacy discovery enabled, read tools can inspect `docs/ai_20260101/001_example`. Writes use the configured records root, such as `.aiwf/records/ai_20260101/001_example`. Absolute paths, dot components, links in required paths and extra input fields are rejected. Each guidance request accepts one ID or 1–8 distinct exact scopes.

## Interpreting the result

Queries return an MCP `structuredContent` object and an equivalent JSON text block. Each query object contains `contract_version`, `operation`, `execution`, `exit_code`, `result`, `error`, `repository` and `consistency`. The adapter checks runtime output against the installed `.aiwf/docs/schemas/query_result_v1.schema.json` and checks operation, selector/task identity and child exit status. `exit_code: null` identifies an adapter failure or an aggregate with individual process statuses. Context also returns `interface`, including the server mode and the currently enabled write tool names.

- A successful readiness query may return `execution: "ok"`, `exit_code: 2`, `workflow_result: "BLOCKED"` and `isError: false`. This reports the Runtime's governance decision.
- A guidance lookup returns each selector in `result.queries`. Status 0 may have zero matches. Status 1 preserves current candidates and withheld notes requiring review. Status 2 discards all candidates from that invocation. If any lookup fails, MCP returns `isError: true` and retains the outcomes of other requested scopes. Inspect `source_state`, `eligible`, version and applicability before acting. The note body returned for an explicit ID is project-authored data.
- `unavailable` indicates a missing component or dependency. `unsupported` identifies a component without the supported query contract. Invalid JSON, exit mismatch, timeout, failed process launch, unsafe path and excess output are errors without a workflow verdict. Raw child stderr remains private.
- `consistency: "unconfirmed"` describes ordinary reads of a live worktree. Changes observed across selected task/index/event metadata or contradictory observations of a note can produce `possible_concurrent_change` with no usable verdict. Source edits that do not change the observed metadata can go undetected. Use an externally immutable snapshot when conclusions require one.

The default per-process timeout is ten seconds (`--timeout-seconds` accepts 0.1–60). The adapter runs up to four calls concurrently and admits up to 60 recognized tool invocations per rolling minute per server process, including calls with invalid tool inputs. A rate-limited write returns `rate_limited` before Core starts it. Modern discovery and tool listings return `ttlMs: 0` and `cacheScope: "private"` because permissions and available operations can change. Each child's stdout and stderr and the final serialized tool payload are each limited to 128 KiB. Output over the limit fails as a whole. Scope queries return note metadata and source status. The current helper omits note bodies before writing a scope response. With an older query-v1 helper, full scope output must fit the child limit. A lookup by ID returns the selected note's body.

## Enable daily workflow writes

Append `--mode read-write` to the server's startup arguments in your chosen Host configuration. The default is `read-only`. Set `--recorder` at startup if your deployment needs a specific evidence recorder. Before a mutation compare the expected worktree with `aiwf_context.repository.binding_id` and pass that ID as `binding_id`. The server rejects mismatches. Each of these operations accepts the exact inputs in its discovery schema.

Core creates and removes `.aiwf-mutation-pending` directly in the worktree root while holding its directory lock. The Runtime process therefore needs write and search permission on that directory, even when the records and events live in writable subdirectories. `./aiwf query context --full-workflow` reports the current process's effective permission in `result.mutation_root_writable` without creating a file. The adapter enables writes only when Core reports `true`. If the field is missing, update the bound Runtime and its query schema to enable writes. Core checks permissions again at mutation time. Individual operations still depend on their target files, storage and workflow gates.

| Tool | Inputs beyond binding ID | Effect |
| --- | --- | --- |
| `aiwf_new_task` | `name` and optional native task metadata such as `title`, `priority`, `risk`, `project`, `tags`, `related_files` and task relations | Creates the task with a Runtime-allocated ID and returns the canonical target. |
| `aiwf_guard` | `task_path` | Runs the pre-edit guard, including any configured event logging. |
| `aiwf_transition` | `task_path`, `to` | Requests a legal transition. Final closure uses `aiwf_finalize`. |
| `aiwf_sync_index` | `task_path` | Synchronizes the status projection for the task through Core. |
| `aiwf_record` | `task_path`, `kind`, kind-specific fields | Validation takes `result` and optional evidence-only `command`. Review takes `result` and optional `summary`; `not_required` needs a reason and an eligible policy. Fix and safety acknowledgement require `summary`. The reviewer and decision authority are supplied by the channel. |
| `aiwf_finalize` | `task_path` | Evaluates the current gate under the shared Runtime writer lock and applies workflow closure when allowed. |

Mutation results expose `operation_status`, `mutation_state`, `runtime_exit_code`, `target`, `diagnostics`, `requires_reconciliation` and `result`. A blocked mutation returns `isError: true`. Check its receipt because Core can record an audit event even when it denies the requested change. The Runtime serializes supported writers on its supported local storage. Older runtimes and ordinary editors operate outside that lock. Stop writers before running installation or maintenance operations.

After a timeout, cancellation, lost response, partial write or unknown result, stop issuing mutations. Confirm that the original writer has stopped, then inspect the bound worktree, task, daily index, event projections and finalize manifest. When evidence disagrees, preserve it for the maintainer. An ordinary gate blocker, human-review requirement or permission denial remains binding across both interfaces. Keep actual engineering outputs and review documents with the project-owned engineering tools.

## Operator review and additive correction

The separate POSIX `aiwf-mcp-operator` console application serves one approved operation to its own in-process MCP client. The agent-facing stdio server has no operator transport. The operator application prints the canonical root, task, authority, recorder and exact arguments to its controlling terminal and asks the operator to confirm a random challenge for that one action.

A qualified deployment requires distinct OS accounts for the human operator and the Agent. The operator must exclusively control the terminal, adapter environment, installed Runtime, schema, worktree root and the following policy. Restrict the Agent to the intended project engineering files and cooperating evidence writers. The policy check covers POSIX ownership and mode bits. The deployment owner must also check ACLs, privilege delegation and file-sharing rules. Agent access to the operator's identity, credentials, terminal, writable runtime or raw human-authorized CLI falls outside this trust boundary.

On that protected worktree an Agent launching stdio directly under its own account gets the read tools. Keep the worktree root operator-controlled. To offer daily mutations on the same worktree, the deployment must supply a trusted writer process with root-directory write permission. The operator starts the ordinary `aiwf-mcp --mode read-write` server with a fixed root, binding, recorder, interpreter and trusted environment. The Agent's only access to that process is its stdio tool connection. The deployment must isolate its credentials, shell and process control from the Agent, and the operator runs `aiwf-mcp-operator` separately in their own terminal. Where this process isolation is unavailable, use read-only Agent access on the protected worktree. For a trusted single-account checkout, ordinary read-write stdio supports daily operations directly. Qualified human approval requires the separate-account deployment above.

Under the operator's real account home, provision `.config/aiwf/mcp-operator.json` as an operator-owned mode-0600 file. Its parent directories and the installed code must be protected against other writers. Each permitted canonical root has exactly one grant; replace the sample Agent UID and paths with your deployment's values.

```json
[{"root":"/absolute/path/to/trusted-project","binding_id":"project-a","agent_uid":501,"recorder":"release-reviewer","correction_authority":"human_maintainer"}]
```

```sh
aiwf-mcp-operator review --help
aiwf-mcp-operator correction --help
```

The action help includes the accepted values. In the authorized worktree, set `TASK` to the actual path returned by `aiwf_list_tasks` or `./aiwf list`. After examining the change and its validation evidence, the reviewer supplies `DECISION` (`pass` or `fail`) and `SUMMARY`. For a correction, the operator supplies the correction type, current statement and reason. Run the command for the action you intend to confirm.

```sh
aiwf-mcp-operator --repo-root "$PWD" review --task-path "$TASK" --result "$DECISION" --summary "$SUMMARY"
aiwf-mcp-operator --repo-root "$PWD" correction --task-path "$TASK" --type "$TYPE" --current-state "$CURRENT_STATE" --reason "$REASON"
```

The operator application exits before the mutation when its deployment policy or terminal confirmation is unavailable. User acceptance of actual human operation requires a qualified deployment. Automated fixture checks exercise the channel mechanics only.

## Test the adapter

From the AIWF source root, use a Python environment containing the package dependencies, PyYAML and pytest. The suite opens real stdio sessions against temporary synthetic worktrees.

```sh
python -m pytest -q integrations/mcp/tests
```

To test a built wheel, install it in that environment and run
`AIWF_MCP_TEST_INSTALLED=1 python -m pytest -q integrations/mcp/tests/test_wire.py`.
The stdio server then starts in isolated Python mode using the installed package.

Modern clients can call `server/discover` or send a tool request directly. They include the protocol revision and client capabilities in each request. Handshake-era hosts begin with `initialize`, followed by `notifications/initialized`. For a Python SDK v2 client, the default `auto` mode probes the peer. Use pinned `2026-07-28` to require the modern protocol or `legacy` to test the handshake. Version selection takes place before issuing workflow mutations. Reconcile a missing mutation receipt through the bound worktree before any retry. [Modern stdio and fallback](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio) · [Modern tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) · [Legacy lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) · [Python SDK protocol modes](https://py.sdk.modelcontextprotocol.io/protocol-versions/)
