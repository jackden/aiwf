# AIWF Upgrade Guide

## Scope

This guide is for repositories that already use AIWF and need a newer source package.
For a brand-new repository, use [adoption_guide.md](adoption_guide.md) instead.

## Supported Source Package

The source repository used with `./aiwf upgrade --source <path>` must contain:

- `aiwf`
- `.aiwf/bin/**`
- `.aiwf/docs/`
- `.aiwf/templates/`

At minimum, `upgrade --check` validates that the source package contains `aiwf`,
`.aiwf/bin/ai_workflow.py`, `.aiwf/bin/safe_paths.py`, `.aiwf/bin/lib/`,
`.aiwf/bin/lib/package_core.py`, `.aiwf/bin/lib/workflow_lock.py`,
`.aiwf/docs/`, and `.aiwf/templates/AGENTS.block.md`. It also checks for the
query and mutation result schemas declared by the source Runtime.

The runtime dependency set must include `.aiwf/bin/safe_paths.py` and
`.aiwf/bin/lib/package_core.py`.

GitHub ZIP downloads and git clones are both supported as source packages when
`--source` points to the extracted package root that contains `aiwf` and
`.aiwf/`.

## Install or Upgrade

| Repository state | Recommended path |
|---|---|
| No `aiwf` wrapper and no `.aiwf/` tree | First install |
| Root `aiwf` exists and `.aiwf/` exists | Upgrade |
| Legacy `docs/ai_*` layout exists | Upgrade / migration path |
| Partial or inconsistent layout | If the target starts, run `./aiwf upgrade --check --source <source_repo>`. If its launcher or a Runtime import fails, use [source-side recovery](#recover-a-target-that-cannot-start). |

## Safe Upgrade Order

Stop workflow writers before upgrading. When upgrading from v1.7.16 or another
older installer, run the new source package's launcher. Its destination checks
and file comparisons take effect on the **first** attempt. An already-running
old installer uses its own copy logic until that command exits.

```bash
SOURCE=/absolute/path/to/complete-aiwf-source
TARGET=/absolute/path/to/your-project
cd "$SOURCE"
./aiwf --repo-root "$TARGET" upgrade --check --source "$SOURCE"
./aiwf --repo-root "$TARGET" upgrade --dry-run --source "$SOURCE"
./aiwf --repo-root "$TARGET" upgrade --apply --source "$SOURCE"
```

Review the check and dry-run output before applying. After an interrupted apply,
correct the reported filesystem problem and repeat the check from the same
complete source. A matching version alone does not establish that every
managed file was installed. Run the check again after repair.

Install, upgrade and relocation writes require directory handles that can open
each parent without following symbolic links (supported on Linux and macOS).
Native Windows supports install preview, upgrade checks and dry runs, and
relocation preview. An upgrade whose files already match can report a no-op.
For an upgrade that needs to write files, use a supported system with the
target and the complete source accessible there and all workflow writers stopped.

## Recover a target that cannot start

A partly installed target can raise `ImportError` before its local
`upgrade --check` starts. A missing launcher or a launcher that lost its
execute permission also prevents startup. Use the trusted, complete **source**
package to drive the repair.
Choose absolute directories and keep workflow writers stopped.

```bash
SOURCE=/absolute/path/to/complete-aiwf-source
TARGET=/absolute/path/to/project-to-repair
cd "$SOURCE" && ./aiwf --repo-root "$TARGET" upgrade --check --source "$SOURCE"
```

Confirm the target and the listed updates, preserved paths, relocations and
blockers. From the same source directory, review the dry run before applying.

```bash
./aiwf --repo-root "$TARGET" upgrade --dry-run --source "$SOURCE"
```

```bash
./aiwf --repo-root "$TARGET" upgrade --apply --source "$SOURCE"
```

Run `cd "$TARGET" && ./aiwf upgrade --check --source "$SOURCE"` to verify
that the target now launches and reports `repair_required: no`.

## Upgrade Modes

| Mode | Writes files? | What it validates | What it reports | Stop when | Exit behavior |
|---|---|---|---|---|---|
| `--check` | No | Source package validity, target dependency completeness, current vs target versions, layout state, and whether relocation is needed | Current/target summary, blockers, planned updates or repairs, preserved paths, relocation plan, and a suggested next step | Any blockers are reported, or the plan is not what you want | `0` on success, `2` on blockers or invalid source |
| `--dry-run` | No | The same comparison as `--check` | The same plan without changing files; no-op plans report `Will update: none` | Any blockers are reported, or the planned relocations/updates are not what you want | `0` on success, `2` on blockers or invalid source |
| `--apply` | Yes | The validated plan is executed and written to disk | Installed files, preserved paths, relocated legacy paths, and a migration report path | The dry-run output does not match your expectations | `0` on success or no-op, `2` on blockers or invalid source |

`--no-relocate` skips legacy layout relocation and leaves the old layout in place.
A v1 project with a custom `layout.records_root` keeps that directory as its v2 `record_root`. Compare the current and target records roots in the preview and run `./aiwf list` after upgrading.

During apply, the installer records the original plan as `*_upgrade.pending` under `.aiwf/migrations/`. An interrupted report write keeps the upgrade open even after the runtime files match. Restore access to the directory, then repeat check and apply from the same source bytes with the same migration options. The finished `*_upgrade.md` records the verified result.

Relocation is fail-closed when both a legacy source and its canonical destination
exist. AIWF reports `AIWF-RELOCATE-CONFLICT-001`, returns `2`, and does not
overwrite, merge, or delete either path automatically. The operator must review
and resolve the conflict before `relocate --apply` or upgrade apply.

## What Upgrade Preserves

The upgrade command preserves:

- `.aiwf/records/**`
- `.aiwf/events/**`
- `.aiwf/migrations/**`
- `.aiwf/guidance/**`
- `.aiwf/config.yaml`

Preserved means the source package must not overwrite those paths in the target repository.
For an existing v2 layout, custom record and event paths, comments and settings
in `.aiwf/config.yaml` are retained byte for byte. Source-only internal docs,
private knowledge and release helpers are excluded from both install and upgrade.
If an older installer already rewrote a custom configuration, restore it from
your project history or backup before resuming workflow operations.

## Package Records Upgrade Impact

Package Records is an optional capability exposed through:

```bash
./aiwf package records --task "$TASK" --output records.zip
```

No migration is required to use existing AIWF task creation, validation, review,
or finalize workflows. Package Records does not change workflow protocol
semantics, task front matter schema, event schema, finalize behavior, or
upgrade relocation behavior.

Set `TASK` to the full dated task directory before using the example.
See the [Reporting Guide](reporting.md#package-records) for selection and
the contents to inspect before sharing.

AIWF v1.7.9 introduces `review_agent.md` as the canonical AI/agent review
artifact for new task records. Existing records that contain only
`review_codex.md` remain supported through a legacy alias and do not require
migration.

## v1.7.14 review-authority release boundary

The v1.7.14 runtime creates `ai-workflow-v1.7` tasks with
`required_review_authority` (default `human`) and writes review evidence as
`aiwf-event-v0.3` in that release. Review records use v0.4 starting in v1.7.15
and still must provide
`--decision-authority` and a non-empty `--recorded-by` (or `AIWF_ACTOR`).

Upgrade preserves existing task artifacts and event rows. Legacy event schemas
remain readable; finalized legacy tasks are not retroactively invalidated by
the new authority semantics. An active older task that explicitly requires
human review must obtain structured authority evidence before it can close.
This is an evidence-consistency check, not human authentication.

## v1.7.15 actor identity evidence boundary

No user action or profile migration is required for a safe upgrade. Old profiles
remain loadable and usable as configured context. Starting with this release,
both command and evidence events use `aiwf-event-v0.4`, with execution identity
kept separately in `actor_identity`. Profile model/provider/reasoning values
never become execution observations. Missing identity is unknown and valid;
conflicting identity remains preserved without automatic resolution. Neither
state adds closure blockers. Review decision authority remains unchanged.

Historical task artifacts, validation/review events, finalize events, and
finalized manifests remain unchanged. Readers accept legacy/new mixtures, and
dataset version `2` marks legacy configured attribution as unverified.
This is an evidence semantics change, not a metadata cleanup patch.

Optional cleanup after upgrade:

```bash
./aiwf profile migrate --dry-run
./aiwf profile migrate
```

These commands operate only on the selected profile; provide a profile name to
select another. Migration preserves runtime configuration, removes census-backed
deprecated attribution fields, and rejects malformed, duplicate, or unknown keys
before writing. Repeating migration is a no-op. No-migration and migrated
configuration are both supported. See [metadata.md](metadata.md).

## Relocation Behavior

Project-level `docs/`, `tools/`, and `scripts/` directories are project-owned.
AIWF does not require, copy, move, or delete a project-level `tools/ai_workflow.py`; if one exists from an older integration, upgrade preserves it unchanged and reports it as legacy project-owned content.
Remove it manually only after confirming no external caller depends on it.
AIWF upgrade and relocation must not create, overwrite, move, or assume ownership of files under root `scripts/` unless the user explicitly requests a project-specific integration.

Legacy root `docs/` migration is disabled by default.
When the target repository still contains older AIWF-owned `docs/ai_*` content, `upgrade --check` and `upgrade --dry-run` report relocation only if `--migrate-legacy-docs` is used after reviewing ownership.
`upgrade --apply --migrate-legacy-docs` moves those legacy AIWF paths into the committed v2 layout unless `--no-relocate` is set.
For an existing v2 configuration, migration uses its configured documentation
and record directories. Moves must stay within the target's `.aiwf/` tree
and on one filesystem. Review both locations in the dry run.

Upgrade with legacy migration uses the same conflict preflight as relocation. A
conflict aborts before runtime, config, docs, event, or report mutation, and no
successful upgrade report or relocated-path count is published.

When explicitly enabled, legacy AIWF relocation rules cover:

- `docs/workflow_protocol.md`
- `docs/diagnostics.md`
- `docs/repo_boundary.md`
- `docs/adoption_guide.md`
- `docs/reporting.md`
- `docs/agent_integration.md`
- `docs/metadata.md`
- `docs/packaging.md`
- `docs/agent_rules`
- `docs/releases`
- `docs/examples`
- `docs/knowledge`
- legacy `docs/ai_YYYYMMDD/` task trees

## AGENTS.md Integration

`AGENTS.md` stays at the repository root.
Upgrade preserves the file and does not relocate it.

- `./aiwf agents print-block` reads `.aiwf/templates/AGENTS.block.md`.
- `./aiwf agents check --path AGENTS.md` validates the installed block and reports `AIWF-AGENTS-OUTDATED` when the managed block drifts.
- `./aiwf agents install --path AGENTS.md --yes` creates or updates only the managed block and preserves the rest of the file.

If the target repository is already on the same tool version but is missing
`.aiwf/templates/AGENTS.block.md`, `upgrade --check` reports repair as needed and
`upgrade --apply` reinstalls `.aiwf/templates/**`.

## Post-Upgrade Validation

After `upgrade --apply`, validate the repository with:

```bash
./aiwf --help
./aiwf upgrade --check --source /path/to/new_aiwf_repo
./aiwf upgrade --dry-run --source /path/to/new_aiwf_repo
./aiwf agents check --path AGENTS.md
./aiwf query context
```

If the repository already has tasks, run `./aiwf list` and use
`./aiwf check --path "$TASK"` on a known dated task path. Use
`--finalize-ready` when evaluating that task for closure. An open task
awaiting validation or human review can legitimately report closure blockers.

Recommended spot checks:

- confirm the `tool_version` and `layout_version` reported by `upgrade --check`
- confirm `./aiwf` resolves the repo-local runtime at `.aiwf/bin/ai_workflow.py`
- confirm `.aiwf/bin/safe_paths.py` and `.aiwf/bin/lib/package_core.py` exist in the upgraded repository
- confirm `.aiwf/docs/` exists in the upgraded repository
- confirm `.aiwf/templates/AGENTS.block.md` exists in the upgraded repository
- confirm `./aiwf agents check --path AGENTS.md` does not fail because the managed block template is missing
- confirm the target's reported records root matches the one in your v2
  configuration (`.aiwf/records` by default), then use `./aiwf list` to
  check that your dated tasks are visible
- confirm project-level `docs/`, `tools/`, and `scripts/` were not modified unless you explicitly chose a legacy AIWF docs migration
- confirm existing project-owned files under root `scripts/` remain unchanged
- confirm no copied generated state was accidentally staged for commit

## Troubleshooting

| Symptom | Cause | Recommended correction |
|---|---|---|
| `upgrade --check` reports a missing required source package path | Only part of the new package was copied into the source repo | Use a source package that contains `aiwf`, `.aiwf/bin/**`, `.aiwf/docs/**`, and `.aiwf/templates/**`, then rerun `--check` |
| Target `./aiwf` is missing or raises an import error before showing its plan | Its own Runtime cannot start | Run the [source-side recovery procedure](#recover-a-target-that-cannot-start) |
| `upgrade --check` reports `repair_required: yes` for the same tool version | One or more managed package files are missing, incomplete or differ from the complete source | Review the listed paths and use the source-side apply command above, then repeat the check |
| `upgrade --check` or `--dry-run` reports `relocation_required: yes` | The target repo still has legacy `docs/ai_*` paths | Review the relocation plan, then run `--apply` or intentionally use `--no-relocate` |
| `upgrade --check` warns that `tools/ai_workflow.py` exists | An older project-owned legacy file is still present | Keep it if callers depend on it, or remove it manually after confirming it is unused |
| `upgrade --check` or `--dry-run` reports `AIWF-RELOCATE-CONFLICT-001` | A legacy source and canonical destination both exist | Review both paths, resolve the duplicate explicitly, then rerun the command before `--apply` |
| `AIWF-AGENTS-OUTDATED` after upgrade | The managed block no longer matches `.aiwf/templates/AGENTS.block.md` | Re-run `./aiwf agents install --path AGENTS.md --yes` |
| `./aiwf agents check --path AGENTS.md` fails because the template is missing | The target was upgraded by an older package copy scope | Run `./aiwf upgrade --check --source <source_repo>` and apply the reported repair |
| `git status` shows copied datasets or backup files | Generated state was copied from another repository | Remove those files from the commit set and keep only the AIWF package files |

## Reference Example

- [examples/upgrade_v1_7_5_post2_to_v1_7_7.md](examples/upgrade_v1_7_5_post2_to_v1_7_7.md)
