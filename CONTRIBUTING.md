# Contributing

Contributions are welcome, especially bug reports, documentation fixes, tests,
and focused implementation improvements.

Before proposing a major runtime or workflow-protocol change, please open an
issue for design discussion.

For pull requests:

- keep the change narrowly scoped
- include relevant validation results
- ensure the existing test suite passes
- do not include private workflow records, datasets, credentials, internal URLs,
  or other sensitive information
- do not rewrite finalized workflow evidence
- treat `.aiwf/` as the AIWF-owned namespace; do not assume project-root
  directories such as `docs/`, `tools/`, or `scripts/` are controlled by AIWF

By contributing, you agree that your contribution may be distributed under the
Apache License 2.0.
