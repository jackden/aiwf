# AIWF Package Records Release Preparation

## Release Preparation Status

This document prepares release-facing documentation for the completed Package
Records v1 capability. It is not a release publication record and does not
create a tag.

## Capability Summary

`./aiwf package records` packages AIWF workflow execution records and related
workflow evidence for analysis and engineering handoff.

The package includes:

- deterministic workflow evidence package identity
- `package_manifest.json`
- package summary
- task, event, and artifact inventories
- copied workflow records
- canonical event packaging
- dataset integration
- redaction profiles
- dry-run manifest generation
- ZIP and directory output
- integrity metadata

The command is for workflow evidence portability. It does not export the source
repository and is not a repository backup or tamper-proof audit ledger.

## Major Additions

- Deterministic package identity for packaged workflow evidence.
- Manifest schema validation for package metadata.
- Task, event, and artifact inventories.
- Canonical task-local and associated global event packaging.
- Dataset metadata and dataset payload integration.
- Safe, internal, and none redaction profiles.
- Fail-closed handling for secret findings.
- Dry-run manifest output for review before writing packages.
- ZIP and directory package output.
- Package summary and integrity metadata.
- Qualification and dogfooding evidence completed before this release
  preparation task.
- Validation result wording clarified so package generation status is separate
  from historical workflow evidence findings.

## Upgrade Notes

Package Records is optional. Existing AIWF repositories do not need migration to
continue using task creation, validation, review, or finalize workflows.

This capability does not change:

- workflow protocol semantics
- task front matter schema
- event schema
- finalize behavior
- upgrade relocation behavior

## Final Human Release Decision

Selected release: `v1.7.9`

Reason: The completed Package Records feature set adds a user-visible workflow
evidence portability capability without changing workflow protocol semantics,
event schema, finalize behavior, or existing task lifecycle behavior.

The earlier `v1.8.0` recommendation remains useful historical context because
Package Records is a first-class capability. The human release decision for this
series is `v1.7.9`, reserving minor version changes for workflow semantic
changes.

## Compatibility Boundary

- No required migration.
- No automatic rewrite of existing records.
- No source repository export.
- No release tag or GitHub Release is created by this preparation task.
- No runtime behavior is introduced by this documentation task.

## CLI Help Review

Current CLI help exposes `package records` as the command for packaging AIWF
workflow records. This release preparation keeps runtime help unchanged to
preserve the no-runtime-change boundary. User-facing documentation now states
the intended wording explicitly:

```text
Package AIWF workflow execution records and related workflow evidence for
analysis and engineering handoff. This command does not export the repository.
```
