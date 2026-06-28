# Core Rules

## Environment

- Use the local Python virtual environment at `.venv` by default.
- Prefer PowerShell-compatible commands on Windows.
- Use `pytest` for test execution.
- Do not install or upgrade dependencies unless explicitly requested.
- Do not modify generated logs, archives, or collected diagnostic artifacts unless the task specifically requires it.

Typical commands:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests
.\.venv\Scripts\python.exe -m pytest path\to\test_file.py -k test_name
```

## Token / Output Hygiene

- If `rtk` is available, prefer `rtk <command>` for read-only exploratory commands that may produce large output, such as directory listings, searches, git/status inspection, and log sampling.
- Do not require `rtk` for commands where exact raw output matters, for test execution, for commands that modify files/state, or when `rtk` is unavailable.
- Continue to prefer `rg` / `rg --files` for text and file searches. Use `rtk` only as an output-filtering wrapper when it does not change command semantics.

## Working Rules

Before editing code:

1. State the assumption behind the change.
2. Identify the smallest file/function scope needed.
3. Avoid broad refactors unless explicitly requested.
4. Prefer reproducing bugs with a focused test or existing failing command.

## Workflow Invariants

- Task IDs are tool-allocated (`./aiwf next-id` / `new-task`), not manually inferred.
- Workflow completion truth belongs to tooling (`./aiwf finalize`), not prose claims.
- Validation evidence must be recorded in `self_validation.md` before finalize.
- Destructive or high-risk execution claims must have explicit command evidence or be marked skipped with reason.

When editing:

- Make surgical changes only.
- Match existing style and naming.
- Do not clean up unrelated files.
- Do not reformat entire files unless formatting is the task.
- Do not delete logs, tarballs, reports, cache folders, or backup folders unless explicitly requested.
- If unrelated dead code or suspicious behavior is found, mention it instead of changing it.

## Repository Hygiene

Common generated or diagnostic artifacts may include:

- `logs/`
- `report/`
- `backup_*`
- `tmp_*`
- `pytest-cache-files-*`
- `*.log`
- `*.tar.gz`
- `*.zip`
- `.pytest_cache/`
- `__pycache__/`

Do not modify or remove these unless they are directly part of the task.

## Implementation Preferences

- Prefer simple procedural code when it matches existing tests.
- Avoid new abstractions for one-off test cases.
- Keep helper functions small and named after the hardware/test behavior they encapsulate.
- Use existing fixtures, utilities, and project helpers before adding new ones.
- Preserve existing test naming conventions.
- Keep assertions explicit and diagnostic.

## Communication

When uncertain:

- Ask before making risky assumptions.
- Explain hardware-impacting risks plainly.
- State what was changed and how it was verified.
- If verification was skipped, explain why.
