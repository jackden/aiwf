# AIWF Metadata

## Purpose

AIWF metadata stores configured context such as tool, provider, model, reasoning effort, source, and confidence. These values describe configuration; they do not establish which actor executed an event. Actor Identity Evidence is recorded separately on each new event.

## Layers

- Active profile: `.aiwf/metadata_profiles/<name>.env`
- Current profile pointer: `.aiwf/metadata.current`
- Local override: `.aiwf/metadata.local.env`
- Shell override: process `AIWF_*` environment variables

## Configured Context Precedence

Effective configured metadata resolves in this order:

```text
default -> active profile -> .aiwf/metadata.local.env -> shell env
```

This precedence is deterministic and is not changed by `metadata profile use`.

## Command Semantics

- `./aiwf metadata init`
  Writes `.aiwf/metadata.local.env` as a repo-local override.
- `./aiwf metadata profile create <name>`
  Creates `.aiwf/metadata_profiles/<name>.env` with `AIWF_EVENT_LOG=1` only. New profiles do not seed model identity fields.
- `./aiwf metadata profile use <name>`
  Updates `.aiwf/metadata.current` only. It does not overwrite `.aiwf/metadata.local.env`.
- `./aiwf metadata profile current`
  Shows which profile is currently selected.
- `./aiwf metadata profile show [name]`
  Shows stored metadata and runtime options for the current or specified profile.
- `./aiwf metadata show`
  Shows the effective metadata AIWF currently uses.
  When all effective metadata fields resolve from the same source, it prints one shared `Source:` line.
  When fields resolve from mixed sources, it prints per-field `from:` lines.
- `./aiwf metadata status`
  Shows active profile, local override, shell override, runtime options, effective metadata, and resolution summary.
- `./aiwf metadata validate`
  Validates effective metadata values and runtime-option legality.

Example compact rendering:

```text
Active Profile: gpt_5_4_high
Resolution: effective metadata comes from active profile.
Source: .aiwf/metadata_profiles/gpt_5_4_high.env
Effective Metadata:
  Tool: codex
  Provider: openai
  Model: gpt-5.4
  Reasoning Effort: high
  Source: explicit_env
  Confidence: high
```

## Interactive Help In Metadata Init

During `./aiwf metadata init`, the prompt supports inline help without leaving the current field:

| Input | Behavior |
|---|---|
| `?` | Show allowed values for the current field |
| `:list` | Same as `?` |
| `:help` | Same as `?` |
| `L` | Same as `?` |
| `l` | Same as `?` |
| `:all` | Show all metadata allowed values and descriptions |

Prompt behavior notes:

- Help output re-prompts the same field after printing guidance.
- Pressing Enter still accepts the displayed default value.
- Help tokens are control inputs only and are never written into `.aiwf/metadata.local.env`.

## Runtime Option Boundary

`AIWF_EVENT_LOG` is a runtime logging option, not an actor identity field.

- It is shown under Runtime Options.
- It is not shown as Tool / Provider / Model / Reasoning Effort / Source / Confidence.
- Runtime resolution for `AIWF_EVENT_LOG` is:

```text
built-in default -> active profile -> repo .env -> shell env
```

## Recommended Patterns

- Use profiles for runtime configuration. Legacy tool/provider/model values remain readable as configured context.
- Use `.aiwf/metadata.local.env` for repo-local overrides that should persist on disk.
- Use legacy shell metadata variables for one-shot configured context overrides. They do not become execution observations.

## Event-Level Actor Identity Evidence

Configured identity ≠ self-reported identity ≠ observed identity. An event carries
`actor_identity` with an `observations` list and a derived `status`:
`unknown`, `self_reported`, `observed`, or `conflicting`. No observations produces
`unknown`. Conflicting observations are preserved; AIWF does not choose a winner.

An observation uses `source` and `method` to declare provenance:

| Source | Method | Meaning |
|---|---|---|
| `runtime` or `host` | `runtime_observation` | Execution context reported by the runtime or host |
| `actor` | `self_report` | Identity asserted by the actor |

Optional fields include `agent`, `provider`, and `model`. `reasoning_effort` belongs
only in runtime/host observations of execution configuration; actor self-reports
do not require it. Identity evidence has no confidence score. Source labels are
declared provenance, not authenticated model identity or provider verification.

Integrations may supply observations directly per event. CLI users may supply
transient JSON through the live process environment:

```bash
AIWF_ACTOR_IDENTITY='{"observations":[{"source":"actor","method":"self_report","agent":"codex","provider":"openai","model":"example-model"}]}' \
  ./aiwf record --path <task-path> --kind validation --result pass \
  --command "pytest" --summary "Tests passed"
```

`AIWF_ACTOR_IDENTITY` is never read from a profile, local metadata file, or repo
`.env`. Missing or malformed input produces unknown identity (malformed input
also emits a warning). Profile values go into `configured_context`, never into
execution observations. Unknown or conflicting identity does not add a validation,
review, authority, finalize-readiness, or finalize blocker.

## Optional Profile Migration

Existing profiles remain usable without migration. To clean a selected profile:

```bash
./aiwf profile migrate --dry-run
./aiwf profile migrate
# Equivalent metadata namespace; name is optional and defaults to current profile.
./aiwf metadata profile migrate <name> --dry-run
```

Migration uses the census-backed field classification. It removes only the six
legacy attribution keys `AIWF_AGENT_TOOL`, `AIWF_MODEL_PROVIDER`, `AIWF_MODEL_NAME`,
`AIWF_REASONING_EFFORT`, `AIWF_METADATA_SOURCE`, and `AIWF_METADATA_CONFIDENCE`; these have no
remaining non-attribution runtime configuration responsibility. It preserves
`AIWF_EVENT_LOG` and reports each preserved, removed, or reclassified field with
its reason. It validates known values and repository-safe profile paths before
atomically writing the selected profile. A malformed profile, duplicate key, or unknown field aborts without
modification. Dry-run is read-only; repeated migration reports
`No migration required.` without rewriting the profile. Historical events, task
artifacts, finalized manifests, and other configuration files remain unchanged.

Migration preserves blank lines and standalone comment lines byte-for-byte.
Assignment inline comments (for example, `AIWF_EVENT_LOG=1 # logging`) are rejected
before modification: the legacy profile loader does not parse them as comments.
Quoted values must contain only the value, with no trailing comment or other text.

The [Actor Identity Design and Census](actor_identity_evidence_design.md) records
the producer/consumer evidence behind the migration classification.
