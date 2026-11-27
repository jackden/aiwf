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

## Record a review and handle findings

Use the full dated task path returned by `new-task` or `list`. Run the
project's actual validation before recording its result. The
[worked example](../examples/basic_lifecycle.md) includes a runnable test
and separate instructions for the human operator.

1. An agent reviews the implementation and validation evidence and records its
   own assessment with `--decision-authority ai-agent` and its actual recorder
   identity. Capture the review scope and findings in `review_agent.md`.
2. After a blocking finding, make the approved fix, record it with
   `record --kind fix`, rerun the relevant test and log the observed result.
   Request a fresh review of the revised work.
3. For a human-required task, send the work and evidence to the assigned
   reviewer. Keep the task open until that person responds. The authorized
   operator records the actual decision and the identity of its recorder.
4. With the evidence documents complete, use
   `./aiwf check --path "$TASK" --finalize-ready`. Run
   `./aiwf finalize --path "$TASK"` only after readiness passes.

Transitions into validation and review make the sequence easier to follow.
Closure uses the recorded evidence, review authority and readiness checks.
