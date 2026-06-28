# Agent Rule Index

Governance entrypoint for this repository.

## Rule Discovery

| Task Type | Required Rule Files | Notes |
|---|---|---|
| Any non-trivial repository change | `01_core_rules.md`, `02_ai_workflow.md`, `03_review_fix_loop.md` | Includes code, tests, safety logic, workflow docs, or shared helpers. |
| Testcase migration | `01_core_rules.md`, `03_review_fix_loop.md`, `04_test_safety.md` | Includes Gate-0 style intent/risk analysis. |
| RAID helper / selector / storage selection change | `03_review_fix_loop.md`, `04_test_safety.md`, `05_storage_safety.md` | Verify contract enforcement, not only parameter forwarding. |
| Disk cleanup / destructive storage logic | `04_test_safety.md`, `05_storage_safety.md` | Must fail closed when source resolution is uncertain. |
| Root AGENTS.md bootstrap entrypoint | `00_root_entrypoint.md` | Thin managed block at repo root; canonical rules live under `.aiwf/docs/agent_rules/` and protocol behavior lives in `.aiwf/docs/workflow_protocol.md`. |
| AI work record / workflow tooling | `02_ai_workflow.md` | `.aiwf/bin/ai_workflow.py` is the canonical runtime; `./aiwf` is the stable entrypoint; project-level `tools/` is project-owned legacy space. |
| Backfill request | `06_backfill_workflow.md` | Scope only to the user-specified path. |
| Code review only | `07_review_expectations.md` | Findings-first review output. |

## Capability Overview

- Governance/policy/safety/domain rules live in `.aiwf/docs/agent_rules/`.
- `AGENTS.md` is a thin managed bootstrap entrypoint at the repo root.
- Deterministic workflow correctness is enforced by `.aiwf/bin/ai_workflow.py`.
- `./aiwf` is the stable user-facing entrypoint.
- Project-level `docs/`, `tools/`, and `scripts/` remain project-owned unless content is explicitly under `.aiwf/`.
- LLM outputs are implementation drafts until workflow tooling validation/finalize passes.

If multiple task types apply, follow all matching rule files.
