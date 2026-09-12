# Basic Lifecycle Example (AIWF v1.7.14)

## End-to-End Command Flow
```bash
./aiwf new-task demo_aiwf_task --date 20260516 --allow-non-today-date
./aiwf transition \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task \
  --to validation
./aiwf record \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task \
  --kind validation \
  --result pass \
  --command "python -m pytest -q" \
  --summary "unit tests passed"
./aiwf transition \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task \
  --to review
./aiwf record \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task \
  --kind review \
  --result pass \
  --reviewer human \
  --decision-authority human \
  --recorded-by codex \
  --summary "review passed"
./aiwf check \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task \
  --finalize-ready
./aiwf finalize \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task
./aiwf report \
  --path .aiwf/records \
  --format markdown
```

## Clarifications
- `transition --to validation` and `transition --to review` are recommended for readability.
- AIWF v1.7.14 does not require strict `workflow_phase == review` before finalize.
- The final review decision authority must satisfy the task's
  `required_review_authority`; the recording actor may be different.
- `doctor`/`report` derived evidence is observational and does not add a new
  finalize gate.

## Negative Example: Post-Finalize Record Rejection
```bash
./aiwf record \
  --path .aiwf/records/ai_20260516/001_demo_aiwf_task \
  --kind fix \
  --summary "post-finalize fix"
```

Expected diagnostic:
- `AIWF-FINALIZED-002`

Recovery:
- Do not append evidence to this finalized task.
- Create a new follow-up task and continue there.
