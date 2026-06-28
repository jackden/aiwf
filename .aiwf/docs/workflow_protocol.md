# AI Workflow Protocol v1.7.8

This document is the canonical protocol semantics reference for repository-native AI workflow governance.

## Version Identity Policy (v1.7.8.post1)

For the current lightweight, repository-native AIWF project, release identity and tool provenance normally move together.
The `v1.7.8.post1` public baseline patch advances release/tool identity while preserving workflow protocol semantics at `v1.7.8`.
This does not introduce a package manager, database migration framework, or silent overwrite of workflow evidence.

Current version state:
- release version: `1.7.8.post1`
- tool version: `1.7.8.post1`
- workflow protocol version: `1.7.8`

This patch identity is a public packaging and documentation decision. The upgrade mechanism is additive and does not by itself imply event schema, finalize gate, or diagnostic behavior changes.

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
- `finalized_at`: RFC3339 UTC timestamp written by tooling on first successful finalize
- `finalized_by`: finalize actor identifier written by tooling (`tool`)

Protocol rules:

- `status: done` must be compatible with `review_status` and `workflow_phase` checks.
- `finalized_at` and `finalized_by` are nullable before finalize for v1.5 tasks.
- LLM/manual prose is not workflow truth; metadata and deterministic commands are workflow truth.

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

- `finalize --dry-run` validates and previews mutations without writing files.
- For already finalized tasks, dry-run reports no-op preview.

Closure hardening:

- finalized tasks reject new evidence records from `record`.
- if `finalize_success` exists, post-finalize evidence-changing events are treated as a closure violation.
- `check --finalize-ready` runs finalize-level diagnostics in read-only mode for CI/agent gates.
- `check --finalize-ready` validates closure evidence hygiene, including pending validation/review residue, default template residue in required artifacts, and acceptance-criteria closure-decision states.
- v1.6.1 remains evidence-driven; strict phase-gated finalize is deferred and not enforced as `workflow_phase == review`.
- finalized required artifacts (`task.md`, `task_record.md`, `self_validation.md`, `review_codex.md`, `review_final.md`) are governance-controlled evidence after finalize.
- AIWF does not provide tamper-proof storage or physical immutability guarantees for finalized artifacts.
- AIWF guarantees deterministic post-finalize drift handling: detect, diagnose, repair, preserve evidence.
- follow-up tasks must not silently rewrite finalized evidence.

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
- Controlled amend/reopen runtime semantics are future work (v1.8+) and are not part of v1.7.1 patch behavior.

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

## 5. Compatibility Policy

Supported compatibility tiers:

- `legacy` (no metadata front matter)
- `ai-workflow-v1.2`
- `ai-workflow-v1.3`
- `ai-workflow-v1.4`
- `ai-workflow-v1.5`
- `ai-workflow-v1.6`

Compatibility expectations:

- legacy tasks remain readable and exportable
- newer validation rules should not require mass migration for historical records
- exporter/checker must continue best-effort handling for older metadata versions
- v1.6 adds event-backed lifecycle evidence, finalize-readiness path checks, review/validation ordering checks, and post-finalize evidence warnings
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

For future task naming, avoid duplicated numeric prefixes when possible to reduce reviewer confusion.

- Prefer: `005_aiwf_v1_7_0_post_merge_baseline_review`
- Avoid: `001_005_aiwf_v1_7_0_post_merge_baseline_review`

Existing finalized task paths should not be renamed only for cosmetic cleanup.

## 9. Event Logging v0.1 / v0.2

AIWF may optionally record task-local workflow events under:
`<task_dir>/.aiwf/events.jsonl`

Event logging is controlled by `.env` / environment variables.

The event log is an append-only raw data source for reliability experiments and lightweight workflow audit. It is not workflow authority and is not a tamper-proof ledger. Workflow authority remains metadata validation, diagnostics, and finalize semantics.

Event logging must not change finalize behavior.

Schema compatibility:

- command events remain readable in `aiwf-event-v0.1`.
- newly recorded evidence events use normalized `aiwf-event-v0.2` with:
  - `event_type` / `event_group`
  - `result.status`
  - `payload`
  - task/model/context fields for dataset analysis.
- legacy evidence events using `event` + string `result` remain readable.

`export-experiment` summarizes task event logs for experiment analysis.

`report` provides repository/task summaries in JSON or Markdown for dataset readiness analysis.
Report outputs are analysis artifacts and not source-of-truth completion state.
