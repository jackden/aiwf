# Legacy / Backfill Workflow Rules

## Legacy / Backfill Work Record Rules

When backfilling old AI work records to the current workflow format:

1. Prefer task-specific directories.
   - Standard format: `.aiwf/records/ai_YYYYMMDD/NNN_short_task_name/`

2. Do not place task-specific `task.md` or `agent.md` directly under `.aiwf/records/ai_YYYYMMDD/` unless that date directory contains exactly one historical task.

3. If `.aiwf/records/ai_YYYYMMDD/` contains multiple historical tasks or mixed records:
   - create a new task-specific subdirectory, for example `.aiwf/records/ai_YYYYMMDD/NNN_ddf_cleanup_backfill/`
   - move or create only the new v1.1 backfill files in that subdirectory
   - do not rewrite or relocate historical files unless explicitly requested

4. If the original historical record has no task-specific subdirectory:
   - preserve the original files in place
   - create a new backfill task directory for the v1.1 additions
   - link back to the original historical files from `task.md`

5. For backfill tasks, always record:
   - original historical path
   - selected backfill path
   - reason for selecting that path
   - whether the original historical structure was preserved

6. Update the relevant `index.md` to make the relationship clear.

7. For any v1.1 backfill, never add task-specific files directly under `.aiwf/records/ai_YYYYMMDD/`. Always create or use a task-specific subdirectory.

## Backfill Trigger Contract

When the user requests:

```text
backfill <path>
```

The agent must:

1. Treat the task as a v1.1 workflow backfill.

2. Scope:
   - Only operate on the specified path.
   - Do not expand to other tasks.

3. Actions:
   - If `<path>` is already a task-specific directory, add `task.md` and `agent.md` under that directory.
   - If `<path>` is a date-level directory (`.aiwf/records/ai_YYYYMMDD/`) or a legacy mixed directory, create a task-specific backfill subdirectory first.
   - Never add task-specific `task.md` or `agent.md` directly under `.aiwf/records/ai_YYYYMMDD/`.
   - Preserve all existing historical files.
   - Do not rewrite historical conclusions.
   - Create knowledge writeback if reusable patterns or bugs exist.

4. Knowledge:
   - Write to `.aiwf/docs/knowledge/patterns|bugs|decisions`.
   - Do not duplicate existing knowledge files.

5. Record:
   - Create a new AI work record under `.aiwf/records/ai_<current YYYYMMDD>/NNN_<backfill_name>/`.
   - Task ID allocation must come from workflow tooling (`new-task`/`next-id`), not manual inference.
   - Include `task.md`, `agent.md`, `task_record.md`, `self_validation.md`, `review_agent.md`, and `review_final.md`.
   - Treat `review_codex.md` as a legacy alias when reading existing historical records; do not rename historical evidence unless explicitly requested.

6. Safety:
   - Do not run real DUT tests.
   - Do not run destructive operations.
   - Prefer static validation only.

7. Validation:
   - Verify files exist.
   - Verify no business code changes.
   - Verify knowledge created or updated.

8. Output:
   - Summarize selected path, files added, knowledge written, and limitations.
