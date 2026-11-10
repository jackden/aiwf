# Actor Identity Evidence Semantic Migration

## Census scope and baseline

This is the Task 1 design and producer/consumer census, completed before changing
runtime behavior. It records the inspected baseline, rather than describing the
subsequent implementation as if it already existed. Baseline runtime references
below are function names plus line numbers in `.aiwf/bin/ai_workflow.py` at tool
version `1.7.14`; line numbers can move during implementation.

The inspected baseline has release/tool `1.7.14`, workflow protocol `1.7.9`,
task metadata `ai-workflow-v1.7`, command event `aiwf-event-v0.1`, evidence event
`aiwf-event-v0.3`, experiment export `aiwf-experiment-v0.1`, and dataset version
`1`. These values are runtime constants at lines 97–113 and agree with the
current protocol and release note.

The migration release will be `1.7.15`, protocol `1.7.10`, with
`aiwf-event-v0.4` for both newly written command and evidence events and dataset
version `2`. The task metadata schema stays `ai-workflow-v1.7`. This is an
evidence semantics change, not a packaging patch or profile redesign.

The census searched all checked-in and working-tree runtime Python/Bash files,
package helpers, wrapper, templates, tests, protocol, metadata documentation,
release documentation, knowledge analysis, and narrative documentation for
`profile`, `ai_agent`, `model_name`, `agent_model`, `provider`,
`reasoning_effort`, `confidence`, metadata resolution, event writers/readers,
and dataset/export paths. Searches included hidden `.aiwf` paths. Historical
records are inputs to compatibility verification, not files to repair or
rewrite. No local credential/profile contents are required to establish the
consumer graph.

There are no unresolved in-repository consumers of the registered profile
fields. External scripts that consume AIWF exports cannot be inventoried from
this repository; the schema/version boundary and conservative legacy export
classification address that compatibility limit without assuming their behavior.

## Invariants

- AIWF must not make a stronger actor-attribution claim than its evidence source
  supports.
- Actor identity evidence is provenance evidence, not workflow authority and not
  model governance. Source labels describe supplied evidence; AIWF does not
  authenticate a host, actor, provider, or actual model execution.
- Configured identity, self-reported identity, and observed identity are distinct
  evidence classes. Identical model strings do not merge those classes.
- Unknown, missing, conflicting, or malformed optional identity must not add a
  validation/review/finalize/finalize-ready blocker.
- Existing authority fields retain their current responsibility:
  `required_review_authority`, `decision_authority`, and `recorded_by` are not
  inferred from an agent, provider, model, or identity status.
- Upgrade requires no profile migration. Legacy profiles remain loadable and
  usable while future events follow the new semantics immediately.
- Historical task artifacts, validation/review records, local/global event
  rows, correction artifacts, indexes, and finalized manifests are not rewritten
  by this migration. New events append through the existing writer only.

## Field classification from actual consumers

Classification: A = workflow configuration; B = integration configuration;
C = configured identity hint; D = legacy execution attribution. A field may
have C/D history while having no A/B responsibility. Operator display and
metadata validation are consumers, but do not route a model or configure an
integration.

