# AIWF Upgrade Example: v1.7.5.post2 to v1.7.7

## Scenario

- Source version: `1.7.5.post2`
- Target version: `1.7.7`
- Legacy records migrated: `128` `task.md` records
- Legacy paths relocated: `38`
- Result: `PASS`

## What Was Validated

This example captures a successful legacy-repo upgrade to the v2 `.aiwf/` layout.
It is historical v1.7.7 evidence, not current v1.7.8.post1 installation guidance.
For current public usage, `./aiwf` is the supported entrypoint, `.aiwf/bin/ai_workflow.py` is the canonical runtime, and project-level `tools/ai_workflow.py` is treated as project-owned legacy content when present.

The upgrade flow was validated with:

```bash
./aiwf upgrade --check --source /path/to/new_aiwf_repo
./aiwf upgrade --dry-run --source /path/to/new_aiwf_repo
./aiwf upgrade --apply --source /path/to/new_aiwf_repo
```

Observed result:

- `.aiwf/bin/ai_workflow.py` was installed as the canonical runtime from the source repo
- `tools/ai_workflow.py` was installed from the source repo as the compatibility shim
- the target repo's legacy `tools/ai_workflow.py` was not relocated into `.aiwf/bin/ai_workflow.py`
- workflow evidence paths and config content were preserved
- root AGENTS integration still depends on `.aiwf/templates/AGENTS.block.md` being present in the package copy

## Known Non-Blocker

- `docs/backup/agent_rules/templates/task.md` is not an AIWF execution record

That file is a template artifact, so it should not be counted as migrated workflow evidence.

## Result Summary

This upgrade case is a positive example for the v1.7.7 documentation set.
It confirms that the upgrade guide, preserved-path contract, and legacy-layout relocation rules can be used safely on a real legacy repository.
AGENTS managed block validation remains a separate package requirement and should be checked after the template file is present.
