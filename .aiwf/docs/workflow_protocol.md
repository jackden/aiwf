# AI Workflow Protocol v1.7.9

This document is the canonical protocol semantics reference for repository-native AI workflow governance.

## Version Identity Policy (v1.7.14)

For the current lightweight, repository-native AIWF project, release identity and
tool provenance normally move together. The `v1.7.14` release advances the
workflow protocol from `1.7.8` to `1.7.9` because review closure now has
structured decision-authority semantics. This does not introduce a package
manager, database migration framework, or silent overwrite of workflow
evidence.

Current version state:
- release version: `1.7.14`
- tool version: `1.7.14`
- workflow protocol version: `1.7.9`

Semantics carried by this release:
- deterministic review decision-authority validation in finalize readiness
- derived workflow evidence diagnostics exposed through `doctor` and `report`

The existing metadata schema `ai-workflow-v1.7` and event schema
`aiwf-event-v0.3` are unchanged by this release; no schema migration is
introduced here.

The derived diagnostics are observational. They do not add a finalize blocker,
validation disposition, workflow phase, reliability score, or second source of
workflow truth.

Version-separation strategy may be revisited only if AIWF later requires:
- external compatibility guarantees
- schema compatibility negotiation
- independent runtime/protocol release channels

## 1. System Scope

The workflow system is split into three layers:

| Layer | Responsibility |
|---|---|
| Governance rules (`AGENTS.md`, `.aiwf/docs/agent_rules/*`) | Policy, safety boundaries, engineering invariants, repository conventions |
| Deterministic workflow layer (`./aiwf` entrypoint, `.aiwf/bin/ai_workflow.py` runtime) | Allocation, metadata validation, diagnostics, finalize enforcement, export/list/inspection; stable interpreter selection for wrapper execution |
| LLM runtime | Implementation, editing, documentation authoring |

Out of scope:

- orchestration runtime
- DAG/state engine
- background daemon
- MCP execution runtime
- database backend
- scheduler
- CI/PR integration

## 2. Metadata Semantics

Core metadata semantics:

- `status`: task lifecycle state (draft/active/review/blocked/done/archived)
- `workflow_phase`: coarse stage (`init`, `implementation`, `validation`, `review`, `finalized`)
- `review_status`: review outcome (`pending`, `pass`, `fail`, `not_required`)
- `required_review_authority`: authority required for final review closure
  (`human` or `ai-agent`); new v1.7 tasks default to `human`
- `finalized_at`: RFC3339 UTC timestamp written by tooling on first successful finalize
- `finalized_by`: finalize actor identifier written by tooling (`tool`)

Protocol rules:

- `status: done` must be compatible with `review_status` and `workflow_phase` checks.
- `finalized_at` and `finalized_by` are nullable before finalize for v1.5 tasks.
- LLM/manual prose is not workflow truth; metadata and deterministic commands are workflow truth.

### Review decision authority

Review closure uses three separate structured values:

- `required_review_authority` is the task policy recorded in v1.7 metadata.
- `decision_authority` is the authority asserted to have made the review
  decision. A final `pass` must match the task requirement; a
  `not_required` result uses `not_required` as its decision value.
- `recorded_by` is the actor that writes the review evidence event.

`reviewer` remains a workflow role and is not a substitute for either authority
field. Likewise, an agent capability or model identity is not a decision
authority. `recorded_by` may differ from `decision_authority`; for example, an
agent may record a human decision that was supplied through an accountable
workflow.

When a task requires a specific review authority, the latest applicable final
review decision MUST carry a valid decision authority that satisfies the
required review authority before the task can become finalize-ready. The actor
or tool recording the decision is evidence provenance and MUST NOT be treated
as equivalent to the decision authority.

For v1.7 records, review evidence written by `record` must contain the
structured authority fields. `check --finalize-ready` and `finalize` validate
the latest final review, including the required-authority snapshot in the event,
the decision authority, and a non-empty recording actor. This validates the
workflow authority assertion and evidence consistency; it does not authenticate
that a real human performed the review and is not cryptographic approval.