| Current field | Current source | Current consumers and semantics | Classification / non-attribution responsibility | Future semantics | Migration action |
|---|---|---|---|---|---|
| `tool` / `AIWF_AGENT_TOOL` | Defaults, active profile, local env, shell env | Resolver; metadata display/init/create/validate; both event writers; metadata report tool distribution | C/D; no workflow or integration behavior depends on it | Optional configured tool context; event observation `agent` only through explicit event input | Remove profile key; continue reading unmigrated legacy profiles as configured context |
| `provider` / `AIWF_MODEL_PROVIDER` | Same metadata layers; separately `.env`/shell runtime context | Same metadata consumers; `build_event_context` also writes legacy `model.provider`; experiment export reads that context | C/D; no API selection, connection, routing, credentials, or integration configuration | Configured provider context; explicit observation `provider` only | Remove profile key; do not rewrite `.env` or shell variables |
| `model_name` / `AIWF_MODEL_NAME` | Same metadata layers; separately `.env`/shell runtime context | Same metadata consumers; free text; legacy `model.name`; experiment export context/coverage report | C/D; no execution configuration or model routing | Configured model context; explicit observation `model` only | Remove profile key; retain compatibility reader; no historical reinterpretation |
| `reasoning_effort` / `AIWF_REASONING_EFFORT` | Defaults/profile/local/shell metadata only | Registry allow-list, prompts, display, validation, profile seeding, event `ai_agent`; report extraction retains it | C/D; no model configuration consumer | Configured reasoning context only; an explicit runtime/host observation may record execution configuration | Remove profile key; no self-report requirement or confidence inference |
| `source` / `AIWF_METADATA_SOURCE` | Metadata layers; value supplied by configuration, separately from field-level resolution source | Metadata validation/display; event `ai_agent.source`; report distribution | C/D; labels metadata acquisition, not actual observation source | Legacy configured metadata source, independent of observation `source`/`method` | Remove profile key; never convert `profile`/`shell_env`/`explicit_env` to observed identity |
| `confidence` / `AIWF_METADATA_CONFIDENCE` | Defaults/profile/local/shell metadata | Registry/init/create/validate/display; event `ai_agent.confidence`; report distribution | D (legacy attribution certainty); no workflow/integration use | Legacy configured metadata only; no identity confidence/scoring | Remove profile key; preserve historical value only in qualified configured context |
| `AIWF_EVENT_LOG` | Default -> active profile -> `.env` -> shell env | `resolve_aiwf_runtime_options_with_sources`, logging enablement, runtime-option validation, profile/status display | A; determines optional command event logging | Unchanged logging option | Preserve exact profile line/value |
| `AIWF_WORKFLOW_MODE` | Default -> `.env` -> shell env | `build_event_context`, both event writers, experiment export | A/context; no model identity | Workflow context label | Outside profile migration allow-list; an unexpected profile occurrence aborts migration |
| `AIWF_ACTOR` | Default -> `.env` -> shell env | Event recording label; review `recorded_by` fallback | Workflow evidence recording provenance; not model identity | Retain existing authority/recording behavior | Outside profile migration allow-list; never remove from `.env` |
| `AIWF_MODEL_CLASS` | Default -> `.env` -> shell env | Legacy `model.class`; experiment context only | C/D; no runtime execution configuration | Configured context only | Outside registered profile schema; unexpected profile occurrence aborts |
| `agent_model` | Architecture prose only | No runtime, parser, test, template, or task-metadata consumer | Descriptive proposed field, not a supported runtime field | No new field or inferred identity | Do not migrate historical prose/task documents |

The important distinction is that `AIWF_MODEL_NAME`/`AIWF_MODEL_PROVIDER` are
also registered in `ENV_DEFAULTS`. That loader only accepts `AIWF_EVENT_LOG`
from profiles; their `.env`/shell legacy `model` path is a second configured
context producer, not evidence of a profile integration responsibility. Both
paths must be separated from new execution identity.

## Producer and configuration census

