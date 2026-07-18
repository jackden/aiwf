# Repository Packaging Guidelines

## Purpose
This document defines packaging boundaries for AIWF-owned artifacts and review evidence.
AIWF no longer provides or owns a general root-level repository snapshot helper.

## Must Exclude
- `.env`
- API keys
- tokens
- local virtual environments
- cache directories
- `__pycache__`
- generated pycache
- temporary editor files

## Recommended Include
- source code
- tests
- docs
- AIWF task artifacts
- release notes
- analysis artifacts

## Review Bundle Boundary

`.aiwf/bin/package_review_bundle.sh` generates a task-scoped review bundle from AIWF workflow evidence.
It is not a general repository snapshot tool or a workflow-record analysis package exporter.

Root-level `scripts/` is project-owned.
AIWF installation, upgrade, relocation, and packaging operations must not create, overwrite, move, or assume ownership of files under `scripts/` unless the user explicitly requests a project-specific integration.

## Records Analysis Package Design

The design for a future workflow-record analysis package is documented in
[package_records_design.md](package_records_design.md).
That design is explicitly separate from review bundles, public tree export,
dataset export alone, and general repository snapshots.

Before package record discovery, the command validates `--from-date` and
`--to-date` (including the reversed-range case) and validates repeated
`--status`, `--workflow-phase`, and `--review-status` selectors against the
canonical, case-sensitive metadata values. Invalid input returns `2` without
creating output parents or replacing an existing `--force` target. Valid
selectors that match no records still produce a successful empty manifest.

The status line `Workflow Evidence Findings` reports workflow evidence findings
discovered during package construction; it does not claim that findings were
themselves packaged as a separate artifact. Manifest fields such as
`validation.findings` and `finding_count` retain their existing schema.

## Rationale
AIWF task artifacts are workflow evidence.
Environment secrets are not workflow evidence and must not be included in shared review packages.

## Public Tree Hash Policy

The deterministic public tree exporter uses `git-compatible-v1` as the canonical release-tree hash policy.

Canonical release-tree hash:

- emitted as `canonical_git_tree_sha256`
- also emitted through the legacy-compatible `tree_sha256` and `public_tree_tree_sha256.txt` names
- is an AIWF-defined SHA-256 over a deterministic, path-sorted manifest, not a native Git object ID
- must not be compared with `git rev-parse HEAD^{tree}`
- uses Git-compatible modes:
  - regular non-executable files: `100644`
  - regular executable files: `100755`
  - symbolic links: `120000`
- ignores local POSIX mode bits that Git cannot publish, such as `0644` versus `0664` or `0755` versus `0775`
- includes file path, file size, canonical Git mode, and file content SHA256

Each canonical manifest record is serialized as:

```text
<content_sha256>\t<git_mode>\t<size>\t<public_path>\n
```

Records are sorted by public path before hashing.

Content-only hash:

- emitted as `content_only_sha256`
- includes file path, file size, and file content SHA256
- is intended for comparing source exports, Git checkouts, GitHub ZIP archives, and GitHub TAR.GZ archives when archive extraction changes local filesystem modes

Each content-only record is serialized as:

```text
<content_sha256>\t<size>\t<public_path>\n
```

Filesystem diagnostic hash:

- emitted as `filesystem_diagnostic_sha256`
- includes local filesystem mode bits
- is for local debugging only
- must not be used as the cross-environment release identity

The `included_inventory.tsv` schema exposes both `git_mode` and `filesystem_mode`.
Consumers must use `git_mode` for release identity.

Mode `120000` is reserved by the hash policy for object-type completeness.
The current public exporter may still reject source symlinks under its separate public-tree safety policy.

Historical note:

The v1.7.8.post1 Task 005 staging hash `dad9ada7c639b676b4eb58bfef97e6d0eb3e399c05f02576f4c367eb95055473` is preserved as historical staging evidence.
It was computed before Git-compatible mode normalization and included local mode `0664` for `requirement.txt`.
The v1.7.8.post1 tag, GitHub Release, and public commit must not be retagged or rewritten for this evidence-policy correction.
