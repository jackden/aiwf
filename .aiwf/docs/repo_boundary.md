# Repository Boundary: AIWF Core vs Domain Engineering Content

## Purpose
Define what belongs to AIWF core governance semantics versus project/domain engineering context.
AIWF should remain repository-native and domain-agnostic.

## AIWF Core Governance Semantics
AIWF core governance includes:
- command entrypoint identity (`./aiwf`) and runtime implementation (`.aiwf/bin/ai_workflow.py`)
- committed `.aiwf/` documentation, templates, config, records, events, and migration reports
- deterministic runtime behavior and diagnostics
- workflow protocol and metadata semantics
- agent governance rules and completion gate policy
- readiness checks and finalize gate behavior
- workflow execution record structure:
  - date/task directory layout (`ai_YYYYMMDD/NNN_task_name`)
  - task-local `.aiwf/events.jsonl` path semantics
  - machine-readable evidence artifacts

AIWF core behavior must not depend on any specific product, test framework, or infrastructure domain.

## Domain-Specific Engineering Content
Domain-specific content includes:
- RAID/storage development and automation logic
- backend/frontend implementation details
- product-specific workflows and validation commands
- infrastructure-specific safety constraints
- project-specific testing and release process details
- project-level `docs/`, `tools/`, and `scripts/` directories unless explicitly placed under `.aiwf/`

These are valid engineering context, but they are not AIWF core semantics.

## Public Namespace Boundary

AIWF owns only:

- the root `./aiwf` entrypoint
- the `.aiwf/` namespace

AIWF does not require, copy, move, delete, or rewrite project-level `docs/`, `tools/`, or `scripts/` as part of the public runtime boundary.
If an older repository contains a project-level `tools/ai_workflow.py`, treat it as a project-owned legacy file; use `./aiwf` for new public usage and remove the legacy file manually only after confirming no external caller depends on it.

## Evidence Boundary Principle
Task content is context, not direct workflow evidence.

Workflow evidence comes from AIWF task records and task-local event logs. Domain complexity or project difficulty does not by itself prove workflow correctness.

## Adoption Guidance
When adopting AIWF in another repository:
- keep AIWF core files and protocol/rule docs intact
- define domain safety rules separately for that repository
- avoid binding AIWF semantics to product-specific assumptions
