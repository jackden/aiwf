# Root Agent Entrypoint

`AGENTS.md` at the repository root is a thin managed bootstrap entrypoint.
This file defines the root workflow governance boundary.
It is not the canonical AIWF rule corpus.
The managed block content is sourced from `.aiwf/templates/AGENTS.block.md`.

## Responsibility Split

- `AGENTS.md`: root bootstrap surface for auto-reading tools and local repo instruction injection
- `.aiwf/docs/agent_rules/*`: canonical AIWF governance rules
- `.aiwf/docs/workflow_protocol.md`: protocol semantics and workflow behavior

## Guidance

- Read `00_index.md` before applying non-trivial repo changes.
- Read `02_ai_workflow.md` for workflow and tooling semantics.
- Update only the managed block in root `AGENTS.md`; preserve any project-specific content outside the block.
- Root `AGENTS.md` should refer to this file and the workflow protocol, not duplicate the full rule corpus.
- `./aiwf agents print-block` and `./aiwf agents install --path AGENTS.md --yes` both use the template source of truth.