| Path/function at baseline | Kind | Effect and migration boundary |
|---|---|---|
| `AI_AGENT_METADATA_DEFAULT`, `AI_AGENT_METADATA_ENV_MAP`, `METADATA_FIELDS`, registry (340–562) | Configuration / schema | Six attribution fields, allow-lists and prompts; no integration settings |
| `_parse_simple_env_file` (883) | Compatibility read | Permissive legacy reader ignores malformed lines and uses last duplicate key; keep normal legacy loading compatibility, do not reuse this permissiveness for migration |
| `_metadata_*_path`, `_active_metadata_profile_name`, `_current_profile_state` (906–1067) | Configuration / read | Profile storage and current pointer; names validated, absent/dangling state represented |
| `_extract_ai_agent_metadata_fields`, `_normalize_ai_agent_metadata` (922–945) | Compatibility read | Map six env keys, trim values, supply neutral defaults |
| `resolve_ai_agent_metadata_with_sources`, `resolve_ai_agent_metadata` (1068–1099) | Read / configured producer | Per-field default -> profile -> local -> shell; actual layer/path is independent of configured `source` value |
| `resolve_aiwf_runtime_options_with_sources`, `load_aiwf_env` (1102, 901) | Configuration / read | Only `AIWF_EVENT_LOG` is profile-supported runtime configuration; `.env`/shell may add legacy context |
| `_seed_profile_metadata_defaults`, `_metadata_to_env_lines` (1156, 1250) | Write producer | Copy known attribution into six-key profiles, including confidence; must cease new-profile identity seeding |
| `metadata_init_command` (9561) | Write producer | Writes local override with six fields; label configured context, never actual actor observation |
| `metadata_profile_create_command` (9597) | Write producer | Writes six attribution keys plus `AIWF_EVENT_LOG=1`; new profiles need only actual runtime configuration |
| `metadata_profile_use_command` (9637) | Write configuration | Writes current pointer only; must remain usable for old profiles and warn about overrides |
| `build_event_context` (1382) | Legacy configured producer | `.env`/shell `model.name/class/provider`, `actor`, `workflow_mode`; model moves under `configured_context` |
| `append_aiwf_event` (5082) | Event write producer | Optional command v0.1 envelope with both resolved `ai_agent` and legacy `model`; must use v0.4 and explicit identity boundary |
| `_append_evidence_event` (6242) | Event write producer | Mandatory evidence v0.3 envelope with both configured paths; same v0.4 identity boundary |
| `_append_raw_event` (6229) | Raw write | Appends the same object to task-local `.aiwf/events.jsonl` and configured repository event log; no independent identity resolution |
| `aiwf` wrapper, `safe_paths.py`, `lib/package_core.py` | Entrypoint / path / packaging | No metadata/profile/model consumer or separate attribution writer |

There is no supported `profile migrate` implementation at the baseline. The
new command must be deterministic tooling, not manual editing or a generic env
key deletion script. `metadata profile migrate` may be the canonical nested
command with `profile migrate` as a supported discoverable alias.

### Every event-producing caller

| Caller | Event types / command | Writer | Conditions |
|---|---|---|---|
| `transition_command` (5226) | Explicit `phase_transition` | Evidence | After valid metadata phase mutation |
| `record_command` (5379) | `validation_recorded`, `review_recorded`, `fix_recorded`, `safety_ack_recorded` | Evidence | After existing evidence/authority checks; finalized tasks reject these records |
| `check_path` (6071) | `command=check` | `_try_append_aiwf_event` -> command writer | Task-specific ordinary check only, logging enabled |
| `doctor_command` (9887) | `command=doctor` | Command | Logging enabled after diagnostics |
| `finalize_command` (9915) | Blocked `command=finalize` | Command | Normal finalize only; no success event |
| `finalize_command` (9946) | Already-finalized `command=finalize` | Command | Existing diagnostic logging behavior only |
| `finalize_command` (9975) | Index-sync-failed `command=finalize` | Command | Metadata rollback; no success event |
| `finalize_command` (9985) | Implicit finalized `phase_transition` | Evidence | Only after metadata and index mutation succeeds |
| `finalize_command` (10004) | `finalize_success` with manifest | Evidence | Same successful mutation boundary |
| `finalize_command` (10026) | Final `command=finalize` diagnostics | Command | Logging enabled after successful closure evidence |

`_try_append_aiwf_event` (5120) is the sole exception-tolerant command logging
wrapper. `check --finalize-ready`, `finalize --dry-run`, repository/date-root
check, guard, task creation/backfill, inspect/correction, report, export,
install/upgrade, and profile commands do not produce another attribution event.
Read-only modes must continue bypassing the writer entirely.

## Reader, display, export, and validation census