The existing `not_required` reason requirement remains in force. Older active
records that explicitly require human review cannot close through a missing
authority field. Older finalized records remain readable and are not
retroactively invalidated solely by the current authority semantics.

For active v1.2–v1.6 records, explicit required authority is honored; when
absent, `reviewer: human` supplies the compatibility requirement. Recording a
review preserves that inferred policy before updating the reviewer role.
Pre-v1.6 records receive authority checks without adopting v1.6 validation or
correction-loop gates.

## 2.1 Tool-Owned Task Metadata

Task front matter is tool-owned workflow metadata.
Agents may propose task intent, title, scope, related task IDs, tags, and related files, but the final front matter representation must be generated or validated by AIWF tooling.
Agents must not manually rewrite canonical metadata fields such as `task_id`, `task_name`, `created_at`, `updated_at`, `related_tasks`, `blocked_by`, `supersedes`, `workflow_phase`, `finalized_at`, or `finalized_by`.
This rule does not make AIWF a workflow orchestrator or business completion engine. It only preserves deterministic workflow metadata integrity.

## 2.2 Records Root Layout Resolution

AIWF supports layout-aware records root discovery via `.aiwf/config.yaml`.

Canonical v2 layout:
```yaml
aiwf_layout_version: 2
docs_root: ".aiwf/docs"
record_root: ".aiwf/records"
event_log: ".aiwf/events/events.jsonl"
legacy_enabled: true
```

Legacy v1 compatibility:
```yaml
layout:
  records_root: <repo-relative-directory>
```

Rules:
- If config is missing, records root defaults to `docs` for compatibility.
- In this repository, committed config points records root at `.aiwf/records` and docs root at `.aiwf/docs`.
- Task day directories resolve under `<record_root>/ai_YYYYMMDD/`.
- Runtime write safety remains fail-closed and only permits writes under `.aiwf/` plus legacy knowledge-path compatibility during migration.
- `./aiwf` is the stable repository-local command entrypoint.
- `.aiwf/bin/ai_workflow.py` is the canonical runtime.
- Project-level `docs/`, `tools/`, and `scripts/` directories are project-owned.
- When a legacy project-level `tools/ai_workflow.py` exists, AIWF preserves it unchanged, does not treat it as a supported public entrypoint, and does not use it as a relocation source.
- Legacy root `docs/` migration is explicit opt-in and must be used only after reviewing project ownership.

Legacy relocation conflict handling:
- A relocation plan classifies each selected entry as `source_missing`, `relocatable`, `already_relocated`, or `conflict`.
- When both a legacy source and canonical destination exist, `relocate --apply` and `upgrade --apply --migrate-legacy-docs` fail closed before mutation with `AIWF-RELOCATE-CONFLICT-001` and return code `2`.
- Conflict handling does not overwrite, merge, delete, or publish a successful migration/upgrade report. `--check` and `--dry-run` expose the same blocker without changing files.
- This is runtime integrity behavior; it does not change event schema, workflow phases, or finalize semantics.

## 2.3 AI Agent Metadata Attribution

AIWF tracks operator-facing AI attribution metadata through:

- `tool`
- `provider`
- `model_name`
- `reasoning_effort`
- `source`
- `confidence`

Operator reference rules:

- `./aiwf metadata allowed-values` is the canonical CLI reference for defaults, descriptions, and allow-listed values.
- `provider`, `tool`, `reasoning_effort`, `source`, and `confidence` use allow-lists.
- `model_name` remains free text because model identifiers churn quickly.
- `metadata init` uses neutral defaults (`unknown` plus `explicit_env` / `medium`) rather than inferring a provider/tool choice.
- `metadata profile create` writes profile-backed metadata (`source=profile`) while preserving any already known tool/provider/model values it can safely reuse.
- `metadata profile show [name]` shows stored profile metadata and runtime options for the current or specified profile.
- `metadata show` shows effective metadata plus source layer/path for each field.
- `metadata status` shows profile, local override, shell override, runtime options, effective metadata, and resolution summary.
- `AIWF_EVENT_LOG` is a runtime option, not an AI attribution metadata field.

