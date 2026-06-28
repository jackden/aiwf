# AGENTS.md
<!-- AIWF:BEGIN -->
This repository uses AIWF.
Before editing repository files:
- Read `.aiwf/docs/agent_rules/00_root_entrypoint.md`
- Read `.aiwf/docs/workflow_protocol.md`
Use `./aiwf` for:
- task creation
- pre-edit guard
- validation
- review evidence
- `./aiwf finalize`
- `./aiwf check --path <task_path>`
- `./aiwf check --path <task_path> --finalize-ready`
Do not manually rewrite AIWF task front matter.
AIWF workflow records are stored under:
.aiwf/records/
Workflow events are stored under:
.aiwf/events/
<!-- AIWF:END -->
