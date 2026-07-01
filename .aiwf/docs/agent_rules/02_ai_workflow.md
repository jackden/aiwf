# AI Workflow Governance

This rule defines workflow intent and invariants.
Use `./aiwf` as the repository-local command entrypoint.
Deterministic correctness enforcement is implemented in `.aiwf/bin/ai_workflow.py` and surfaced through `./aiwf`.

## Responsibility Split

| Layer | Responsibility |
|---|---|
| `.aiwf/docs/agent_rules/*` | Governance policy, safety boundaries, repository conventions |
| `./aiwf` + `.aiwf/bin/ai_workflow.py` | Deterministic workflow truth: allocation, validation, diagnostics, finalize gate |
| LLM runtime | Implementation and documentation authoring only |

## Workflow Intent

- Keep AI work records machine-readable.
- Keep task state deterministic and auditable.
- Prevent premature completion claims.
- Preserve legacy records without forced mass migration.
- Keep AGENTS.md governance instructions aligned with AIWF completion authority.
- Keep release/tool/protocol version metadata aligned in current v1.7.x governance scope unless explicit compatibility requirements require separation.

## Agent Instruction Surface

Use the managed AGENTS thin block commands when needed:

- `./aiwf agents print-block`
- `./aiwf agents check --path AGENTS.md`
- `./aiwf agents install --path AGENTS.md --yes`

## Tool-Owned Front Matter

Do not manually create or rewrite task front matter.
Use `./aiwf new-task` for task creation and structured metadata inputs.

Example:

```bash
./aiwf new-task raw_disk_smartctl_optional \
  --project EXAMPLE_PRODUCT \
  --related-task 014 \
  --tag raw_disk \
  --related-file examples/test_raw_disk.py
```

Task body may be edited by the agent. Front matter is tool-owned workflow metadata.

## Attribution Rule

- Do not use `owner` or `reviewer` as a shortcut for tool/provider/model provenance.
- Normal AI-generated task metadata should keep neutral workflow roles such as `owner: "ai-agent"` and `reviewer: "human"`.
- Actual agent identity belongs in AIWF metadata profiles, explicit env metadata, or task-local event provenance.
- Historical finalized records may keep older values; do not mass-migrate or rewrite them as part of unrelated work.

## Source Record Boundary

When analyzing AIWF workflow execution reliability, treat only `.aiwf/records/ai_YYYYMMDD/*` task directories and their task-local `.aiwf/events.jsonl` files as source workflow records.

- `.aiwf/records/ai_YYYYMMDD/*` is the workflow evidence layer: workflow execution records, task lifecycle artifacts, validation/review/finalize evidence, and task-local event logs.
- `.aiwf/docs/knowledge/*` is reusable engineering knowledge: patterns, repeatable bugs and mitigations, and decisions derived from tasks. These files are not workflow execution records.
- `knowledge/analysis/*` is derived analysis: cross-task analysis, trend analysis, workflow interpretation, and comparative studies.
- `knowledge/articles/*` is public narrative material: article planning, README strategy, public engineering narratives, and external communication drafts.
- Derived analysis and reusable knowledge may be cited as prior interpretation, but must not be counted as raw workflow evidence.
- Public narrative material must not override protocol, runtime behavior, release notes, or workflow evidence.

Source precedence:

```text
runtime code
  > protocol/design docs
  > release notes
  > workflow execution records
  > reusable engineering knowledge
  > derived analysis
  > public narrative material
```

## Deterministic Invariants

- Use `new-task` / `next-id` for task ID allocation.
- Use `check` and `doctor` for diagnostics.
- `task.md` metadata is source of truth; `.aiwf/records/ai_YYYYMMDD/index.md` is a derived projection.
- Use `sync-index --path <task_dir>` to repair stale index status from metadata.
- Only `finalize` can set workflow completion state (`status: done`, `workflow_phase: finalized`).
- Before finalize, run `check --path <task_dir> --finalize-ready` as the recommended deterministic gate.
- `finalize --path <task_dir>` is fail-closed when parent `index.md` status is stale.
- Successful finalize explicitly synchronizes parent index status projection; this mutation must be visible in command output.
- Missing required files/sections/placeholders/review state must block finalize.
- Closure evidence hygiene must also block finalize when required artifacts still show pending validation/review residue, default template residue, or unresolved acceptance-criteria closure states.
- Validation output should be actionable (error code + suggested fix).
- AIWF v1.6 uses task-local `.aiwf/events.jsonl` as path evidence for finalize gate checks.
- For v1.6 tasks, validation/review/fix evidence records are part of finalize gate.
- `record --kind validation --command "<...>"` records command evidence only; it does not execute commands.
- A finalized task is closed. Do not append `validation`, `review`, `fix`, or `safety_ack` evidence after finalize.
- If additional work is required post-finalize, create a follow-up task.
- Finalized required artifacts are governance-controlled evidence (`task.md`, `task_record.md`, `self_validation.md`, `review_agent.md`, `review_final.md`).
- `review_agent.md` is the canonical AI/agent review artifact for new records; `review_codex.md` is a legacy alias retained for backward compatibility.
- AIWF does not guarantee physical immutability of finalized artifacts.
- AIWF governance guarantee is drift handling: detect, diagnose, repair, preserve evidence.
- Follow-up tasks must not silently rewrite finalized evidence from earlier tasks.
- For post-finalize interpretation/drift issues, use a dedicated follow-up task that references original task/file/section and records repair evidence.
- For `AIWF-PATH-015`, revert post-finalize edits. Use amend/reopen only when a controlled runtime command is actually supported.
- Treat `AIWF-FINALIZED-002` as expected closure enforcement.
- Treat `AIWF-PATH-019` as event-chain contamination that requires follow-up handling.
- Closure evidence hygiene checks validate workflow readiness only; they do not validate business completion truth.
- Treat version metadata alignment as governance metadata behavior, not automatic runtime semantic change.

## v1.6.1 Scope Note

- AIWF v1.6.1 remains evidence-driven.
- Do not assume strict phase-gated finalize in governance text.
- Do not state `finalize requires workflow_phase == review`; strict phase gating is deferred.

## Required Work Record Files

For non-trivial code/test/safety/workflow changes:

- `task.md`
- `agent.md`
- `task_record.md`
- `self_validation.md`
- `review_agent.md`
- `review_final.md`

Legacy records that contain only `review_codex.md` remain compatible and should
not be renamed as part of unrelated work.

## Legacy Compatibility Policy

- Legacy tasks without front matter must remain readable/exportable.
- Legacy metadata gaps may warn, but should not require mass rewrite as part of unrelated work.

## Operational Note

Use shell-appropriate Python path (PowerShell vs Bash).
For wrapper invocation, `./aiwf` resolves interpreter in this order: `AIWF_PYTHON`, `.venv/bin/python`, `.venv/Scripts/python`, `.venv/Scripts/python.exe`, `python`, then `python3` (must be Python >= 3.10).
WindowsApps alias interpreters under `Microsoft/WindowsApps` are skipped during wrapper fallback selection.
Tool behavior, not prose checklists, is the source of workflow correctness.
