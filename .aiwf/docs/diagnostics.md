# AIWF Diagnostics Catalog

| Code | Severity | Meaning | Typical Cause | Suggested Fix |
|---|---|---|---|---|
| `AIWF-FINALIZED-002` | error | Evidence record is rejected because task is finalized. | Trying to run `record` after successful `finalize`. | Do not append evidence to a finalized task. Create a follow-up task. |
| `AIWF-FINALIZE-001` | info | Task is already finalized; `finalize` is idempotent/no-op. | Re-running `finalize` on a closed task. | No action required. |
| `AIWF-PATH-019` | error | Post-finalize event pollution detected in event chain. | `.aiwf/events/events.jsonl` contains evidence-changing events after closure. | Inspect `.aiwf/events/events.jsonl`; treat as closure contamination and continue in follow-up task. |
| `AIWF-PATH-013` | error | Metadata is finalized but no `finalize_success` event exists. | Task metadata was manually changed to finalized, or finalize evidence was lost/missing. | Re-run `finalize` through `ai_workflow.py` when possible, or repair through a controlled follow-up/migration path. |
| `AIWF-PATH-015` | error | Finalized artifact changed after finalize. | Required task artifacts drifted from `finalize_success.artifact_manifest` after closure. | Revert post-finalize edits, or use a controlled amend/reopen command if supported. Do not manually edit finalized task artifacts. |
| `AIWF-FINALIZED-001` | warn | Finalized task file was modified after `finalized_at`. | One or more task markdown files have mtime later than the recorded closure time. | Review post-finalize edits. If new work is needed, open a follow-up task rather than appending evidence to the closed task. |
| `INDEX_STATUS_STALE` | error | Parent index projection status does not match task metadata status. | `index.md` not synchronized after metadata mutations. | Run `sync-index --path <task_dir>` or finalize again after fixing metadata state. |
| `INDEX_STATUS_INVALID_DONE` | error | Index status `done` is inconsistent with task metadata/finalized semantics. | Manual index edits or broken projection state. | Repair metadata/index consistency, then run `sync-index` and `check`. |
| `AIWF-REVIEW-002` | error | Review state is incompatible with completion criteria. | Review result is fail/pending/unknown while trying to finalize. | Complete review-fix-revalidation loop; record review pass or explicit allowed state. |
| `AIWF-META-007` | error | Metadata is invalid for expected schema/invariants. | Missing or malformed required metadata fields. | Fix task front matter fields and re-run `check`. |
| `AIWF-META-009` | error | A metadata list field contains an invalid item. | A list field such as `related_tasks`, `blocked_by`, `supersedes`, or `tags` contains a non-canonical item. | Use canonical metadata item format. |
| `AIWF-META-010` | error | A task reference field does not use canonical task id format. | A task reference field such as `parent_task` contains a non-canonical value. | Use canonical task id format `NNN`, for example `014`. |
| `AIWF-META-011` | error | `related_files` contains an unsafe or invalid repo-relative path. | `related_files` contains an absolute path or parent traversal such as `/etc/passwd` or `../secret.txt`. | Use a repo-relative path such as `examples/test_raw_disk.py`. |
| `AIWF-META-PROFILE-004` | warn | The active current-profile pointer does not resolve to a profile file. | `.aiwf/metadata.current` names a profile that does not exist under `.aiwf/metadata_profiles/`. | List profiles, switch to an existing one, or create the missing profile. |
| `AIWF-META-RUNTIME-001` | error | A runtime metadata option uses an invalid value. | `AIWF_EVENT_LOG` is set to something other than `0` or `1`. | Use `AIWF_EVENT_LOG=1` to enable event logging or `AIWF_EVENT_LOG=0` to disable it. |
| `AIWF-DATE-001` | error | `new-task --date` was provided with a non-today date without explicit override. | A normal new task tried to target a historical/future date without `--allow-non-today-date`. | Omit `--date` for normal new tasks, or use `--allow-non-today-date` only for explicit historical/recovery work. |
| `AIWF-DATE-002` | error | A `--date` value does not match `YYYYMMDD` format. | The provided date string is malformed. | Use `YYYYMMDD`, for example `20260604`. |
| `AIWF-DATE-003` | error | A `--date` value is not a valid calendar date. | The provided date string has the right shape but is not a real calendar date. | Use a real calendar date in `YYYYMMDD`, for example `20260604`. |
| `AIWF-NEW-TASK-001` | error | `new-task` is create-only; `--update-existing` is unsupported. | An existing-task update flag was passed to task creation. | Use path-based commands for an existing task, or create a distinctly named follow-up task. No files are written. |
| `AIWF-TASK-NAME-001` | error | Duplicate normalized task names exist within one AI record date. | A same-date task was created by an older runtime, copied manually, or otherwise bypassed the creation gate. | Preserve one canonical task and resolve the duplicate; use a distinct name for intentional follow-up work. |
| `AIWF-PLACEHOLDER-001` | error | Required doc still contains unresolved placeholder content. | Template placeholders were not replaced. | Fill required sections with real content before finalize. |
| `AIWF-PATH-010` | error | Missing validation pass before finalize. | No successful validation evidence exists before finalize readiness checks. | Run validation, record validation pass evidence, then re-run `check --finalize-ready`. |
| `AIWF-PATH-014` | error | Latest effective review decision is missing, stale, or not final. | The task has no valid final review decision after latest relevant fail/fix evidence. | Complete review and record a fresh final decision (`pass`/`not_required`) before finalize. |
| `AIWF-PATH-016` | error | Event log is malformed or unreadable for v1.6 finalize. | `.aiwf/events/events.jsonl` contains malformed JSONL, unreadable content, or unexpected structure. | Inspect and repair the event log carefully, or restore valid lifecycle evidence through a controlled follow-up/migration path. |
| `AIWF-PATH-020` | error | Pending validation residue is still present in a closure artifact. | `task_record.md` or `self_validation.md` still uses pending validation template text instead of an actual result. | Replace pending validation text with real validation outcome or explicit skipped rationale. |
| `AIWF-PATH-021` | error | Pending review residue is still present in a closure artifact. | `review_final.md` still contains pending reviewer/decision template text. | Replace pending review text with the actual review decision and reviewer. |
| `AIWF-PATH-022` | error | Default template residue remains in a required section. | A generated section such as Background, Problem, Goal, or review summary was never rewritten for the current task. | Replace default template text with task-specific closure evidence before finalize. |
| `AIWF-PATH-023` | error | Acceptance Criteria exist but no item has a closure decision. | The AC section is present, but every checkbox item is still unresolved. | Give each AC item a closure state such as passed, deferred, or not applicable before finalize. |
| `AIWF-PATH-024` | error | Acceptance Criteria still contain unresolved or blocking states. | One or more AC items remain unchecked, failed, or blocked even though the task is being prepared for closure. | Resolve the item, or mark it deferred/not applicable with rationale before finalize. |

