# AIWF Diagnostics Catalog

| Code | Severity | Meaning | Typical Cause | Suggested Fix |
|---|---|---|---|---|
| `AIWF-FINALIZED-002` | error | Evidence record is rejected because task is finalized. | Trying to run `record` after successful `finalize`. | Do not append evidence to a finalized task. Create a follow-up task. |
| `AIWF-FINALIZE-001` | info | Task is already finalized; `finalize` is idempotent/no-op. | Re-running `finalize` on a closed task. | No action required. |
| `AIWF-CORRECTION-001` | error | Post-finalization correction requires a finalized task. | Correction target is still open or has incomplete finalized metadata. | Finalize the task first, or create a separate follow-up task. |
| `AIWF-CORRECTION-002` | error | Correction type is not in the v1 correction taxonomy. | Unsupported `--type` value. | Use `implementation_reverted`, `scope_reclassified`, `conclusion_corrected`, `evidence_superseded`, or `current_state_clarification`. |
| `AIWF-CORRECTION-003` | error | Correction authority is not an explicit human authority. | Authority is empty or does not match `human_*`. | Supply a value such as `human_scope_decision`; agent/automated authority is fail-closed. |
| `AIWF-CORRECTION-004` | error | Correction text is empty or contains a newline. | `--current-state` or `--reason` is missing or not a deterministic single-line value. | Supply non-empty single-line text for both fields. |
| `AIWF-CORRECTION-005` | error | Correction directory contains an invalid or colliding artifact name. | A file, symlink, or duplicate ID does not match the deterministic correction layout. | Review `corrections/` and keep unique files named like `001_implementation_reverted.md`. |
| `AIWF-CORRECTION-006` | error | A correction artifact has invalid machine-authoritative metadata. | Required correction front matter/body is missing or malformed. | Recreate the correction through `./aiwf correct-finalized`; do not hand-edit it. |
| `AIWF-CORRECTION-007` | error | Correction path is not a safe directory under the task. | `corrections/` is a symlink or conflicting filesystem object. | Resolve the path conflict explicitly before retrying. |
| `AIWF-CORRECTION-008` | error | Deterministic correction ID collides with an existing artifact. | A concurrent/manual artifact occupies the next correction ID. | Resolve the collision and retry after review. |
| `AIWF-INSPECT-001` | error | `inspect` requires a task-specific directory. | A date root or unsupported path was supplied. | Use `.aiwf/records/ai_YYYYMMDD/NNN_task_name`. |
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
| `AIWF-META-TAG-001` | error | A new-task tag is not a canonical tag value. | `--tag` contains uppercase characters, spaces, or unsupported punctuation. | Use a lowercase tag beginning with a letter or digit and containing only `a-z`, `0-9`, `_`, or `-`. |
| `AIWF-META-PROFILE-004` | warn | The active current-profile pointer does not resolve to a profile file. | `.aiwf/metadata.current` names a profile that does not exist under `.aiwf/metadata_profiles/`. | List profiles, switch to an existing one, or create the missing profile. |
| `AIWF-META-RUNTIME-001` | error | A runtime metadata option uses an invalid value. | `AIWF_EVENT_LOG` is set to something other than `0` or `1`. | Use `AIWF_EVENT_LOG=1` to enable event logging or `AIWF_EVENT_LOG=0` to disable it. |
| `AIWF-DATE-001` | error | `new-task --date` was provided with a non-today date without explicit override. | A normal new task tried to target a historical/future date without `--allow-non-today-date`. | Omit `--date` for normal new tasks, or use `--allow-non-today-date` only for explicit historical/recovery work. |
| `AIWF-DATE-002` | error | A `--date` value does not match `YYYYMMDD` format. | The provided date string is malformed. | Use `YYYYMMDD`, for example `20260604`. |
| `AIWF-DATE-003` | error | A `--date` value is not a valid calendar date. | The provided date string has the right shape but is not a real calendar date. | Use a real calendar date in `YYYYMMDD`, for example `20260604`. |
| `AIWF-DATE-RANGE-001` | error | A package-records date range is reversed. | `--from-date` is later than `--to-date`. | Set `--from-date` to a date on or before `--to-date`; equal endpoints are valid. |
| `AIWF-SELECTOR-001` | error | A package/list enum selector is not a canonical allowed value. | `--status`, `--workflow-phase`, or `--review-status` contains an unknown or differently cased value. | Use one of the listed exact, case-sensitive values. Validation happens before discovery and output mutation. |
| `AIWF-TASK-ID-001` | error | The AI record date path exists but is not a directory. | `next-id` or task creation found a conflicting filesystem object at the AI date path. | Remove or rename the conflicting filesystem object before allocating a task ID. |
| `AIWF-DATASET-OUTPUT-001` | error | Dataset output is under the configured AIWF records root. | A relative, absolute, or symlink-resolved output target would write analytical data into workflow evidence records. | Choose a repository-local output outside AIWF records, for example `artifacts/dataset.json` or `reports/aiwf/dataset.json`. |
| `AIWF-DATASET-OUTPUT-002` | error | Dataset output resolves outside the repository boundary. | An absolute output or repository-local symlink resolves outside the repository. | Choose a repository-local output path outside the configured AIWF records root. |
| `AIWF-CLI-PATH-001` | error | A deterministic command target path does not exist. | `check`, `doctor`, `finalize`, `transition`, `record`, `sync-index`, `report`, or an export command received a missing target. | Provide an existing repository-local path supported by the command. |
| `AIWF-CLI-PATH-002` | error | A deterministic command target path resolves outside the repository boundary. | A command target is an external absolute path or a repository-local symlink escape. | Use a repository-relative path that resolves within the current repository. |
| `AIWF-BACKFILL-PATH-001` | error | A backfill target exists but is not a directory. | `backfill` received a regular file instead of a directory. | Provide an existing directory path supported by backfill. |
| `AIWF-BACKFILL-NOOP` | info | Existing backfill target already matches the requested source. | The same deterministic source identity was backfilled previously and all required artifacts exist. | No action required. |
| `AIWF-BACKFILL-IDENTITY-001` | error | An existing backfill task has the same normalized name but a different source identity. | A requested source would create a duplicate or conflict with an existing backfill provenance record. | Review the existing task and requested legacy source; AIWF will not create a duplicate or select a canonical task automatically. |
| `AIWF-BACKFILL-INCOMPLETE-001` | error | A matching backfill target is missing required artifacts. | A previous backfill was incomplete, and `--update-existing` was not supplied. | Run backfill with `--update-existing` to create missing artifacts only. |
| `AIWF-BACKFILL-PRESERVE-001` | error | A finalized target is missing an artifact that backfill would otherwise add. | A finalized historical record is incomplete. | Review manually or use a separate repair/migration task; backfill will not modify finalized evidence. |
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
| `AIWF-AGENTS-PATH-001` | error | The resolved AGENTS path is outside the repository boundary. | An absolute outside path, `..` traversal, or repository-local symlink resolves outside the repository. | Use a repository-relative path that resolves within the current repository. The `--yes` option cannot bypass this check. |
| `AIWF-RELOCATE-CONFLICT-001` | error | A legacy source and its canonical destination both exist. | Relocation or upgrade legacy-docs migration found an ambiguous duplicate path. | Review both paths and resolve the conflict explicitly. AIWF will not overwrite, merge, or delete either path automatically. |

