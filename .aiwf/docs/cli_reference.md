# AIWF CLI Reference

The repository-local entrypoint is `./aiwf`. Run `./aiwf --help` for the
complete command list for the installed release.

## First install

```bash
/path/to/aiwf-package/aiwf install --target .
/path/to/aiwf-package/aiwf install --target . --yes
```

The first command performs a read-only preflight. The second applies it.
Fresh install is source-driven and rejects both complete and partial AIWF
layouts; it does not perform upgrade or repair work.

## Daily workflow

```bash
./aiwf new-task <task-name>
./aiwf check --path <task-path>
./aiwf check --path <task-path> --finalize-ready
./aiwf finalize --path <task-path>
```

Use `record` for explicit validation, review, fix, and safety evidence. Use
`doctor` for diagnostics and `inspect` to distinguish historical closure from
an additive post-finalization correction.

## Review authority evidence (v1.7.14)

New tasks use schema `ai-workflow-v1.7` and default to
`required_review_authority: human`. Review records must state the authority of
the decision separately from the actor that records it:

```bash
./aiwf record --path <task-path> --kind review --result pass \
  --reviewer human \
  --decision-authority human \
  --recorded-by codex \
  --summary "Human review decision recorded by the agent"
```

Use `--decision-authority ai-agent` only when the task policy permits an agent
decision. Use `--decision-authority not_required` only with
`--result not_required`; the existing non-empty `--summary` reason remains
required. `recorded_by` may differ from `decision_authority`. These fields are
workflow evidence assertions, not authenticated human identity or
cryptographic approval.

`check --finalize-ready` and `finalize` validate the latest final review's
required-authority snapshot, decision authority, and recording actor. Older
finalized records remain readable without migration; active older tasks that
explicitly require human review cannot bypass the authority check.

## Derived evidence diagnostics

`doctor --path <task-path>` prints a `Workflow Evidence Summary`. JSON/Markdown
`report` output includes each task's `derived_evidence`, derived status, and
derived warning codes. The view reports correction-loop counts, validation
outcomes, review freshness, authority consistency, local/global event
projection discrepancies, schema compatibility, and last activity age.

Derived warnings are observational only. They do not add finalize blockers,
workflow phases, validation dispositions, reliability scores, or a second
workflow state source. `check --finalize-ready` and `finalize` do not consume
Task 002 derived warnings as gates.

## Existing installations

Use the [Upgrade Guide](upgrading.md) and its explicit source package for an
existing repository. Install never silently becomes upgrade.
