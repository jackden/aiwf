# AIWF CLI Reference

The repository-local entrypoint is `./aiwf`. Run `./aiwf --help` for the
complete command list for the installed release.

## First install

```bash
/path/to/aiwf-package/aiwf install --target .
/path/to/aiwf-package/aiwf install --target . --yes
```

The first command performs a read-only preflight. The second applies it.
Fresh install is source-driven and rejects both complete and partial AIWF
layouts; it does not perform upgrade or repair work.

To connect an MCP client to this installation, follow the guide for building or
installing the adapter, registering it, and checking the bound worktree.
[MCP setup walkthrough (繁體中文)](examples/mcp_setup.md)

## Daily workflow

Use the installed CLI from the project root. In the table, `TASK` is the
complete dated directory printed by `new-task`.

| Goal | Command or action |
| --- | --- |
| Start or resume | Run `./aiwf new-task <task-name>` once. To resume, find the existing path with `./aiwf list`. |
| Prepare to edit | Run `./aiwf guard --pre-edit --path "$TASK"`. Edit the task body and project files once it passes. |
| Validate | Run the actual project test. Save its output in `self_validation.md` and use `./aiwf record --path "$TASK" --kind validation` with the observed result and command. |
| Review | Document the scope and findings. A human-required task needs the assigned reviewer's actual decision. |
| Inspect structure | Run `./aiwf check --path "$TASK"`. |
| Close | Run `./aiwf check --path "$TASK" --finalize-ready`. When it passes, run `./aiwf finalize --path "$TASK"`. |

The [worked example](examples/basic_lifecycle.md) includes a real test, its
validation event and the distinct operator step for recording human review.

Use `doctor` for diagnostics and `inspect` to distinguish historical closure
from an additive post-finalization correction. To preview closure in JSON, use
`./aiwf query check --preview --path <task-path>`. For a text preview use
`./aiwf finalize --dry-run --path <task-path>`.

Use the optional [Guidance helper](guidance.md) to check or display
project-owned notes linked to workflow evidence.

## Read-only JSON queries

Run these commands from the installed repository. Use the complete task path
under its configured records root.

```bash
./aiwf query context
./aiwf query inspect --path <task-path>
./aiwf query check --path <task-path>
./aiwf query check --path <task-path> --finalize-ready
./aiwf query diagnostics --path <task-path>
python .aiwf/bin/guidance.py show --format json --scope validation
```

`query` uses the same task inspection, policy checks and doctor diagnostics
as the text commands. These observation paths bypass the event writer even
when project logging is enabled. The context result reports the executing
runtime version and checks that it belongs to the selected root. Its Guidance
capability requires the structured helper and a discoverable PyYAML package
in the current interpreter. The helper reports a dependency error if the
import fails.

For a finalized task, `inspect` compares the required files with the saved finalize manifest. A difference gives `closure_preserved: false`; an unusable or missing manifest gives `AIWF-INSPECT-002`. An active task also has `closure_preserved: false`. Use `workflow_phase` to distinguish these cases.

Check the process exit code against `exit_code` and read `execution` before
using `result`. A blocked readiness check returns status 2 with `execution`
set to `ok` and `workflow_result` set to `BLOCKED`. A path or operation error
returns status 2 with `execution` set to `error`, `result` set to `null`, and
a diagnostic in `error`. For an identifiable query operation, argument syntax
errors also return this JSON envelope on stdout. The detailed argument error
appears on stderr and the JSON message names the operation's help command.
An absent or unknown operation produces CLI usage on stderr. Treat missing or
invalid JSON as an execution failure. Diagnostics include the Runtime's severity and blocker fields.
The derived evidence summary includes the age at query time. Each query
holds a shared lock against cooperating Runtime writers for that single call.
A global event can identify its task with a canonical relative path or an
absolute path in the same repository. The structured diagnostic query ignores
foreign absolute paths without resolving them. An in-repository event pointer
containing parent traversal or a symlink makes the observation fail.

The [version 1 result schema](schemas/query_result_v1.schema.json) defines
the envelope and per-operation fields.

## Concurrent workflow operations and recovery