## Deterministic Input Exit Codes

Deterministic user-input and repository-path validation failures return exit
code `2`. This includes field-specific new-task metadata rejection, missing or
outside command target paths, backfill target validation, agents installation
confirmation rejection, and dataset repository-boundary rejection. This local
rule does not redefine exit behavior for repository discovery/configuration
errors, internal invariant failures, unexpected runtime failures, argparse
usage errors, or process interruption.

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
- `package records` rejects a reversed `--from-date`/`--to-date` range before task discovery, output validation, or `--force` replacement.
- `package records` and `list` validate status, workflow phase, and review status with exact, case-sensitive matching. A valid selector that matches no tasks remains a successful empty result.

## List Selector Semantics

An empty `list` result means that valid selectors matched no tasks. It does
not mean that an unknown selector was accepted: invalid status, workflow
phase, and review status values return `2` with `AIWF-SELECTOR-001` before the
task table or `Total: 0` line is printed.

## Task ID and new-task side-effect notes

- `next-id` and the internal `next_task_id()` lookup are read-only. A missing AI date directory returns `001` without creating the directory, index, event, or report.
- An existing AI date path that is not a directory fails closed with `AIWF-TASK-ID-001`.
- `new-task` validates deterministic metadata inputs before AI date/task directory allocation. Rejected input does not leave an orphan date directory or partial task artifacts.

## Warning Semantics Note
- `AIWF-FINALIZED-001` is a post-finalize mtime warning, not a finalize blocker by itself.
- It means one or more task files were modified after `finalized_at`.
- A task can still pass `check --finalize-ready` with this warning, but the warning should be reviewed before treating the task as immutable evidence.
- `AIWF-PATH-015` is a finalize blocker for v1.6 task integrity drift against the recorded finalize artifact manifest.
- `AIWF-FINALIZE-001` confirms `finalize` idempotency/no-op on closed tasks; do not treat "re-run finalize" as a repair path for finalized artifact drift.
- `AIWF-PATH-020` through `AIWF-PATH-024` are workflow-readiness checks only; they do not prove or disprove the underlying business result.
