# AIWF Adoption Guide

## Scope

This guide covers first-time AIWF adoption in a repository that does not yet use the committed v2 layout.
If the repository already has AIWF files and workflow evidence, use [upgrading.md](upgrading.md) instead.

## Preconditions

- Run the commands from the repository root.
- Use Bash and Python 3.10 or newer for the commands below.
- Install from macOS or Linux. On native Windows, omit `--yes` to preview
  the install. Writing package files requires a platform that can open
  destination directories without following symbolic links.
- Keep the working copy on supported local storage if you plan to create tasks
  or record evidence. Core qualifies APFS/HFS on macOS and specific local
  filesystems on Linux. Native Windows lacks a supported writer backend.
  Some text observations remain available with a warning on unsupported
  storage. [Storage and locking requirements](cli_reference.md#concurrent-workflow-operations-and-recovery)
- Git is optional for the CLI itself, but you will usually want a git repository if you plan to commit the installed files and future workflow records.
- An existing `AGENTS.md` is supported.
- Back up local work before installing AIWF into a repository that already contains edits.

## Supported Package Contents

Copy the AIWF package from a trusted source tree. The supported install set is:

- `aiwf`
- `.aiwf/bin/`
- `.aiwf/docs/`
- `.aiwf/templates/`
- `.aiwf/config.yaml`

Those paths provide the wrapper, canonical runtime, docs, managed AGENTS template, and committed layout config.
AIWF owns only the root `./aiwf` entrypoint and the `.aiwf/` namespace. Project-level `docs/`, `tools/`, and `scripts/` directories remain project-owned and are not required for a first install.
The first-install flow must not create, overwrite, or assume ownership of files under root `scripts/` unless the user explicitly requests a project-specific integration.

## Install Boundary

Public repository contents are not the install payload. The fresh installer has
an explicit allowlist for the launcher, `.aiwf/bin/`, `.aiwf/docs/`,
`.aiwf/templates/`, and `.aiwf/config.yaml`. Repository-level development
assets are source-only and are intentionally excluded, including `tests/`,
`.github/`, root `docs/`, `knowledge/`, release files, CI assets, and review
artifacts.

If the target already contains `tests/`, `.github/`, or root `docs/`, install
does not merge, copy, overwrite, rename, or otherwise modify those directories.
The installer creates only the AIWF-owned namespace and its empty workflow
state directories.

Do not copy repo-local or generated state from another repository:

- `.aiwf/records/`
- `.aiwf/events/`
- `.aiwf/migrations/`
- `.aiwf/metadata_profiles/`
- `.aiwf/metadata.current`
- `.aiwf/metadata.local.env`
- local dataset exports
- temporary backup directories

## Canonical First-Install Flow

Use the source package's wrapper as the single fresh-install command:

```bash
/path/to/aiwf-package/aiwf install --target .
/path/to/aiwf-package/aiwf install --target . --yes
```

The first command performs all preflight checks and writes nothing. The second
applies the validated plan, installs the package-owned files, creates empty
records/events/migrations directories, and installs the managed `AGENTS.md`
block while preserving user-owned content outside that block.

Install is fail-closed for complete or partial layouts, source/target path
conflicts, missing source package files, and failed post-install validation. A
write-time failure is rolled back. Install does not download, migrate, repair,
or silently become upgrade.

If `AGENTS.md` already exists, `agents install` preserves everything outside the managed block.
If `AGENTS.md` does not exist, `agents install` creates the file with the managed block in place.

## Connect an MCP client

To use AIWF in Codex CLI, GitHub Copilot CLI or VS Code, install the optional
adapter in its own Python environment using a wheel or the AIWF source package.
Point the client at the project where you installed Core. The walkthrough is
included in this project's `.aiwf/docs/examples/` directory and shows how to
verify the connection and create a first task. [MCP setup walkthrough (繁體中文)](examples/mcp_setup.md)

## Root AGENTS.md Integration

- `./aiwf agents print-block` prints the managed block text from `.aiwf/templates/AGENTS.block.md`.
- `./aiwf agents check --path AGENTS.md` validates the installed block and returns `AIWF-AGENTS-OUTDATED` when the block drifts from the template.
- `./aiwf agents install --path AGENTS.md --yes` creates, appends, or replaces only the managed block and preserves the rest of the file.
- The managed block boundaries are `<!-- AIWF:BEGIN -->` and `<!-- AIWF:END -->`.
- `AGENTS.md` stays at the repository root.

If the template file is missing, the `agents` commands cannot render or validate the managed block. Copy `.aiwf/templates/AGENTS.block.md` from the package before using `agents check` or `agents install`.

## Validation Checklist

- `./aiwf --help` opens the repo-local CLI.
- `./aiwf agents check --path AGENTS.md` confirms the root managed block.
- `./aiwf query context` checks structured query support on this working copy.
  If it reports `AIWF-LOCK-UNSUPPORTED`, review the storage requirements
  before creating a task. For the current process's root write permission,
  inspect `result.mutation_root_writable` in `./aiwf query context --full-workflow`.
- Use the [worked example](examples/basic_lifecycle.md) to create the first task,
  test the installed managed block and record the result. If the task already
  exists, resume using the dated path printed by `./aiwf list`.
- `./aiwf doctor --path <generated_task_path>` is a useful task-level sanity check once you have a real task path.
- `./aiwf install --target .` is a read-only preflight when invoked from a source package.
- `git status --short` should not show copied generated state that you did not intend to commit.

## What To Commit

Commit the copied package files and any intentional `AGENTS.md` update:

- `aiwf`
- `.aiwf/bin/`
- `.aiwf/docs/`
- `.aiwf/templates/`
- `.aiwf/config.yaml`
- `AGENTS.md` changes that only update the managed block

Do not copy or commit workflow records, events, migrations, metadata profiles, dataset exports, or backup directories from the source AIWF repository.
After installation, workflow records and event logs generated by the target repository follow that repository's normal AIWF evidence-retention policy and are typically committed as repository-native workflow evidence.
If an older repository already has a project-level `tools/ai_workflow.py`, treat it as project-owned legacy content. AIWF does not require it for new public installations.
Existing project-owned files under root `scripts/` should remain unchanged during installation.

## Troubleshooting

| Symptom | Cause | Recommended correction |
|---|---|---|
| `./aiwf` says bootstrap mode only supports upgrade commands | The canonical runtime is missing and the command is not being run from a source package | Use `/path/to/aiwf-package/aiwf install --target . --yes`, or use `upgrade` for an existing installation |
| `AIWF-AGENTS-001` or `AGENTS.md file not found` | Root `AGENTS.md` has not been created yet | Run `./aiwf agents install --path AGENTS.md --yes` from the repo root |
| `AIWF-AGENTS-OUTDATED` | The managed block drifted from `.aiwf/templates/AGENTS.block.md` | Re-run `./aiwf agents install --path AGENTS.md --yes` |
| The target launcher is missing or its Runtime cannot import a dependency | Only part of the package is present | Use the [source-side recovery procedure](upgrading.md#recover-a-target-that-cannot-start) with a complete package |
| Copied files appear under `git status` but you did not mean to commit them | Generated state or backup artifacts were brought over from another repository | Remove the generated files from the commit set and keep only the installed package files |
