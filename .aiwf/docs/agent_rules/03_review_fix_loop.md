# AI Review-Fix Lifecycle

Non-trivial changes must follow a review-fix lifecycle.

## Lifecycle Intent

- Separate implementation from correctness claims.
- Require explicit validation evidence.
- Require review-driven fix rounds for blocking findings.
- Preserve auditable reasoning and residual risk.

## Lifecycle Stages (Conceptual)

`analysis -> implementation -> validation -> review -> fix -> re-validation -> finalize`

This stage model is governance guidance.
Deterministic completion gating is enforced by `./aiwf finalize`.

## Review Principles

- Independent review should challenge assumptions, not just confirm implementation presence.
- Focus on behavioral correctness, safety impact, cleanup behavior, and hidden regressions.
- Blocking findings require fix rounds or explicit defer rationale.

## Validation Principles

- Distinguish syntax checks, unit checks, integration checks, and real DUT checks.
- Do not over-claim from narrow validation.
- Record skipped checks and constraints explicitly.

## Completion Policy

- Prose statements are not workflow truth.
- Workflow completion is valid only when deterministic tooling validation and finalize pass.
- Review status and workflow phase must remain machine-readable in metadata.
- Before finalize, run `./aiwf check --path <task> --finalize-ready`.
- Finalized tasks are closed; do not record new `validation/review/fix/safety_ack` evidence after finalize.
- If additional changes are required after finalize, open a follow-up task.
- `AIWF-FINALIZED-002` is expected closure enforcement in this flow.
- `AIWF-PATH-019` indicates post-finalize event-chain contamination and should be handled via follow-up workflow.

## Standard Command Flow (v1.6)

```bash
./aiwf transition --path <task> --to validation
./aiwf record --path <task> --kind validation --result pass --command "pytest"
./aiwf transition --path <task> --to review
./aiwf record --path <task> --kind review --result pass --reviewer human --summary "review passed"
./aiwf check --path <task> --finalize-ready
./aiwf finalize --path <task>
```

Review fail / fix / re-validation flow:

```bash
./aiwf record --path <task> --kind review --result fail --reviewer codex --summary "..."
./aiwf transition --path <task> --to implementation
./aiwf record --path <task> --kind fix --summary "..."
./aiwf transition --path <task> --to validation
./aiwf record --path <task> --kind validation --result pass --command "pytest"
./aiwf transition --path <task> --to review
./aiwf record --path <task> --kind review --result pass --reviewer human --summary "..."
./aiwf check --path <task> --finalize-ready
./aiwf finalize --path <task>
```

Note:
- Validation/review transitions are recommended for clarity.
- AIWF v1.6.1 does not enforce strict phase-gated finalize (`workflow_phase == review` is not a finalize prerequisite in v1.6.1).
