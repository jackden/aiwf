# AIWF Reporting Guide

## Commands
```bash
./aiwf report --path .aiwf/records --format json
./aiwf report --path .aiwf/records --format markdown
```

## Package Records

Use Package Records when workflow execution records and related workflow
evidence need to leave the repository for analysis or engineering handoff:

```bash
./aiwf package records --output records.zip
```

Package Records produces an analysis package with a manifest, inventories,
copied workflow records, events, optional dataset output, redaction metadata,
and integrity metadata. It does not export the source repository.

## Metrics
- `task_count`: total discovered tasks
- `event_backed_task_count`: tasks with readable event evidence
- `finalized_count`: finalized tasks
- `draft_count`: draft tasks
- `review_count`: tasks currently in review status/phase buckets
- `total_event_count`: total parsed events across tasks
- `malformed_event_count`: event rows that cannot be normalized
- `blocked_event_count`: count of events whose normalized `result.status == blocked`
- `post_finalize_event_count`: events detected after closure boundary
- `derived_status_counts`: counts of deterministic evidence-derived task states
- `derived_diagnostic_count`: non-blocking derived warning count
- `derived_diagnostic_task_count`: tasks with at least one derived warning
- `diagnostic_code_ranking`: frequency ranking of diagnostics found in report scope

Each task entry also contains `derived_status`, `derived_evidence`, and
`derived_diagnostic_codes`. The evidence view includes validation pass/fail
counts, review correction-loop counts, review freshness, final-review authority
consistency, metadata/latest-review status consistency, local/global event
projection consistency, known/unknown event schema compatibility, and last
activity timestamp/age.

Authority consistency uses the same structured-evidence validator as closure
checks, including the event's required-authority snapshot. Projection equality
compares complete parsed JSON events, preserving schema, provenance, result
details and extension fields; only object key order and JSON whitespace are
ignored.

## Caveats
- `blocked_event_count` is MVP-defined as events with normalized `result.status == blocked`.
- `blocked_event_count` is not equal to all diagnostic blockers.
- `diagnostic_code_ranking` may include legacy tasks and mixed schema generations.
- `AIWF-FINALIZED-001` in rankings is a post-finalize mtime warning; it is not a finalize blocker by itself.
- Compare records by workflow version, event schema version, and whether tasks are event-backed.
- Event logs are evidence records, not tamper-proof audit logs.
- Report output is for analysis and triage, not workflow source of truth.
- Derived warnings are observational only. They do not block
  `check --finalize-ready` or `finalize`, add a workflow phase, classify a
  validation failure disposition, or form a reliability score.
- Task-local events are the task evidence stream; `.aiwf/events/events.jsonl`
  is the global projection. Projection discrepancies are reported without
  historical rewrite.

Workflow source of truth remains:
- `task.md` metadata
- deterministic diagnostics (`check`/`doctor`)
- `finalize` closure semantics

## Recommended Analysis Splits
When analyzing output, split data by:
- legacy task
- non-event-backed task
- event-backed task
- `aiwf-event-v0.1`
- `aiwf-event-v0.2`
- `aiwf-event-v0.3`
- `aiwf-event-v0.4`
- actor identity evidence class (separate from configured model names)
- domain automation work
- workflow tooling work

## Related References
- Diagnostic catalog: [diagnostics.md](diagnostics.md)
- Release baseline: [releases/v1.7.15.md](releases/v1.7.15.md)
- Package Records release preparation: [releases/package_records_release_preparation.md](releases/package_records_release_preparation.md)

## Dataset Actor Identity Normalization

```bash
./aiwf dataset export --output artifacts/workflow_dataset.json
```

Dataset version `2` includes a per-task `actor_identity_evidence` list, retaining
identity provenance separately for every source event. New observations retain
their source/method and classify as `runtime_observed`, `host_observed`,
`self_reported`, `unknown`, or `conflicting`. Legacy `ai_agent` and model metadata
classify as `configured_legacy`, with unverified execution attribution.
Configured legacy hints never become observations, and equal model names never
merge evidence classes. Mixed historical/new events can coexist in one dataset.

Dataset output is derived; exporting does not modify source tasks, events, or
finalized manifests. Identity diagnostics remain non-blocking for closure.
For model comparisons, failure rates, or compliance analysis, use the
[Model Workflow Analysis Guide](model_workflow_analysis.md).
