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
- `diagnostic_code_ranking`: frequency ranking of diagnostics found in report scope

## Caveats
- `blocked_event_count` is MVP-defined as events with normalized `result.status == blocked`.
- `blocked_event_count` is not equal to all diagnostic blockers.
- `diagnostic_code_ranking` may include legacy tasks and mixed schema generations.
- `AIWF-FINALIZED-001` in rankings is a post-finalize mtime warning; it is not a finalize blocker by itself.
- Compare records by workflow version, event schema version, and whether tasks are event-backed.
- Event logs are evidence records, not tamper-proof audit logs.
- Report output is for analysis and triage, not workflow source of truth.

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
- domain automation work
- workflow tooling work

## Related References
- Diagnostic catalog: [diagnostics.md](diagnostics.md)
- Release baseline: [releases/v1.6.1.md](releases/v1.6.1.md)
- Package Records release preparation: [releases/package_records_release_preparation.md](releases/package_records_release_preparation.md)