The CLI, the Guidance helper and the local adapter coordinate on the inode
of the bound repository directory. The Runtime takes a shared or exclusive
POSIX advisory lock before reading workflow state. Mutations, including
legacy checks that can append an event, take the exclusive lock through
the final state check. A five-second wait that expires before dispatch
returns `AIWF-LOCK-BUSY`. The kernel releases the lock when a process
exits. Readers create no lock file. The same process can reuse its existing
lease for the same root, without upgrading a shared lease to exclusive.

Use private, local, single-owner storage. The Darwin implementation checks
for APFS or HFS. Linux checks mount information for a local ext2/3/4, XFS,
Btrfs, tmpfs or overlay mount with its own filesystem root. The mounted
backing store must be local to a single machine. Conflicting repo ownership,
cross-mounted storage, symlinked or multiply linked write targets, and
unrecognized storage prevent governed writes, structured queries, readiness
checks and finalize previews. An explicit legacy `--repo-root` inside an
existing AIWF project needs its own installation or layout configuration
and disjoint storage. Native Windows has no qualified lock backend.
Where the platform or filesystem lacks a qualified backend, the legacy
`list`, `inspect`, `next-id`, `report`, `export-json`, `export-experiment`,
`guard --pre-edit` and text Guidance commands can produce an unconfirmed
observation with a warning on stderr. The guard can inspect edit policy,
but its result cannot grant a storage lease for subsequent writes. A busy
lock, a pending recovery marker or conflicting storage ownership still
blocks the operation. Stop all writers for setup, upgrade, relocation, profile changes,
package/dataset administration and other maintenance. Older runtimes, direct
Python calls to internal functions and external file editors do not
participate. An individual read cannot guarantee a multi-call snapshot.

Before its first governed write, the Runtime creates the owner-only
`.aiwf-mutation-pending` marker in the repository root. It records the
operation and the canonical task path when known. Completion clears it.
A killed process or partial failure may leave the marker after the OS has
released the lock. `AIWF-RECOVERY-REQUIRED` blocks participating commands
until the repository maintainer reconciles the operation.

1. Stop participating writers, verify that the original process has exited
   and preserve the marker and the observed repository state.
2. Compare the actual task directory, metadata, day index, both event logs,
   and recorded finalize manifest against the operation. A missing response
   may follow a successful write. A missing marker alone proves no outcome.
3. Keep the repository quiescent when the evidence disagrees. Use the
   project's authorized recovery process. Preserve finalized evidence and
   record any necessary correction through its governed path.
4. Once the maintainer has resolved the uncertainty, archive the marker
   outside the working tree and resume with inspection and diagnostics. An
   agent must not clear the marker automatically or replay the original write.

## Review authority evidence (v1.7.14)