| Consumer at baseline | Kind | Current behavior / required future boundary |
|---|---|---|
| `_print_effective_metadata_with_sources`, `_metadata_resolution_summary` (978–1026); `_print_metadata_block`, `_print_runtime_options_block` (9511–9529) | Display | Field/layer/path display; describe configured context, not execution identity |
| `metadata show/allowed-values/profile list/current/show/status` (9530–9559, 9619–9636, 9661–9767) | Display / compatibility | Old profiles remain readable; field meanings must be explicit; logging option remains separate |
| `_metadata_validation_errors`, `_runtime_option_validation_errors`, `metadata_validate_command` (1181–1225, 9580) | Validation | Metadata legality only; not called as task closure gate; keep valid old profiles acceptable |
| `_extract_event_ai_agent` (1355), `metadata_report_command` (9768) | Attribution read / analytical display | Reads `ai_agent`, falls back legacy `model`, reports known model/source/confidence/provider/tool; must qualify configured counts separately from observed/self-reported evidence |
| `_derive_experiment_context_from_events`, `export_experiment_command` (6280, 6324) | Export / compatibility | Legacy event `model` consensus or current-env fallback; both are configured context, never infer actual actor/model from either |
| `_load_events_with_stats`, `_load_events`, `_load_jsonl_events_with_stats` (6202, 6224, 6485) | Compatibility read | JSONL parsing, malformed counts, no identity verification; keep legacy/new streams readable |
| `_event_type`, `_event_result_status`, `_event_field`, `_event_payload_from_legacy`, `_normalize_event` (4605–4766) | Compatibility / projection | Event naming/result/payload compatibility; preserve complete raw event, avoid copying new reserved identity/configuration envelope fields into legacy payload |
| `_event_schema_compatibility` (6539) | Diagnostics | Recognizes legacy/v0.1/v0.2/v0.3; register v0.4, treat v0.3 as legacy relative to new current schema, warn on unsupported schema without new closure gate |
| `_canonical_event_projection_key`, `build_derived_evidence_summary`, derived diagnostics and display (6532, 6580–6906) | Read / display | Full JSON projection equality, activity/schema/review diagnostics; preserves provenance fields, no model gate |
| `_dataset_event_inventory`, association helpers, `collect_task_dataset_record`, `collect_dataset_records*`, `build_dataset_export_payload`, `dataset_export_command` (6907–7216) | Dataset / export | Version 1 only counts event types and workflow artifacts; version 2 adds qualified per-event attribution rather than pretending an existing identity dataset already exists |
| `_package_records_dataset_plan`, `_package_records_package_files` (7726, 8372) | Export | Embeds dataset and dataset-version manifest; automatically use new builder/version without changing package selection/integrity contract |
| `_package_records_event_plan`, `_package_records_canonical_events_jsonl`, event inventory (8067–8227, 8307, 8273) | Export / compatibility | Wraps complete raw event with source location, stable sorting, serializes all raw fields; retain source evidence exactly in meaning; normalize only separate dataset view |
| `build_report_payload`, report rendering (9331–9510) | Read / display | Counts normalized workflow events/schemas, no model attribution decisions |
| `_collect_task_diagnostics`, `_collect_path_policy_diagnostics`, `_collect_review_authority_diagnostics`, finalize hygiene (4951, 4808, 4645, 4485) | Validation / closure | Uses lifecycle, validation/review freshness, authority, artifact/index/manifest/JSONL hygiene; none reads profile model/provider/tool/reasoning/confidence as completion authority |
| `package_review_bundle.py`, `export_public_tree.py` | Packaging / boundary | Exclude private event/profile/dataset state; do not interpret model metadata; adding a public design/release doc does not authorize exporting private evidence |

Tests covering current consumers are concentrated in
`tests/unit/test_ai_workflow.py`: dataset/export at 2709–3106, package dataset and
event handling at 3268–3350 and 4106–4401, read-only/finalize guards at
4585–4758, command/experiment context at 5450–5559, lifecycle/authority/legacy
event compatibility at 5781–6791, derived diagnostics at 6849–7142, and metadata
resolution/validation/profile/display/report at 7199–8093. Other unit files
cover entrypoint, path boundaries, managed instructions and packaging exclusion;
they have no direct profile/model attribution consumer.