Task front matter uses workflow role fields:

- `owner` and `reviewer` are workflow roles, not tool/provider/model provenance.
- New task metadata should default to `owner: "ai-agent"` and `reviewer: "human"`.
- Actual tool, provider, model, and reasoning profile belong in AIWF metadata/env profiles or `.aiwf/events/events.jsonl` provenance.
- Historical records may still contain older values such as `owner: "codex"`; these remain compatible and are not migrated retroactively.

## 2.4 Task ID lookup and new-task preflight

Task ID lookup is read-only. `next-id` and the internal `next_task_id()` helper only inspect an existing AI date directory; a missing directory returns `001` without creating a directory, index entry, event, report, or task artifact. An existing date path that is not a directory fails closed with `AIWF-TASK-ID-001`.

`new-task` validates all deterministic inputs before allocating an AI date directory or task directory. This includes date policy, normalized name, priority/risk, project normalization, task references, tags, and related files. Duplicate normalized names and the create-only `--update-existing` gate are also rejected before allocation. Invalid input returns `2` without leaving a date directory, task artifacts, index entry, event, report, or partial file. Valid task creation retains the existing max-plus-one ID allocation and artifact/index behavior.

This boundary is intentionally limited to single-process ordering; it does not introduce locks, reservations, transaction directories, or a new rollback subsystem.

## 2.5 Dataset output boundary

`dataset export --output <path>` writes analytical output only to a repository-local
relative or absolute path outside the active configured records root. The records
root is reserved for workflow records and evidence; dataset output belongs in a
project-owned location such as `artifacts/`, `reports/`, or an experiment output
directory.

The runtime resolves both the repository root and output target before writing,
then rejects any target resolved anywhere under the configured records root,
including nested paths, final symlinks, and symlinked parent directories. Absolute
paths outside the repository remain rejected, and sibling names such as
`.aiwf/records-export/` are not treated as the records root. Rejection returns
code `2` before dataset collection, parent-directory creation, serialization, or
output mutation, with diagnostic `AIWF-DATASET-OUTPUT-001` for the records-root
boundary.

This is an output placement boundary only. It does not change dataset schema,
selection semantics, event semantics, workflow phases, or finalize behavior, and
does not introduce an output override or generic output-management framework.

## 2.6 Identity-aware additive backfill

Backfill is additive, identity-aware, and fail-closed. Each backfill source is represented by a deterministic `backfill_source.json` containing the normalized source path, source date, source task ID when available, and normalized source task name. The artifact is provenance evidence and does not change the workflow protocol schema.

Re-running backfill for the same source identity is an idempotent no-op when the selected and execution targets are complete. It returns `0`, does not create another task, and does not rewrite artifacts, indexes, or events. A same-name different-identity target returns `2` with `AIWF-BACKFILL-IDENTITY-001`; multiple same-name candidates return `2` without automatic canonical selection.

`backfill --update-existing` may create missing backfill artifacts only when provenance matches. Existing `task.md`, `agent.md`, `task_record.md`, validation/review evidence, provenance, index entries, and finalized records are never overwritten. Incomplete matching targets fail closed without the flag; incomplete finalized targets remain protected even with it. Backfill does not merge, rename, repair, discard, or select historical records.

## 3. Finalize Semantics

`./aiwf finalize --path <task_dir>` is the workflow completion authority.

First successful finalize:

- validates deterministic blockers
- mutates metadata:
  - `status: done`
  - `workflow_phase: finalized`
  - `finalized_at: <timestamp>`
  - `finalized_by: tool`
  - `updated_at: <date>`

Idempotency:

- If task is already finalized (`status: done`, `workflow_phase: finalized`, non-empty `finalized_at`), finalize is a deterministic no-op.
- Second finalize must not rewrite metadata and must not change timestamps.

