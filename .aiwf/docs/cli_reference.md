# AIWF CLI Reference

The repository-local entrypoint is `./aiwf`. Run `./aiwf --help` for the
complete command list for the installed release.

## First install

```bash
/path/to/aiwf-package/aiwf install --target .
/path/to/aiwf-package/aiwf install --target . --yes
```

The first command performs a read-only preflight. The second applies it.
Fresh install is source-driven and rejects both complete and partial AIWF
layouts; it does not perform upgrade or repair work.

## Daily workflow

```bash
./aiwf new-task <task-name>
./aiwf check --path <task-path>
./aiwf check --path <task-path> --finalize-ready
./aiwf finalize --path <task-path>
```

Use `record` for explicit validation, review, fix, and safety evidence. Use
`doctor` for diagnostics and `inspect` to distinguish historical closure from
an additive post-finalization correction.

## Existing installations

Use the [Upgrade Guide](upgrading.md) and its explicit source package for an
existing repository. Install never silently becomes upgrade.