Templates under `.aiwf/templates` and agent-rule task templates have no model
identity fields. Task owner/reviewer remain workflow roles. The untracked
architecture document's `agent_model` examples have no runtime consumer.
Current docs needing semantic updates are `metadata.md`, protocol section 2.3,
agent-rule attribution guidance, reporting/analysis guidance, CLI/upgrading,
and `.env.example`. Adoption and packaging docs only describe exclusion and
layout. Historical release notes, finalized records, and prior analysis or
narrative examples are historical context; new guidance qualifies their meaning
without rewriting them as observed evidence.

## Minimal v0.4 event contract

Every new command/evidence envelope contains `actor_identity`:

```json
{"actor_identity":{"observations":[],"status":"unknown"}}
```

An observation has required `source`/`method` and optional non-empty string
`agent`, `provider`, `model`, and `reasoning_effort` fields. Supported pairs:

| Source | Method | Meaning |
|---|---|---|
| `actor` | `self_report` | Actor-supplied attribution assertion |
| `host` | `runtime_observation` | Host-supplied execution observation assertion |
| `runtime` | `runtime_observation` | Runtime-supplied execution observation assertion |

Host/runtime values are preserved as supplied; a caller being able to write
these labels is not authentication or provider verification. No profile,
local override, `.env`, existing `AIWF_MODEL_*`, metadata `source`, or metadata
`confidence` can create one of these observations. Self-reports need not
contain reasoning effort; execution reasoning effort belongs only to explicit
host/runtime observations in this first version.

Status is derived deterministically, never accepted as authority from input:

- No supported identity claims: `unknown`.
- Only valid actor self-reports: `self_reported`.
- At least one host/runtime observation, with no conflicting overlapping claim:
  `observed`.
- Different supplied non-empty known values for any overlapping identity field:
  `conflicting`, with all valid observations preserved in input order.

Matching observations remain separate observations. Disjoint fields alone do
not conflict. Comparison uses exact strings after whitespace normalization;
there is no model/provider alias canonicalization, ranking, winner selection,
or automatic truth resolution. Empty/`unknown` values supply no identity claim.
Do not synthesize missing fields from profiles. Unsupported source/method,
invalid object shape, forbidden confidence, or invalid field values fail closed
for attribution: produce unknown identity and a non-blocking warning, rather
than promoting a malformed claim or adding a workflow blocker. Readers of raw
historical events retain original data and diagnose invalid identity without
rewriting it.

Both writers put resolved old metadata and legacy model context under the
clearly named `configured_context` envelope. New events must not retain naked
`ai_agent`/`model` fields that imply actor execution. `actor`, `workflow_mode`,
review authority, result, diagnostics, manifest, and event payload keep their
existing workflow responsibilities. Reserved envelope fields cannot leak back
through legacy payload flattening or override the derived identity.

### Explicit event input channel

Use a transient process-only JSON channel `AIWF_ACTOR_IDENTITY` and an explicit
writer argument for direct runtime callers. The process channel is read from
live `os.environ` only; never add it to `ENV_DEFAULTS`, profile runtime options,
simple env-file loading, persisted metadata, or profile creation. Its value is
the minimal object with `observations` (a supplied `status` is recomputed).
For example:

```sh
AIWF_ACTOR_IDENTITY='{"observations":[{"source":"actor","method":"self_report","agent":"codex","provider":"openai","model":"gpt-x"}]}' ./aiwf record --path <task> --kind validation --result pass --command '<executed check>'
```

Explicit writer input takes precedence over the process channel. Absence yields
unknown. The same input handling must cover every command/evidence writer
caller above, including automatic phase/finalize events. Profile variables
remain configured context even when a shell override supplies them. This
channel records the actor context of the event; it does not infer the identity
of every earlier code author or the review decision authority.

## Legacy compatibility and schema-aware migration

