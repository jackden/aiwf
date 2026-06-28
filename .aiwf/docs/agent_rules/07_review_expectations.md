# Review Expectations

For code review tasks, prioritize:

- Incorrect hardware assumptions
- Unsafe fixture behavior
- Test order dependency
- Missing cleanup after device state changes
- Weak assertions
- Overly broad exception handling
- Silent failure paths
- Race conditions and timing assumptions
- Incorrect controller/disk/DUT selection
- Logs that hide the real failure cause

Report findings with file and line references where possible.

## Final Response Expectations

For code/test/safety/workflow changes, final output must include:

- Changed
- Validation
- Review
- Remaining Risks / Notes
- Merge Recommendation: OK or HOLD

Use HOLD when required validation or review evidence is incomplete.