Dry-run:

- `finalize --dry-run` is a repository read-only operation. It validates and previews mutations without writing task artifacts, metadata, indexes, reports, or either repository/task-local event log.
- A dry-run evaluates the same blockers as the mutating command, prints the projected result, and may print a read-only notice; the observation is not workflow evidence and does not produce a closure event.
- For already finalized tasks, dry-run reports no-op preview.

Closure hardening:

- finalized tasks reject new evidence records from `record`.
- if `finalize_success` exists, post-finalize evidence-changing events are treated as a closure violation.
- `check --finalize-ready` runs finalize-level diagnostics in read-only mode for CI/agent gates. It does not modify task artifacts, metadata, indexes, reports, or either event log, and its readiness result is not closure evidence.
- `check --finalize-ready` validates closure evidence hygiene, including pending validation/review residue, default template residue in required artifacts, and acceptance-criteria closure-decision states.
- For v1.7 tasks, finalize readiness also requires the latest final review's
  structured `required_review_authority`, `decision_authority`, and non-empty
  `recorded_by`; the decision authority must satisfy the task policy.
- This authority gate checks declared workflow evidence consistency, not human
  identity authenticity. It preserves the distinction between capability,
  authority, and the actor that records evidence.
- Read-only preflight paths must bypass the event writer entirely, including when internal `AIWF_EVENT_LOG=1` is enabled. The current parser exposes no explicit event-logging option to combine with these modes.
- A successful normal finalize may append phase/finalize evidence only after the metadata and index mutation succeeds. Failed finalize paths must not emit `finalize_success`.
- v1.6 remains evidence-driven; strict phase-gated finalize is not enforced as
  `workflow_phase == review`. v1.7 adds structured review authority without
  adding a phase.
- finalized required artifacts (`task.md`, `task_record.md`, `self_validation.md`, `review_agent.md`, `review_final.md`) are governance-controlled evidence after finalize.
- `review_agent.md` is the canonical AI/agent review artifact for new tasks.
- `review_codex.md` is a legacy alias retained for backward compatibility with existing records.
- AIWF does not provide tamper-proof storage or physical immutability guarantees for finalized artifacts.
- AIWF guarantees deterministic post-finalize drift handling: detect, diagnose, repair, preserve evidence.
- follow-up tasks must not silently rewrite finalized evidence.

Post-finalization correction projection (`v1.7.12.post1` internal source
stamp):

- `correct-finalized --path <task_dir>` creates an additive correction artifact
  only when the target task is finalized.
- Correction artifacts live under `<task_dir>/corrections/` and are generated
  with `schema_version: aiwf-correction-v1`; their numeric IDs are allocated
  deterministically from existing correction artifacts.
- The first implementation accepts only explicit `human_*` authority values
  and records `created_by: human`; agent-proposed or automated corrections are
  fail-closed rather than treated as authoritative.
- Supported correction types are `implementation_reverted`,
  `scope_reclassified`, `conclusion_corrected`, `evidence_superseded`, and
  `current_state_clarification`.
- A correction preserves the original task metadata, required artifacts,
  index, finalize event, and finalize manifest. It is not appended as a
  post-finalize validation/review/fix event.
- `inspect --path <task_dir>` is the deterministic current-state projection:
  it reports historical workflow state, whether closure evidence remains
  preserved, the latest correction, and the latest current effective state.
- `finalize` remains idempotent after a correction; corrections do not reopen
  the task or change its historical closure state.

Post-finalize correction policy (errata workflow):