Normal legacy load/use/show retains existing profile resolution and neutral
defaults. No migration is required to stop execution-attribution promotion:
the v0.4 writer boundary applies with or without profile migration. New profile
creation writes actual runtime configuration (`AIWF_EVENT_LOG`) without seeding
the six deprecated identity-attribution keys.

The migration schema is the exact census-based key registry:

- Preserve `AIWF_EVENT_LOG`, including its current logging behavior.
- Remove the six `AI_AGENT_METADATA_ENV_MAP` keys because their only profile
  consumers are configured hints/legacy attribution, display, and metadata
  validation; describe each removed field's reclassification and reason.
- Preserve blank lines/comments and retained configuration as feasible; never
  touch `.env`, `.aiwf/metadata.local.env`, the pointer, other profiles, records,
  event rows, indexes, or manifests.

Migration targets the selected current profile, with an explicit profile name
option if supported. Validate profile name/pointer/path and repository boundary
before reading or writing. Use strict schema-aware parsing for migration:
malformed assignments, duplicate keys, ambiguous quoting/values, unsupported
key names (including unknown integration-like keys), and invalid known values
abort before mutation. Do not apply the legacy reader's ignored-line or
last-key-wins behavior to destructive cleanup. Preflight the complete plan,
then write the selected profile atomically; no partial rewrite is allowed.

Dry-run uses the identical plan and reports preserved/removed/reclassified
fields and reasons, plus historical evidence unchanged, without creating
directories/reports/events or changing files. A profile already without the
deprecated keys returns `No migration required.` and preserves bytes/mtime on
all repeated runs. Failure likewise preserves bytes/mtime and evidence. These
boundaries must be tested with profile symlinks/path escape and unknown keys,
not merely happy-path key removal.

## Dataset/report compatibility view

Dataset version 2 adds a per-event qualified identity view while retaining the
existing task/workflow fields. Each event view retains its observations and
configured context separately. Evidence classes distinguish
`runtime_observed`, `host_observed`, `self_reported`, `configured_legacy`,
`unknown`, and `conflicting`; a matching host+runtime set may carry both observed
classes rather than selecting a winner. An event with conflicting observations
is classified conflicting even if one observation claims a host/runtime source.

For all legacy `ai_agent` and legacy `model` input, use `configured_legacy` and
`execution_attribution: unverified`. Specifically, `ai_agent.source=profile`
retains configured metadata/source and may be labeled `legacy_profile`, but
never becomes observed. Older `explicit_env`/shell values are likewise
configured evidence without stronger proof. Preserve configured confidence as
legacy data only. New v0.4 configured context alone supplies no actor observation
and therefore has unknown execution identity.

Do not merge events or evidence classes by model name. Metadata report must
separate configured coverage from identity coverage/class distributions.
Experiment export must qualify legacy event context and current-env fallback
as configured context and include event identity views rather than infer a
single actual model from configured consensus. `package-records` embeds the
same versioned dataset; its raw event export continues preserving evidence.

Model comparison, failure-rate, or compliance analysis may use observed
identity only with the evidence-source limitation disclosed. Self-reported
identity supports qualified exploratory work. Configured legacy evidence is
historical configuration context and cannot be used as verified model execution
or model-ranking evidence.

## Implementation and acceptance boundary

Order: census/contract -> shared v0.4 writer -> compatibility/profile separation
-> strict migration -> dataset/report/experiment normalization -> protocol/docs
and release validation. Task 1 changes this document only, with no runtime
semantic changes.

Required meaningful verification includes both writer types and all producing
commands, no identity, self-report, host/runtime observation, matching/disjoint
observations, conflict preservation, malformed optional identity, profile-only
identity remaining unknown, old profile use/load/check, strict/idempotent
migration and dry-run tree snapshots, mixed legacy/new dataset/export and
package dataset, and unknown/conflicting identity with successful finalize-ready
and finalize. Existing authority/freshness/artifact/index/manifest/read-only
regressions must retain their behavior. Run the full unit suite after integration.
Finally compare a real legacy archive read-only before/after: historical file
hashes must remain unchanged and previously valid workflow records must not gain
identity-driven invalidity.
