# Model Workflow Analysis Guide

AIWF records workflow evidence, not model rankings or authenticated execution
identity. Configured identity ≠ self-reported identity ≠ observed identity.
Dataset version `2` retains each source event in a task's
`actor_identity_evidence` list so analysts can qualify actor-attribution claims.

## Evidence Classes

| Class | Supported interpretation |
|---|---|
| `runtime_observed` | Runtime-declared execution observation |
| `host_observed` | Host-declared execution observation |
| `self_reported` | Actor assertion, suitable only for qualified exploratory analysis |
| `configured_legacy` | Historical configured hint; execution attribution is unverified |
| `unknown` | No usable execution identity observation |
| `conflicting` | Incompatible observations retained without choosing a winner |

Source/method labels describe declared provenance; they do not authenticate the
model, verify a provider, or prove that an actor was truthful. Observed evidence
is necessary for execution-specific claims, but analysts still need to establish
the collection method's reliability. Identity confidence scores and automatic
truth resolution are outside this release.

## Model Comparisons, Failure Rates, and Compliance

An event status of `observed` does not make every field observed: a host
observation containing only `agent: codex` plus an actor self-report of
`model: X` does not establish observed execution of model X. Model comparisons
require the model value itself in a runtime/host observation.

Use runtime/host observations for claims about observed model execution, with
the evidence collection limits stated. Do not use `configured_legacy` as verified
execution evidence in model comparisons, model failure rates, or model compliance
analysis. A configured model can differ from the actor that performed a command.
Self-reports may support exploratory results when labeled explicitly and kept
separate from observations. Keep unknown and conflicting identity visible as
missing or ambiguous attribution, without guessing a model.

Do not join evidence classes solely because model names match. Mixed-class
aggregation can silently convert a configured hint into an execution claim.
A task may contain events from several actors: task-wide profile/model labels
are not substitutes for per-event identity. Report sample counts, exclusions,
source/method, workflow/protocol version, event schema, task/domain type, and
validation environment alongside any comparison. Different profiles can expose
workflow gaps without establishing model capability rankings or causality.

## Historical and Mixed Datasets

Original historical event bytes and finalized task artifacts remain primary
evidence. Dataset normalization does not upgrade a legacy claim into an
observation or alter historical closure. Compare legacy configured evidence only
as qualified historical context. Preserve event provenance when analyzing mixed
legacy/new datasets; do not overwrite it with the current active profile.

Unknown and conflicting identity are valid workflow evidence states. They do not
change validation results, review decision authority, AC closure, or finalize
readiness. Workflow completion and actor-attribution quality are separate questions.

See [Reporting Guide](reporting.md), [Metadata Guide](metadata.md), and
[Workflow Protocol](workflow_protocol.md).