New tasks use schema `ai-workflow-v1.7` and default to
`required_review_authority: human`. An agent records its own review with
`--decision-authority ai-agent`. A human-required task stays open after that
review. Send the work and validation evidence to the assigned human reviewer.
Once they respond, the authorized operator records the actual decision.
[Human operator CLI example](examples/basic_lifecycle.md#record-the-human-decision-and-close)

Use `--decision-authority not_required` only with
`--result not_required`; the existing non-empty `--summary` reason remains
required. `recorded_by` may differ from `decision_authority`. These fields are
workflow evidence assertions, not authenticated human identity or
cryptographic approval.

`check --finalize-ready` and `finalize` validate the latest final review's
required-authority snapshot, decision authority, and recording actor. Older
finalized records remain readable without migration; active older tasks that
explicitly require human review cannot bypass the authority check.

## Derived evidence diagnostics

`doctor --path <task-path>` prints a `Workflow Evidence Summary`. JSON/Markdown
`report` output includes each task's `derived_evidence`, derived status, and
derived warning codes. The view reports correction-loop counts, validation
outcomes, review freshness, authority consistency, local/global event
projection discrepancies, schema compatibility, and last activity age.

Derived warnings are observational only. They do not add finalize blockers,
workflow phases, validation dispositions, reliability scores, or a second
workflow state source. `check --finalize-ready` and `finalize` do not consume
Task 002 derived warnings as gates.

## Existing installations

Use the [Upgrade Guide](upgrading.md) and its explicit source package for an
existing repository. Install never silently becomes upgrade.

## Configured Metadata and Actor Identity

```bash
./aiwf metadata show
./aiwf metadata status
./aiwf metadata profile create <name>
./aiwf metadata profile use <name>
./aiwf profile migrate --dry-run
./aiwf profile migrate
./aiwf metadata profile migrate <name> --dry-run
./aiwf dataset export --output artifacts/workflow_dataset.json
```

New profiles contain logging configuration only. Legacy metadata remains
configured context and does not establish execution identity. Migration is
optional, defaults to the selected current profile, and fails closed for
malformed, duplicate, or unknown profile fields. Dry-run and repeated no-op
migrations do not change files. Neither upgrade nor profile migration rewrites
historical workflow evidence.

New events use `aiwf-event-v0.4`. Supply event observations directly through an
integration or transient live shell `AIWF_ACTOR_IDENTITY` JSON; profiles, local
metadata, and repository `.env` cannot supply that input. Missing identity is
valid; malformed input warns and becomes unknown without blocking the workflow.
Identity source labels are declared provenance, not authenticated model identity.
See [metadata.md](metadata.md) for the JSON shape and migration field policy, and
[model_workflow_analysis.md](model_workflow_analysis.md) for dataset semantics.

## Structured daily workflow operations

The default `./aiwf query context` retains the original Query Contract v1
shape. The opt-in forms below use the Runtime installed in the chosen worktree.

```sh
./aiwf query context --full-workflow
./aiwf query list --workflow-phase review --limit 20
./aiwf query check --path <dated-task-path> --finalize-ready
./aiwf query check --path <dated-task-path> --preview
./aiwf mutate new-task "sample" --priority P2
./aiwf mutate guard --pre-edit --path <dated-task-path>
```

Full-workflow context advertises `readable_records_roots` in search order.
Task queries read the configured records root and, when `legacy_enabled` is
true, dated tasks under `docs/`. Machine mutations target `records_root`.

The list accepts an exact date and exact metadata values for status, review status
and workflow phase. The example selects tasks currently in the review phase.
Run `./aiwf inspect --path <dated-task-path>` on a candidate to compare its
required authority with the latest review decision and authority. A task can
have a recorded agent pass while its required human decision is outstanding.
The limit is 1–100 and defaults to 100. The response gives a dated task path for
each match and a truncation flag. A successful preview reports the metadata
that finalize would write, or an empty projection for an already closed task.
A blocked preview has diagnostics and a null projection. The actual finalize
rechecks the evidence and authority under the writer lock.

The `mutate` family supports new-task, guard, transition, record, sync-index,
finalize and correct-finalized. Its argument grammar comes from the underlying
CLI. Creation uses the current date and rejects overwrite requests. The general
MCP server registers six of these operations when writes are explicitly enabled.
Corrections require the separate operator channel. Direct use of the CLI
requires a trusted local operator with the appropriate workflow authority.

| Operation status | Mutation state | Interpretation |
|---|---|---|
| succeeded | applied, already_applied, not_applied | Runtime observed the requested result. A pure guard has no write. An already finalized task can still receive a command audit. |
| blocked | not_applied, applied | A workflow gate rejected the action. A blocked finalize can still record its audit. A prior unresolved writer can block a new request before it starts. |
| rejected, unsupported | not_applied | Input or capability preflight failed. |
| timeout | not_applied, unknown | Lock wait expired before acquisition, or the client lost a launched process's reply. |
| failed | not_applied, partially_applied, unknown | A launch failure precedes the write. A failed post-write check or an unconfirmed outcome requires reconciliation. |

The JSON schemas ship under `.aiwf/docs/schemas/`. The receipt identifies the
confirmed target when available, operation, runtime exit code, diagnostics and
reconciliation requirement. A transport failure may have no runtime exit code.
Use operation status and mutation state together. An uncertain request must
be reconciled before retrying. See the [upgrade guide](upgrading.md) for
maintenance and the [workflow protocol](workflow_protocol.md) for review policy.
