# AIWF Metadata

## Purpose

AIWF metadata records operator-facing AI attribution such as tool, provider, model, reasoning effort, source, and confidence.
These values support research evidence, provenance clarity, and dogfooding analysis.

## Layers

- Active profile: `.aiwf/metadata_profiles/<name>.env`
- Current profile pointer: `.aiwf/metadata.current`
- Local override: `.aiwf/metadata.local.env`
- Shell override: process `AIWF_*` environment variables

## Attribution Precedence

Effective attribution metadata resolves in this order:

```text
default -> active profile -> .aiwf/metadata.local.env -> shell env
```

This precedence is deterministic and is not changed by `metadata profile use`.

## Command Semantics

- `./aiwf metadata init`
  Writes `.aiwf/metadata.local.env` as a repo-local override.
- `./aiwf metadata profile create <name>`
  Saves the current effective metadata into `.aiwf/metadata_profiles/<name>.env` and writes `AIWF_EVENT_LOG=1` by default.
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

`AIWF_EVENT_LOG` is a runtime logging option, not an AI attribution field.

- It is shown under Runtime Options.
- It is not shown as Tool / Provider / Model / Reasoning Effort / Source / Confidence.
- Runtime resolution for `AIWF_EVENT_LOG` is:

```text
built-in default -> active profile -> repo .env -> shell env
```

## Recommended Patterns

- Use profiles for stable baseline identities, for example a preferred tool/provider/model tuple.
- Use `.aiwf/metadata.local.env` for repo-local overrides that should persist on disk.
- Use shell `AIWF_*` variables for one-shot overrides during ad hoc experiments.
