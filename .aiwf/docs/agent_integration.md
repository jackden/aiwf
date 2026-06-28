# Agent Integration

## Purpose

`AGENTS.md` remains at the repository root as a thin managed bootstrap entrypoint.
The managed block is the only portion that AIWF owns.

## Managed Block Boundaries

AIWF treats the region between these markers as managed content:

```md
<!-- AIWF:BEGIN -->
...
<!-- AIWF:END -->
```

Everything outside the managed block is user-owned content and must be preserved.

## Template Source of Truth

The managed block text comes from `.aiwf/templates/AGENTS.block.md`.
`./aiwf agents print-block` reads that template and prints the block text only.

If the template file is missing, `agents print-block`, `agents check`, and `agents install` cannot render or validate the managed block.
Copy the template into the repository package before using the AGENTS helpers.

## Command Behavior

### `./aiwf agents print-block`

- Prints the managed block from `.aiwf/templates/AGENTS.block.md`.
- Does not modify files.

### `./aiwf agents check --path AGENTS.md`

- Validates the root file or another explicit `AGENTS.md` path.
- Returns `AIWF-AGENTS-001` when the file is missing.
- Returns `AIWF-AGENTS-002` when the managed block is missing.
- Returns `AIWF-AGENTS-003` when the managed block is incomplete.
- Returns `AIWF-AGENTS-OUTDATED` when the managed block text differs from `.aiwf/templates/AGENTS.block.md`.
- Returns `AIWF-AGENTS-OK` when the managed block matches the template.

### `./aiwf agents install --path AGENTS.md --yes`

- Requires `--yes` before it writes.
- Creates `AGENTS.md` if the file does not exist.
- Appends the managed block if the file exists but does not yet contain one.
- Replaces only the managed block when one already exists.
- Preserves all block-external content.

## Example Managed Block

```md
<!-- AIWF:BEGIN -->
This repository uses AIWF.
Before editing repository files:
- Read `.aiwf/docs/agent_rules/00_root_entrypoint.md`
- Read `.aiwf/docs/workflow_protocol.md`
Use `./aiwf` for:
- task creation
- pre-edit guard
- validation
- review evidence
- `./aiwf finalize`
- `./aiwf check --path <task_path>`
- `./aiwf check --path <task_path> --finalize-ready`
Do not manually rewrite AIWF task front matter.
AIWF workflow records are stored under:
.aiwf/records/
Workflow events are stored under:
.aiwf/events/
<!-- AIWF:END -->
```

## Current Usage Pattern

- Use `./aiwf agents install --path AGENTS.md --yes` after first install or when a block needs to be refreshed.
- Use `./aiwf agents check --path AGENTS.md` in validation and before commit.
- Use `./aiwf agents print-block` when you want the canonical block text for review or comparison.

## Notes

- `AGENTS.md` is supported whether it already exists or not.
- Outdated managed blocks are expected to be repaired by reinstalling the block, not by hand-editing inside the managed region.
- This integration is intentionally minimal and does not introduce any other adapter generation or repo relocation behavior.
