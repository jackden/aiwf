# Worked example: verify the installed instruction block

## Create or resume the task

Use Bash from the installed project's root. The question for this task is
whether the root `AGENTS.md` contains the managed block shipped with this
installation. If you started the README quick start, continue with the same
task. Otherwise create it once.

```bash
./aiwf new-task verify_aiwf_install
```

Copy the entire dated path from the `Task directory` line. When resuming in
another terminal, run `./aiwf list` and copy the path for the intended day.
Each day has its own sequence of IDs. Enter the path at the following prompt.

```bash
read -r -p 'Paste the task directory: ' TASK
```

```bash
./aiwf guard --pre-edit --path "$TASK"
```

After the guard passes, write the requirement and acceptance criterion in
the **body** of `$TASK/task.md`. Keep its generated YAML header intact.
In `agent.md`, record the plan for comparing the installed block with the
template. If you already ran the test and recorded its result in the quick
start, continue at **Prepare the review**.

## Run and record the test

```bash
./aiwf transition --path "$TASK" --to validation
if ./aiwf agents check --path AGENTS.md; then
  ./aiwf record --path "$TASK" --kind validation --result pass \
    --command './aiwf agents check --path AGENTS.md'
else
  ./aiwf record --path "$TASK" --kind validation --result fail \
    --command './aiwf agents check --path AGENTS.md'
fi
```

Put the command, its actual output, and the limits of that check in
`self_validation.md`. If it failed, investigate the reported cause. Record any
repair, run the check again, and record its new result. A validation record
stores the result and the command text supplied by the caller. Keep the
observed output and its interpretation in `self_validation.md`. The test runs on the
`./aiwf agents check` line above.

## Prepare the review

1. In `task_record.md`, describe what was verified, why, any changes, the
   observed result and the limits. In `task.md`, give each acceptance
   criterion its actual outcome. Complete the generated body sections.
2. Have the agent review the work and its evidence. Put its findings and scope
   in `review_agent.md`. An agent recording its own decision uses
   `--decision-authority ai-agent` and its actual recorder identity.
3. New tasks default to human review. Send the task, validation and agent
   findings to the assigned reviewer. Leave the task open until they respond.

```bash
./aiwf transition --path "$TASK" --to review
```

After completing its review, the reviewing agent can use the following
command with `AGENT`, `DECISION` and `FINDINGS` set to its own identity,
its actual `pass` or `fail` decision, and its findings.

```bash
./aiwf record --path "$TASK" --kind review --result "${DECISION:?set the actual agent decision}" \
  --reviewer "${AGENT:?set the reviewing agent}" --decision-authority ai-agent --recorded-by "$AGENT" \
  --summary "${FINDINGS:?describe the actual review}"
```

Check what remains open while waiting for the human decision.

```bash
./aiwf check --path "$TASK"
./aiwf check --path "$TASK" --finalize-ready
```

The standard check examines the record's structure. Readiness checks the
evidence needed to close it. Readiness can remain blocked after a successful
agent review because the required human decision is still outstanding.

## Record the human decision and close

**Human operator only.** After reviewing the work, document your actual scope,
findings, decision, identity and limitations in `review_final.md`. On the
trusted CLI, set these variables from the decision you made. For an MCP
deployment, use its separately authorized operator channel.

```bash
read -r -p 'Your reviewer identifier: ' REVIEWER
read -r -p 'Your actual decision (pass or fail): ' HUMAN_DECISION
read -r -p 'What did you review and decide? ' REVIEW_SUMMARY
```

```bash
./aiwf record --path "$TASK" --kind review --result "${HUMAN_DECISION:?enter your actual decision}" \
  --reviewer "${REVIEWER:?enter your reviewer identifier}" --decision-authority human --recorded-by "$REVIEWER" \
  --summary "${REVIEW_SUMMARY:?describe your review}"
```

For a failed review, address the findings, record the fix, retest and obtain a
fresh decision. For an accepted review, complete the closure summary and ask
the Runtime to close the task only if it passes readiness.

```bash
./aiwf check --path "$TASK" --finalize-ready && ./aiwf finalize --path "$TASK"
```

Inspect the result with `./aiwf inspect --path "$TASK"`. After finalization,
open a follow-up task for new work. A later `record` attempt on the finalized
task returns `AIWF-FINALIZED-002`.
