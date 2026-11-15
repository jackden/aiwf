# Evidence-linked Guidance

Guidance Notes preserve a reusable check, its conditions, and the local workflow
evidence behind it. Keep project-owned notes in `.aiwf/guidance/*.md`. The
helper is optional and uses Python 3.10+ with PyYAML. Run it from the project
with a Python environment that has PyYAML installed. To enable the helper, a
project maintainer can run `python -m pip install PyYAML==6.0.3` in that environment.

```sh
python .aiwf/bin/guidance.py check
python .aiwf/bin/guidance.py show --scope validation
python .aiwf/bin/guidance.py show --id GUIDE-VALIDATION-001
```

An explicit `--repo-root` before the subcommand selects a local project tree
or an already extracted snapshot. Both notes and evidence are read from that
root. Output describes that local copy.

Both `show` and `check` match `--scope` and `--id` exactly and use the value as
given. An explicit empty or whitespace-only selector exits with status `2`
before reading the collection. Omitting both selectors is supported for a
manual collection-wide query. Repeating `--scope` uses the last value when all
supplied values are nonblank. Scope unions are unsupported.

## Guidance use in task context

Use this convention before the first decision that materially affects design,
implementation, or validation. It applies when starting, taking over, resuming,
or switching a task, starting a new session, and adding a material module or
type of work. Apply it to read-only work that requires engineering judgment.
Routine mechanical file operations can proceed without a lookup. Agents follow
this convention through the [root entrypoint](agent_rules/00_root_entrypoint.md).

1. Establish the current scope from reliable tags on the canonical task and
   the project's shared scope vocabulary. If tags are absent, use a documented
   project mapping or an explicit requirement and record the reason for the
   choice. A filename alone cannot establish scope or domain applicability. If
   scope is unknown, record `scope unknown / not queried` and continue. Use
   neither a blank selector nor an unfiltered query as a fallback.
