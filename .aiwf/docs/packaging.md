# Repository Packaging Guidelines

## Purpose
This document defines what should and should not be included when sharing AIWF repository snapshots for review.

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

## Rationale
AIWF task artifacts are workflow evidence.
Environment secrets are not workflow evidence and must not be included in shared review packages.

The official packaging script (`scripts/package_aiwf_repo.sh`) enforces this shared snapshot exclusion policy.