## v1.7.5 Metadata Hardening Examples

`AIWF-META-009` example:

```yaml
related_tasks:
  - "\\\"014\\\""
```

Expected format:

```yaml
related_tasks:
  - "014"
```

## Metadata CLI Validation Hints

`./aiwf metadata validate` emits targeted guidance for AI agent attribution metadata:

- `AIWF-META-001` for invalid `source`
- `AIWF-META-002` for invalid `confidence`
- `AIWF-META-003` for invalid `provider`
- `AIWF-META-004` for invalid `tool`
- `AIWF-META-012` for invalid `reasoning_effort`

These command-level diagnostics include an `allowed-values` hint, for example:

```bash
./aiwf metadata allowed-values --field provider
./aiwf metadata allowed-values --field tool
./aiwf metadata allowed-values --field reasoning_effort
```

Use fallback values instead of inventing ad hoc identifiers:

- providers: `local`, `self_hosted`, `custom`, `other`
- tools: `custom_agent`, `script`, `manual`, `other`

## Usage
Run diagnostics with:
```bash
./aiwf check --path <task_dir>
./aiwf check --path <task_dir> --finalize-ready
./aiwf doctor --path <task_dir>
```

## Date CLI Validation Notes

- `next-id`, `list`, `new-task`, and `backfill` all reject malformed `--date` values with `AIWF-DATE-002`.
- The same commands reject invalid calendar dates with `AIWF-DATE-003`.
- `new-task` still rejects non-today dates unless `--allow-non-today-date` is set.
- `backfill` does not use the non-today guard; it only validates date syntax and calendar validity.

## Warning Semantics Note
- `AIWF-FINALIZED-001` is a post-finalize mtime warning, not a finalize blocker by itself.
- It means one or more task files were modified after `finalized_at`.
- A task can still pass `check --finalize-ready` with this warning, but the warning should be reviewed before treating the task as immutable evidence.
- `AIWF-PATH-015` is a finalize blocker for v1.6 task integrity drift against the recorded finalize artifact manifest.
- `AIWF-FINALIZE-001` confirms `finalize` idempotency/no-op on closed tasks; do not treat "re-run finalize" as a repair path for finalized artifact drift.
- `AIWF-PATH-020` through `AIWF-PATH-024` are workflow-readiness checks only; they do not prove or disprove the underlying business result.
