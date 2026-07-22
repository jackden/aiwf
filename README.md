# AIWF

Repository-native, lightweight deterministic workflow governance for AI-assisted engineering.

## Why AIWF

AI-generated work can be useful before it is complete. A claim may be narrowed
by review, corrected, re-validated, or left bounded by an external dependency.
AIWF keeps those workflow decisions and their evidence visible in the
repository.

Git records how code changed. AIWF records the workflow evidence used to
validate, review, correct, and close the work.

## Install

Use a trusted local AIWF source package: a directory containing the executable
`aiwf` entrypoint and the committed `.aiwf/` package paths. Run the command from
the repository that should receive AIWF:

```bash
/path/to/aiwf-package/aiwf install --target . --yes
```

`--target` is the destination repository. Without `--yes`, AIWF performs the
same preflight and prints the plan without changing files. A complete or
partial installation is rejected; use the [Upgrade Guide](.aiwf/docs/upgrading.md)
for an existing AIWF repository.

### Install Payload Boundary

Public repository contents are not the install payload. Installation is limited
to the AIWF launcher and runtime-owned `.aiwf/` paths; repository-level
development assets such as `tests/`, `.github/`, root `docs/`, `knowledge/`,
release files, and review artifacts are intentionally excluded. Existing
project-owned `tests/`, `.github/`, and `docs/` directories are preserved
byte-for-byte.

After installation, the first command is:

```bash
./aiwf new-task demo_task
```

## Five-minute Quick Start

Create a task, implement the requested change, then record validation and
review evidence in the generated artifacts:

```bash
./aiwf new-task demo_task
./aiwf check --path <task-path>
./aiwf check --path <task-path> --finalize-ready
./aiwf finalize --path <task-path>
```

Replace `<task-path>` with the path printed by `new-task`. The finalize-ready
check is read-only. Finalize closes the current workflow only after the
required evidence and review decisions are complete.

## How AIWF Works

<p align="center">
  <img src=".aiwf/docs/images/aiwf_overview.svg" width="760" alt="AIWF workflow overview">
</p>

AIWF provides task creation, deterministic checks, validation and review
evidence, correction tracking, and a completion gate. It does not execute the
engineering work or infer conclusions with an LLM.

## What AIWF Makes Visible

An ordinary engineering change can be represented as:

```text
Initial claim
    → Review finding
    → Correction
    → Re-validation
    → Evidence-backed Closure
```

The final Closure Summary is a short, human-authored conclusion aid:

```markdown
## Closure Summary
- Workflow Decision: finalize
- Engineering Outcome: bounded_incomplete
- Remaining Limitations: Real-DUT validation was not executed in this task.
- Follow-up: Real-DUT validation is tracked in task 052.
```

Workflow Decision and Engineering Outcome are different. `finalize` means the
current workflow has an explicit closure; it does not guarantee product
correctness. Closure Summary is not currently a finalize blocker.

## What AIWF Is

- A repository-native deterministic workflow governance layer.
- A place for local task, validation, review, and finalize evidence.
- A lightweight companion to AI-assisted engineering workflows.
- A tool that keeps workflow history inspectable without becoming the execution engine.

## What AIWF Is Not

- Not a prompt template or autonomous coding framework.
- Not a CI system or a replacement for Git.
- Not a DUT runner or domain validation system.
- Not a workflow orchestration engine.
- Not a tamper-proof audit ledger.
- Not a guarantee of correctness or reliability.
- Not a replacement for Human Review or accountable engineering judgment.

## Design Principles

### Evidence over claims

Completion claims should be supported by explicit workflow evidence.

### History is preserved

Workflow history should be extended rather than silently rewritten.

### Human authority remains explicit

AI assists engineering work but does not replace accountable human judgment.

### Deterministic before intelligent

Prefer deterministic governance rules before introducing model-dependent
reasoning.

## Project Status and Current Release

AIWF is under active development and is being evaluated through real engineering
workflow records. Use tagged public releases for adoption. Tool and protocol
versions evolve independently.

| Field | Value |
| --- | --- |
| Current Release | `1.7.13.post1` |
| Tool Version | `1.7.13.post1` |
| Workflow Protocol Version | `1.7.8` |
| Latest Release Notes | [v1.7.13.post1](.aiwf/docs/releases/v1.7.13.post1.md) |
| GitHub Releases | [jackden/aiwf releases](https://github.com/jackden/aiwf/releases) |

## Documentation

- [Installation Guide](.aiwf/docs/adoption_guide.md)
- [Upgrade Guide](.aiwf/docs/upgrading.md)
- [CLI Reference](.aiwf/docs/cli_reference.md)
- [Workflow Protocol](.aiwf/docs/workflow_protocol.md)
- [Agent Rules](.aiwf/docs/agent_rules/00_index.md)
- [Reporting Guide](.aiwf/docs/reporting.md)
- [Security / Repository Boundary](.aiwf/docs/repo_boundary.md)
- [Release Notes](.aiwf/docs/releases/)

Post-finalization changes have two distinct paths: accidental artifact changes
use a dedicated repair workflow; a new fact or human-authorized correction is
recorded additively with `correct-finalized` and does not rewrite history. See
the [Workflow Protocol](.aiwf/docs/workflow_protocol.md) for the boundary.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
