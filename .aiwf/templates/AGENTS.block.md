<!-- AIWF:BEGIN -->
This repository uses AIWF.
When starting or resuming work, read `.aiwf/docs/agent_rules/00_root_entrypoint.md`
before the first substantive engineering decision, including in read-only analysis.
Before editing repository files:
- Read `.aiwf/docs/agent_rules/00_root_entrypoint.md` if you have not read it for the current task context.
- Read `.aiwf/docs/workflow_protocol.md`
When AIWF MCP is enabled, follow the mode and binding rules in
`.aiwf/docs/agent_rules/02_ai_workflow.md` for daily workflow operations.
In CLI mode, use the repository-local entrypoint.
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