- If interpretation/staleness issues are found after finalize, create a follow-up errata task.
- Errata task must reference original task path, file, and relevant section.
- Record corrected interpretation in errata artifacts while keeping finalized original artifacts unchanged.
- Allowed in follow-up task: new evidence, new interpretation, errata, supersede discussion.
- Not allowed in follow-up task: editing finalized `review_final.md`, `self_validation.md`, `task_record.md`, or finalized manifest evidence files.
- For `AIWF-PATH-015`, revert post-finalize edits, or use a controlled amend/reopen command if supported.
- Do not silently edit finalized task artifacts as a repair path.
- For finalized artifact drift repair:
  - open a dedicated repair task
  - document drift scope and diagnosis
  - restore consistency with auditable commands/actions
  - validate repaired state (`check --finalize-ready`) and record results
  - Controlled amend/reopen runtime semantics remain future work (v1.9+) and are not part of v1.7.14 behavior.

Pre-edit guard:

- `./aiwf guard --pre-edit --path <task_dir>` checks that a task directory exists, required task artifacts are present, `task.md` metadata parses, and the task is still open.
- exit code `0` means pass, `1` means invalid invocation, and `2` means guard block.
- `AIWF-GUARD-PASS`, `AIWF-GUARD-001`, `AIWF-GUARD-002`, `AIWF-GUARD-003`, `AIWF-GUARD-004`, and `AIWF-GUARD-900` are the stable diagnostic codes for this guard.
- missing task-local `.aiwf/events.jsonl` does not block the guard; malformed event logs may emit a warning but remain non-blocking for this command.
- v1.7.0 is the pre-edit governance MVP and task-level guard boundary; it does not yet imply repo-level workflow enforcement.
- guard command scope is pre-edit governance only; it is not closure authority and does not replace `check --finalize-ready`, validation evidence, review, or `finalize`.
- `finalize` remains the closure authority.

## 4. Diagnostics Semantics

Diagnostics use stable `AIWF-*` codes with severity:

- `info`
- `warn`
- `error`

Output format is deterministic and actionable:

- code
- message
- suggested fix (for warn/error when available)

Recovery philosophy:

- deterministic failures should provide concrete, local fixes
- warnings should preserve workflow continuity while surfacing risk
- closure-evidence diagnostics validate workflow readiness, not business-completion truth
- AIWF may require each acceptance-criteria item to have a closure decision, but it does not decide whether the underlying business claim is true

### 4.1 Derived evidence diagnostics

`doctor` and `report` may expose a derived workflow-evidence view calculated
from task-local events and the global event projection. It may summarize
validation pass/fail counts, review-fix-revalidation correction loops, review
freshness, authority consistency, local/global projection discrepancies,
schema compatibility, metadata/latest-review status consistency, and last
activity age. A `review_pass_but_nonfinal` flag
means that a final review pass exists while metadata is not finalized; it is an
observation, not a failure.

Derived output is deterministic and read-only with respect to workflow state.
It must not create a reliability score, classify a validation failure's cause or
disposition, add a finalize blocker, add a phase, rewrite historical events, or
create a second source of truth. `check --finalize-ready` and `finalize` use
their existing policy diagnostics; Task 002 derived warnings are not included
in that gate.

## 5. Compatibility Policy

Supported compatibility tiers:

- `legacy` (no metadata front matter)
- `ai-workflow-v1.2`
- `ai-workflow-v1.3`
- `ai-workflow-v1.4`
- `ai-workflow-v1.5`
- `ai-workflow-v1.6`
- `ai-workflow-v1.7`

Compatibility expectations:

- legacy tasks remain readable and exportable
- newer validation rules should not require mass migration for historical records
- exporter/checker must continue best-effort handling for older metadata versions
- v1.6 adds event-backed lifecycle evidence, finalize-readiness path checks, review/validation ordering checks, and post-finalize evidence warnings
- v1.7 adds `required_review_authority` task metadata and structured review
  authority evidence; older finalized records remain readable without forced
  migration
- v1.7.0 adds task-level pre-edit guard semantics without changing finalize authority

## 6. Governance vs Enforcement Split

| Component | Role |
|---|---|
| Rules docs | Governance intent and invariants |
| `./aiwf` + `.aiwf/bin/ai_workflow.py` | Deterministic enforcement |
| LLM agent | Implementation behavior |

This split is intentionally lightweight and repository-native.

## 7. Knowledge Boundary and Source Hierarchy

