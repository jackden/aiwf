# AIWF Upgrade Guide

## Scope

This guide is for repositories that already use AIWF and need a newer source package.
For a brand-new repository, use [adoption_guide.md](adoption_guide.md) instead.

## Supported Source Package

The source repository used with `./aiwf upgrade --source <path>` must contain:

- `aiwf`
- `.aiwf/bin/ai_workflow.py`
- `.aiwf/docs/`

That is the runtime/source package the current upgrade command validates.
If you want root `AGENTS.md` helpers to work immediately after upgrade, the repository package also needs `.aiwf/templates/AGENTS.block.md` because the AGENTS commands read that template.

## Install or Upgrade

| Repository state | Recommended path |
|---|---|
| No `aiwf` wrapper and no `.aiwf/` tree | First install |
| Root `aiwf` exists and `.aiwf/` exists | Upgrade |
| Legacy `docs/ai_*` layout exists | Upgrade / migration path |
| Partial or inconsistent layout | Run `./aiwf upgrade --check --source <source_repo>` and review blockers before `--apply` |

## Safe Upgrade Order

The current bootstrap-capable flow is:

```bash
cp /path/to/new_aiwf_repo/aiwf ./aiwf
chmod +x ./aiwf
./aiwf upgrade --check --source /path/to/new_aiwf_repo
./aiwf upgrade --dry-run --source /path/to/new_aiwf_repo
./aiwf upgrade --apply --source /path/to/new_aiwf_repo
```

This sequence was verified against the current v1.7.9 runtime.

## Upgrade Modes

| Mode | Writes files? | What it validates | What it reports | Stop when | Exit behavior |
|---|---|---|---|---|---|
| `--check` | No | Source package validity, current vs target versions, layout state, and whether relocation is needed | Current/target summary, blockers, planned updates, preserved paths, relocation plan, and a suggested next step | Any blockers are reported, or the plan is not what you want | `0` on success, `2` on blockers or invalid source |
| `--dry-run` | No | The same comparison as `--check` | The same plan without changing files | Any blockers are reported, or the planned relocations/updates are not what you want | `0` on success, `2` on blockers or invalid source |
| `--apply` | Yes | The validated plan is executed and written to disk | Installed files, preserved paths, relocated legacy paths, and a migration report path | The dry-run output does not match your expectations | `0` on success or no-op, `2` on blockers or invalid source |

`--no-relocate` skips legacy layout relocation and leaves the old layout in place.
Use it only when you intentionally want to preserve the legacy layout.

## What Upgrade Preserves

The upgrade command preserves:

- `.aiwf/records/**`
- `.aiwf/events/**`
- `.aiwf/migrations/**`
- `.aiwf/config.yaml`

Preserved means the source package must not overwrite those paths in the target repository.

## Package Records Upgrade Impact

Package Records is an optional capability exposed through:

```bash
./aiwf package records --output records.zip
```

No migration is required to use existing AIWF task creation, validation, review,
or finalize workflows. Package Records does not change workflow protocol
semantics, task front matter schema, event schema, finalize behavior, or
upgrade relocation behavior.

Use Package Records when you need to hand off workflow execution records and
related workflow evidence for analysis. It does not export the source
repository.

AIWF v1.7.9 introduces `review_agent.md` as the canonical AI/agent review
artifact for new task records. Existing records that contain only
`review_codex.md` remain supported through a legacy alias and do not require
migration.

## Relocation Behavior

Project-level `docs/`, `tools/`, and `scripts/` directories are project-owned.
AIWF does not require, copy, move, or delete a project-level `tools/ai_workflow.py`; if one exists from an older integration, upgrade preserves it unchanged and reports it as legacy project-owned content.
Remove it manually only after confirming no external caller depends on it.
AIWF upgrade and relocation must not create, overwrite, move, or assume ownership of files under root `scripts/` unless the user explicitly requests a project-specific integration.

Legacy root `docs/` migration is disabled by default.
When the target repository still contains older AIWF-owned `docs/ai_*` content, `upgrade --check` and `upgrade --dry-run` report relocation only if `--migrate-legacy-docs` is used after reviewing ownership.
`upgrade --apply --migrate-legacy-docs` moves those legacy AIWF paths into the committed v2 layout unless `--no-relocate` is set.

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

If the template file is missing in the upgraded repository, copy `.aiwf/templates/AGENTS.block.md` from the source package before relying on the AGENTS helpers.

## Post-Upgrade Validation

After `upgrade --apply`, validate the repository with:

```bash
./aiwf upgrade --check --source /path/to/new_aiwf_repo
./aiwf upgrade --dry-run --source /path/to/new_aiwf_repo
./aiwf agents check --path AGENTS.md
./aiwf check --path <task_path> --finalize-ready
```

Recommended spot checks:

- confirm the `tool_version` and `layout_version` reported by `upgrade --check`
- confirm `./aiwf` resolves the repo-local runtime at `.aiwf/bin/ai_workflow.py`
- confirm `.aiwf/docs/` exists in the upgraded repository
- confirm `./aiwf agents check --path AGENTS.md` passes when the template is present
- confirm `.aiwf/records/ai_YYYYMMDD/` is still the active records root
- confirm project-level `docs/`, `tools/`, and `scripts/` were not modified unless you explicitly chose a legacy AIWF docs migration
- confirm existing project-owned files under root `scripts/` remain unchanged
- confirm no copied generated state was accidentally staged for commit

## Troubleshooting

| Symptom | Cause | Recommended correction |
|---|---|---|
| `upgrade --check` reports missing `aiwf` or `.aiwf/bin/ai_workflow.py` | Only part of the new package was copied into the source repo or target repo | Copy the missing package paths and rerun `--check` |
| `upgrade --check` or `--dry-run` reports `relocation_required: yes` | The target repo still has legacy `docs/ai_*` paths | Review the relocation plan, then run `--apply` or intentionally use `--no-relocate` |
| `upgrade --check` warns that `tools/ai_workflow.py` exists | An older project-owned legacy file is still present | Keep it if callers depend on it, or remove it manually after confirming it is unused |
| `upgrade --dry-run` shows a destination already exists | The target repo already contains a file at the relocation destination | Resolve the duplicate path before `--apply` |
| `AIWF-AGENTS-OUTDATED` after upgrade | The managed block no longer matches `.aiwf/templates/AGENTS.block.md` | Re-run `./aiwf agents install --path AGENTS.md --yes` |
| `./aiwf agents check --path AGENTS.md` fails because the template is missing | The package copy did not include `.aiwf/templates/AGENTS.block.md` | Copy the template from the source package, then rerun the AGENTS command |
| `git status` shows copied datasets or backup files | Generated state was copied from another repository | Remove those files from the commit set and keep only the AIWF package files |

## Reference Example

- [examples/upgrade_v1_7_5_post2_to_v1_7_7.md](examples/upgrade_v1_7_5_post2_to_v1_7_7.md)