2. Run `show --scope` once per relevant scope. Combine the results by Note ID
   and consider each Note once. Use the [exit status and output](#read-results)
   together. For status `1`, withhold notes marked `REVIEW NEEDED` from use and
   assess any current references individually. For status `2`, discard the
   query as a basis for adoption. If the helper or PyYAML is missing, record
   `unavailable` and continue using the project's existing workflow. Avoid
   automatically installing dependencies or retrying the query repeatedly.
3. Consider only active notes whose sources are current and whose review still
   covers the version in use. Read Recommended Checks, Applicability,
   Inapplicable Cases, Evidence and Limitations, Recheck Triggers, and Sources
   together. Verify the current fixture, versions, dependencies, DUT state when
   relevant, and authorization before acting. Treat commands in notes as
   reference text. Task scope, Guard, project policy, and domain-tool checks
   govern any operation. An unavailable query, zero matches, or a source that
   needs review leaves those existing requirements in effect.
4. Use the session's tool trace and, as useful, the existing task record or
   handoff to capture the scope and its source, matching IDs, reasons for use
   or exclusion, and open questions. Read-only analysis may keep that context
   in the session. Keep finalized task evidence intact. Recheck in a new
   session or after a material change in scope, source, or linked corrections.
   After a fixture or DUT state change, verify domain applicability against
   the current setup. Repeating the pre-edit Guard alone needs no new lookup.

### Examples

- **New task.** If the project uses `storage_lifecycle` and `regression` for
  this work, create the task with
  `./aiwf new-task review_lifecycle_regression --tag storage_lifecycle --tag regression`.
  Keep the full path printed by `new-task`. Before choosing the validation
  strategy, run `python .aiwf/bin/guidance.py show --scope storage_lifecycle`
  and `python .aiwf/bin/guidance.py show --scope regression` separately. For a
  Note present in both results, assess its conditions once. Capture the decision
  in the ordinary task record and follow the existing Guard and review flow.
- **Resume or switch.** Confirm the task's full path, current open or finalized
  status, tags and current requirements. Query `validation` for an untagged
  task under `tests/validation/` only if the project documents that mapping.
  When analysis expands into another module, select the resulting scope from
  the updated requirements before deciding how to handle that module. If a
  linked source or correction changes, recheck the relevant Note.
- **Read-only analysis.** A request to investigate a regression can establish
  `regression` when that term is part of the project's scope vocabulary. Query
  before selecting a comparison baseline and record the reason in the session.
  When the request supplies no credible scope, record `scope unknown / not queried`.
- **Source drift and failures.** With status `1`, exclude a Note marked
  `REVIEW NEEDED` after a correction and evaluate other current matches against
  today's setup. An unrelated malformed note can cause status `2` even when
  stdout includes a current reference. Set those results aside. If the helper
  cannot start because PyYAML is absent, record `unavailable`. In each case,
  continue with independent project evidence and the applicable domain checks.

## Write and review a note

Use Markdown with YAML front matter. Replace the example paths and digest with
an actual task, artifact, locator, and SHA-256 of the file bytes.

```markdown
---
id: GUIDE-VALIDATION-001
title: "Check whether a comparison supports a regression attribution"
status: draft
scope: [validation, regression]
sources:
  - task: ".aiwf/records/ai_20260101/001_example_task"
    artifact: "evidence/comparison.log"
    locator: "Failure summary, lines 20–32"
    sha256: "<actual 64-digit lowercase SHA-256>"
    reviewed_corrections: null
review_ref: null
---

## Recommended Checks

Compare the same test nodes and failure conditions against a known baseline.

## Applicability

Use when the compared revisions, test inputs, and dependencies are known.

## Inapplicable Cases

When fixtures or dependencies differ, establish a comparable baseline.

## Evidence and Limitations

The comparison covers only the recorded nodes and environment.

## Recheck Triggers

Recheck if the baseline, fixture, dependencies, or source corrections change.
```

The G0 headings `建議檢查`, `適用條件`, `不適用／不得據此推斷`,
`證據與限制`, and `重新檢查觸發條件` also work. Each section requires content.
`task` uses the full path beneath the configured records root. Paths in
`artifact` and `reviewed_corrections` are relative to that task directory.
`locator` is a human-readable pointer to the evidence.

`reviewed_corrections` records the entire observed task-local correction set.
Use `null` for an unknown baseline, `[]` for a confirmed empty set, or entries
with `path` and `sha256` for each known correction. Repeat the same baseline
for every source of the same task within a note. The helper uses the existing
formal reader for `corrections/` and supports the historical
`POST_FINALIZATION_CORRECTION.md` addendum. Unreadable or unrecognized entries
in these locations, including other task-root names containing
`correction`, `errata`, or `addendum`, result in an unknown snapshot.
Separate follow-up tasks must be cited explicitly.

Use the project's existing review to accept a version as `active`. Set
`review_ref` to the review record that identifies the accepted content, such
as a PR review with the reviewed revision and file path. The helper requires a
nonempty reference for active notes. Reviewers check that the reference still
covers the current version, including the source and correction baseline.
Use `withdrawn` to preserve a note for historical viewing.

## Read results

| Operation | Behavior |
| --- | --- |
| `check` | Checks structure, unique IDs, source paths and hashes, and correction baselines. |
| `show` or `show --scope TAG` | Shows matching active notes with intact sources. Reports the ID, title, and reasons for withheld active notes. |
| `show --id ID` | Shows a structurally valid note in full, with a notice for draft, withdrawn, or stale notes. |

| Exit status | Meaning |
| --- | --- |
| `0` | Successful query, including zero matches for a scope. Read the output to determine which notes matched. |
| `1` | One or more selected notes have sources that require review. The same output can include current notes whose sources match. |
| `2` | Global query error, including malformed notes, invalid paths or arguments, missing explicit IDs, or setup errors. Treat the query as failed even if its output includes apparently current notes. |

The helper checks note structure and uniqueness across the collection before
applying valid selectors. Query results and failures are independent of Task,
pre-edit Guard, and Finalize decisions.

Guidance is advisory. Current authorization and domain checks govern any
action. Queries leave task records, events, manifests, and notes intact.
Installing or upgrading the helper preserves the project-owned note directory.
Public AIWF exports include the helper and this guide and exclude private notes.