AIWF knowledge artifacts are documentation aids. They do not add runtime behavior, do not change workflow semantics, and do not participate in finalize gating unless a future protocol version explicitly says so.

Knowledge layers:

| Layer | Path | Semantics |
|---|---|---|
| Workflow evidence | `.aiwf/records/ai_YYYYMMDD/*` | Primary workflow execution records, task lifecycle artifacts, validation/review/finalize evidence, and task-local `.aiwf/events.jsonl`. |
| Reusable engineering knowledge | `.aiwf/docs/knowledge/*` | Operational knowledge derived from tasks: reusable patterns, repeatable bugs and mitigations, and engineering or governance decisions. |
| Derived analysis | `knowledge/analysis/*` | Cross-task analysis, trend analysis, workflow interpretation, and comparative studies. |
| Public narrative | `knowledge/articles/*` | LinkedIn articles, README strategy, public engineering narratives, and external communication material. |

Boundary rules:

- Workflow evidence is the primary source for workflow execution history.
- Reusable engineering knowledge is derived from tasks, but is not itself workflow execution evidence.
- Derived analysis is interpretation and must not override workflow evidence.
- Public narrative material must not be treated as protocol or runtime source of truth.
- Knowledge artifacts must not change finalize behavior, event schema, artifact manifest behavior, or task structure.

Source precedence:

```text
runtime code
  > protocol/design docs
  > release notes
  > workflow execution records
  > reusable engineering knowledge
  > derived analysis
  > public narrative material
```

`review_final.md` may include a lightweight, optional knowledge extraction section with pattern, bug, decision, and suggested artifact path candidates. This section is advisory only, non-blocking, and not part of `check --finalize-ready` or `finalize` semantics.

## 8. Task Naming Reviewability Guidance

Task creation identity enforcement:

- `new-task` is create-only; `--update-existing` is rejected before any file write.
- Within one `ai_YYYYMMDD` directory, normalized task names are unique.
- New-task checks for an existing normalized name before allocating an ID and reports the exact existing task path on failure.
- `check`, `doctor`, and `finalize` report same-date duplicate normalized names as blockers.

For future task naming, avoid duplicated numeric prefixes when possible to reduce reviewer confusion.

- Prefer: `005_aiwf_v1_7_0_post_merge_baseline_review`
- Avoid: `001_005_aiwf_v1_7_0_post_merge_baseline_review`

Existing finalized task paths should not be renamed only for cosmetic cleanup.

## 9. Event Logging v0.1 / v0.2 / v0.3

AIWF may optionally record task-local workflow events under:
`<task_dir>/.aiwf/events.jsonl`

Event logging is controlled by `.env` / environment variables.

The event log is an append-only raw data source for reliability experiments and lightweight workflow audit. It is not workflow authority and is not a tamper-proof ledger. Workflow authority remains metadata validation, diagnostics, and finalize semantics. For derived projection checks, the task-local event log is the task evidence stream and `.aiwf/events/events.jsonl` is its global projection; discrepancies are reported and are not automatically repaired.

Optional command-event logging must not change finalize behavior. Evidence
events are themselves consumed by the existing v1.6+ finalize path.

Schema compatibility:

- command events remain readable in `aiwf-event-v0.1`.
- newly recorded evidence events use normalized `aiwf-event-v0.3` with:
  - `event_type` / `event_group`
  - `result.status`
  - `payload`
  - task/model/context fields for dataset analysis.
  - review authority fields when the event records a review:
    `required_review_authority`, `decision_authority`, and `recorded_by`.
- `aiwf-event-v0.1` command events and `aiwf-event-v0.2` normalized evidence
  remain readable. Historical event rows are not rewritten or migrated by
  this release.
- legacy evidence events using `event` + string `result` remain readable.

`export-experiment` summarizes task event logs for experiment analysis.

`report` provides repository/task summaries in JSON or Markdown for dataset readiness analysis.
Report outputs are analysis artifacts and not source-of-truth completion state.
