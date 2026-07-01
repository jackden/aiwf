#!/usr/bin/env python3
"""
AI Workflow helper.

Repo-local tool for deterministic AI workflow governance.

Commands:
  new-task <name>
  relocate [--dry-run|--apply] [--legacy-docs]
  upgrade --check|--dry-run|--apply --source <repo> [--migrate-legacy-docs]
  dataset export --output <path> [--format json]
  backfill <path>
  check [--path <path>]
  check --path <task_dir> --finalize-ready
  guard --pre-edit --path <task_dir>
  sync-index --path <task_dir>
  doctor --path <path>
  finalize --path <path>
  transition --path <task_dir> --to <phase>
  record --path <task_dir> --kind <kind> [kind-specific args]
  next-id [--date <YYYYMMDD>]
  knowledge-template <pattern|bug|decision> <name>
  export-json [--path <path>]
  export-experiment --path <task_dir>
  report [--path <path>] [--format json|markdown]
  metadata show|status|init|validate|allowed-values|report
  metadata profile create|list|use|current|show
  agents print-block
  agents check [--path AGENTS.md]
  agents install [--path AGENTS.md] --yes

Safety:
- Writes only workflow files under the repo root, `.aiwf/`, and `.aiwf/docs/knowledge/*`.
- Does not run pytest, DUT, destructive, mkfs, RAID, firmware, power-cycle, or git commands.
- Does not delete existing workflow records. Failed new-task creation may roll back
  files and directories created by the failed command before a valid task exists.
- Does not overwrite existing files unless --update-existing is passed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence

AIWF_BIN_DIR = Path(__file__).resolve().parent
if str(AIWF_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(AIWF_BIN_DIR))

from lib.package_core import (  # noqa: E402
    build_manifest_row,
    compute_sha256,
    file_size,
    git_mode,
    manifest_row_tsv,
    normalize_package_path,
    sha256_bytes,
    stable_json_dump,
    stable_sort,
    stable_tsv_dump,
)

AI_DATE_RE = re.compile(r"^ai_(\d{8})$")
TASK_DIR_RE = re.compile(r"^\d{3}_[a-z0-9][a-z0-9_]*$")
SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
TASK_ID_NAME_RE = re.compile(r"^(\d{3})_([a-z0-9][a-z0-9_]*)$")
TASK_NAME_VALUE_RE = re.compile(r"^[a-z0-9_]+$")
TASK_ID_VALUE_RE = re.compile(r"^\d{3}$")

LEGACY_SCHEMA_VERSION = "legacy"
SCHEMA_V12 = "ai-workflow-v1.2"
SCHEMA_V13 = "ai-workflow-v1.3"
SCHEMA_V14 = "ai-workflow-v1.4"
SCHEMA_V15 = "ai-workflow-v1.5"
SCHEMA_V16 = "ai-workflow-v1.6"
CURRENT_SCHEMA_VERSION = SCHEMA_V16
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_V12, SCHEMA_V13, SCHEMA_V14, SCHEMA_V15, SCHEMA_V16}
WORKFLOW_PROTOCOL_VERSION = "1.7.8"
AIWF_TOOL_VERSION = "1.7.9"
AIWF_EVENT_SCHEMA_VERSION = "aiwf-event-v0.1"
AIWF_EVIDENCE_EVENT_SCHEMA_VERSION = "aiwf-event-v0.2"
AIWF_EXPERIMENT_SCHEMA_VERSION = "aiwf-experiment-v0.1"
AIWF_DATASET_SCHEMA_VERSION = "1"
AIWF_PACKAGE_RECORDS_MANIFEST_SCHEMA_VERSION = "aiwf-package-records-manifest-v1"
AIWF_PACKAGE_RECORDS_PACKAGE_VERSION = "1"
AIWF_PACKAGE_RECORDS_HASH_POLICY = "aiwf-package-records-v1"
AIWF_PACKAGE_RECORDS_MANIFEST_SCHEMA_FILENAME = "package_records_manifest_v1.schema.json"
AIWF_PACKAGE_RECORDS_MANIFEST_ERROR = "AIWF-PKG-MANIFEST-001"
AIWF_PACKAGE_RECORDS_DATASET_PATH = "dataset/aiwf_dataset.json"
AIWF_PACKAGE_RECORDS_ROOT_DIR = "aiwf-records-package"
AIWF_PACKAGE_RECORDS_REDACTION_PROFILES = {"safe", "internal", "none"}
ALLOWED_STATUS = {"draft", "active", "review", "blocked", "done", "archived"}
ALLOWED_PRIORITY = {"P0", "P1", "P2", "P3"}
ALLOWED_RISK = {"low", "medium", "high", "critical"}
ALLOWED_REVIEW_STATUS = {"pending", "pass", "fail", "not_required"}
ALLOWED_WORKFLOW_PHASE = {"init", "implementation", "validation", "review", "finalized"}
ALLOWED_PHASE_TRANSITIONS = {
    "init": {"implementation"},
    "implementation": {"validation"},
    "validation": {"review"},
    "review": {"implementation", "validation"},
    "finalized": set(),
}
ALLOWED_RECORD_KIND = {"validation", "review", "fix", "safety_ack"}
VALIDATION_RECORD_RESULTS = {"pass", "fail", "not_run"}
REVIEW_RECORD_RESULTS = {"pass", "fail", "not_required"}
FINAL_REVIEW_RESULTS = {"pass", "not_required"}
TASK_METADATA_SCHEMA: dict[str, dict[str, Any]] = {
    "schema_version": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "enum": SUPPORTED_SCHEMA_VERSIONS, "default": CURRENT_SCHEMA_VERSION},
    "task_id": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "pattern": r"^\d{3}$"},
    "task_name": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "pattern": r"^[a-z0-9_]+$"},
    "title": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS},
    "status": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "enum": ALLOWED_STATUS, "default": "draft"},
    "priority": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "enum": ALLOWED_PRIORITY, "default": "P1"},
    "risk": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "enum": ALLOWED_RISK, "default": "medium"},
    "owner": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "default": "ai-agent"},
    "reviewer": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "default": "human"},
    "review_status": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "enum": ALLOWED_REVIEW_STATUS, "default": "pending"},
    "blocked_reason": {"type": "nullable_string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "default": None},
    "workflow_phase": {"type": "string", "required_in": {SCHEMA_V13, SCHEMA_V14, SCHEMA_V15, SCHEMA_V16}, "enum": ALLOWED_WORKFLOW_PHASE, "default": "implementation"},
    "phase_entered_at": {"type": "nullable_string", "required_in": {SCHEMA_V16}, "default": None},
    "finalized_at": {"type": "nullable_string", "required_in": {SCHEMA_V15, SCHEMA_V16}, "default": None},
    "finalized_by": {"type": "nullable_string", "required_in": {SCHEMA_V15, SCHEMA_V16}, "default": None},
    "review_not_required_reason": {"type": "nullable_string", "required_in": {SCHEMA_V16}, "default": None},
    "created_at": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS},
    "updated_at": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS},
    "project": {"type": "string", "required_in": SUPPORTED_SCHEMA_VERSIONS, "default": "generic"},
    "parent_task": {
        "type": "nullable_string",
        "required_in": SUPPORTED_SCHEMA_VERSIONS,
        "default": None,
        "pattern": r"^\d{3}$",
    },
    "related_tasks": {
        "type": "list",
        "required_in": SUPPORTED_SCHEMA_VERSIONS,
        "default": [],
        "item_pattern": r"^\d{3}$",
    },
    "blocked_by": {
        "type": "list",
        "required_in": SUPPORTED_SCHEMA_VERSIONS,
        "default": [],
        "item_pattern": r"^\d{3}$",
    },
    "supersedes": {
        "type": "list",
        "required_in": SUPPORTED_SCHEMA_VERSIONS,
        "default": [],
        "item_pattern": r"^\d{3}$",
    },
    "related_files": {
        "type": "list",
        "required_in": SUPPORTED_SCHEMA_VERSIONS,
        "default": [],
        "item_kind": "repo_relative_path",
    },
    "tags": {
        "type": "list",
        "required_in": SUPPORTED_SCHEMA_VERSIONS,
        "default": [],
        "item_pattern": r"^[a-z0-9][a-z0-9_-]*$",
    },
}
METADATA_LIST_FIELDS = {name for name, spec in TASK_METADATA_SCHEMA.items() if spec.get("type") == "list"}
AGENT_REVIEW_CANONICAL_FILE = "review_agent.md"
AGENT_REVIEW_LEGACY_FILE = "review_codex.md"
AGENT_REVIEW_FILES = (AGENT_REVIEW_CANONICAL_FILE, AGENT_REVIEW_LEGACY_FILE)
FINALIZE_REQUIRED_FILE_GROUPS = (
    ("task.md",),
    ("task_record.md",),
    ("self_validation.md",),
    AGENT_REVIEW_FILES,
    ("review_final.md",),
)
PRE_EDIT_REQUIRED_FILE_GROUPS = (
    ("task.md",),
    ("agent.md",),
    ("task_record.md",),
    ("self_validation.md",),
    AGENT_REVIEW_FILES,
    ("review_final.md",),
)
FINALIZE_REQUIRED_FILES = tuple(group[0] for group in FINALIZE_REQUIRED_FILE_GROUPS)
PRE_EDIT_REQUIRED_FILES = tuple(group[0] for group in PRE_EDIT_REQUIRED_FILE_GROUPS)
LEGACY_REQUIRED_FILES = (AGENT_REVIEW_LEGACY_FILE,)
FINALIZE_MANIFEST_FILES = tuple(dict.fromkeys((*FINALIZE_REQUIRED_FILES, *LEGACY_REQUIRED_FILES)))
DATASET_RECORD_REFERENCE_FILES = tuple(dict.fromkeys((*FINALIZE_REQUIRED_FILES, *LEGACY_REQUIRED_FILES)))
REQUIRED_DOC_SECTIONS: dict[str, tuple[str, ...]] = {
    "task_record.md": ("Changed", "Why"),
    "self_validation.md": ("Commands Run", "Results"),
    "review_final.md": ("Final Result",),
}
DEFAULT_TEMPLATE_SECTION_BODIES: dict[str, dict[str, str]] = {
    "task.md": {
        "Background": "Describe the source of this task, including bug report, review finding, historical record, or user request.",
        "Problem": "Describe the concrete problem to solve. Keep it verifiable.",
        "Goal": "Describe the expected final state.",
        "Risk": "Document any hardware, storage, DUT, RAID, filesystem, or workflow risk.",
    },
    "task_record.md": {
        "Changed": "Describe what was changed.",
        "Why": "Describe why these changes were needed.",
        "Compatibility Notes": "Describe compatibility impact and legacy behavior.",
        "Files Modified": "List changed files.",
        "Known Limitations": "Document limitations, skipped checks, or unavailable git/DUT validation.",
        "Future Improvement": "Document follow-up improvements.",
    },
    "self_validation.md": {
        "Commands Run": "Record exact commands if executed.",
        "Known Limitations": "Document skipped checks and environment limitations.",
    },
    "review_agent.md": {
        "Code / Documentation Quality": "Pending.",
        "Logic Coverage": "Pending.",
        "Safety Impact": "Pending.",
        "v1.1 Completeness": "Pending.",
        "Remaining Risks": "Pending.",
    },
    "review_codex.md": {
        "Code / Documentation Quality": "Pending.",
        "Logic Coverage": "Pending.",
        "Safety Impact": "Pending.",
        "v1.1 Completeness": "Pending.",
        "Remaining Risks": "Pending.",
    },
    "review_final.md": {
        "Review Scope": "Pending.",
        "Key Findings": "Pending.",
        "Blocking Issues": "Pending.",
    },
}
DATASET_ALLOWED_TASK_FIELDS = (
    "task_id",
    "date",
    "project",
    "workflow_phase_from_metadata",
    "event_count",
    "event_types",
    "event_type_counts",
    "has_task_artifact",
    "has_task_record_artifact",
    "has_self_validation_artifact",
    "has_validation_event",
    "has_agent_review_artifact",
    "has_review_codex_artifact",
    "has_review_final_artifact",
    "has_review_event",
    "has_finalize_event",
    "related_task_count",
    "blocked_by_count",
    "supersedes_count",
    "export_warnings",
)
DATASET_FINALIZE_EVENT_TYPES = frozenset({"finalize_success", "finalize_failed", "finalize_blocked"})
DATASET_RECORDED_EVENT_SUFFIX = "_recorded"
EXPORT_CAPABILITIES = {
    "deterministic_finalize": True,
    "structured_diagnostics": True,
    "rule_system": True,
    "finalize_idempotent": True,
}
ENV_DEFAULTS = {
    "AIWF_EVENT_LOG": "0",
    "AIWF_WORKFLOW_MODE": "unknown",
    "AIWF_MODEL_NAME": "unknown",
    "AIWF_MODEL_CLASS": "unknown",
    "AIWF_MODEL_PROVIDER": "unknown",
    "AIWF_ACTOR": "tool",
}
AIWF_PROFILE_RUNTIME_OPTIONS = ("AIWF_EVENT_LOG",)
METADATA_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
AI_AGENT_METADATA_DEFAULT = {
    "tool": "unknown",
    "provider": "unknown",
    "model_name": "unknown",
    "reasoning_effort": "unknown",
    "source": "unknown",
    "confidence": "low",
}
AI_AGENT_METADATA_ENV_MAP = {
    "tool": "AIWF_AGENT_TOOL",
    "provider": "AIWF_MODEL_PROVIDER",
    "model_name": "AIWF_MODEL_NAME",
    "reasoning_effort": "AIWF_REASONING_EFFORT",
    "source": "AIWF_METADATA_SOURCE",
    "confidence": "AIWF_METADATA_CONFIDENCE",
}
METADATA_FIELDS = (
    "tool",
    "provider",
    "model_name",
    "reasoning_effort",
    "source",
    "confidence",
)
METADATA_DISPLAY_FIELDS = (
    ("Tool", "tool"),
    ("Provider", "provider"),
    ("Model", "model_name"),
    ("Reasoning Effort", "reasoning_effort"),
    ("Source", "source"),
    ("Confidence", "confidence"),
)
ENV_KEY_TO_METADATA_FIELD = {env_key: field for field, env_key in AI_AGENT_METADATA_ENV_MAP.items()}
METADATA_INIT_FIELD_HELP_TOKENS = frozenset({"?", ":list", ":help", "L", "l"})
METADATA_INIT_ALL_HELP_TOKENS = frozenset({":all"})
ALLOWED_METADATA_SOURCE = {"unknown", "explicit_env", "shell_env", "local_env", "profile"}
ALLOWED_METADATA_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_METADATA_PROVIDER = {
    "unknown",
    "openai",
    "anthropic",
    "google",
    "azure",
    "aws",
    "bedrock",
    "vertex",
    "deepseek",
    "mistral",
    "cohere",
    "groq",
    "together",
    "fireworks",
    "perplexity",
    "xai",
    "openrouter",
    "huggingface",
    "ollama",
    "qwen",
    "alibaba",
    "baidu",
    "zhipu",
    "moonshot",
    "minimax",
    "yi",
    "bytedance",
    "volcengine",
    "siliconflow",
    "github",
    "local",
    "self_hosted",
    "custom",
    "other",
}
ALLOWED_METADATA_TOOL = {
    "unknown",
    "codex",
    "chatgpt",
    "copilot",
    "cursor",
    "cline",
    "claude_code",
    "aider",
    "continue",
    "openhands",
    "opencode",
    "roo_code",
    "windsurf",
    "trae",
    "kiro",
    "devin",
    "gemini_cli",
    "qoder",
    "custom_agent",
    "script",
    "manual",
    "other",
}
ALLOWED_METADATA_REASONING_EFFORT = {"unknown", "none", "low", "medium", "high", "veryhigh", "auto"}
METADATA_VALUE_REGISTRY: dict[str, dict[str, Any]] = {
    "tool": {
        "default": "unknown",
        "values": ALLOWED_METADATA_TOOL,
        "description": "AI tool or agent used to perform the work.",
        "notes": "Use `custom_agent`, `script`, `manual`, or `other` for unlisted tools.",
        "value_descriptions": {
            "unknown": "Tool is not known.",
            "codex": "OpenAI Codex / Codex CLI / Codex agent.",
            "chatgpt": "ChatGPT UI.",
            "copilot": "GitHub Copilot or Copilot agent.",
            "cursor": "Cursor.",
            "cline": "Cline.",
            "claude_code": "Claude Code.",
            "aider": "Aider.",
            "continue": "Continue.",
            "openhands": "OpenHands.",
            "opencode": "OpenCode.",
            "roo_code": "Roo Code.",
            "windsurf": "Windsurf.",
            "trae": "Trae.",
            "kiro": "Kiro.",
            "devin": "Devin.",
            "gemini_cli": "Gemini CLI.",
            "qoder": "Qoder.",
            "custom_agent": "Self-developed or wrapped agent.",
            "script": "Script-generated metadata.",
            "manual": "Manually authored by a human.",
            "other": "Other unlisted tool.",
        },
    },
    "provider": {
        "default": "unknown",
        "values": ALLOWED_METADATA_PROVIDER,
        "description": "Model provider or model serving source.",
        "notes": "Use `local`, `self_hosted`, `custom`, or `other` for unlisted providers.",
        "value_descriptions": {
            "unknown": "Provider is not known.",
            "openai": "OpenAI.",
            "anthropic": "Anthropic Claude.",
            "google": "Google AI / Gemini.",
            "azure": "Azure OpenAI.",
            "aws": "AWS AI services.",
            "bedrock": "AWS Bedrock.",
            "vertex": "Google Vertex AI.",
            "deepseek": "DeepSeek.",
            "mistral": "Mistral.",
            "cohere": "Cohere.",
            "groq": "Groq.",
            "together": "Together AI.",
            "fireworks": "Fireworks AI.",
            "perplexity": "Perplexity.",
            "xai": "xAI / Grok.",
            "openrouter": "OpenRouter.",
            "huggingface": "Hugging Face.",
            "ollama": "Ollama local inference.",
            "qwen": "Qwen model family.",
            "alibaba": "Alibaba Cloud / Qwen provider context.",
            "baidu": "Baidu / Wenxin.",
            "zhipu": "Zhipu / GLM.",
            "moonshot": "Moonshot / Kimi.",
            "minimax": "MiniMax.",
            "yi": "01.AI / Yi.",
            "bytedance": "ByteDance AI services.",
            "volcengine": "Volcengine / Doubao provider context.",
            "siliconflow": "SiliconFlow.",
            "github": "GitHub Models.",
            "local": "Local model runtime.",
            "self_hosted": "Self-hosted model service.",
            "custom": "Custom provider.",
            "other": "Other unlisted provider.",
        },
    },
    "model_name": {
        "default": "unknown",
        "values": None,
        "description": "Free-text model name, for example `deepseek-v4-flash`.",
        "notes": "No allow-list is used because model names change frequently.",
    },
    "reasoning_effort": {
        "default": "unknown",
        "values": ALLOWED_METADATA_REASONING_EFFORT,
        "description": "Recorded reasoning effort setting. This is not a model quality score.",
        "value_descriptions": {
            "unknown": "Not recorded or unknown.",
            "none": "Tool/model has no reasoning effort concept.",
            "low": "Low reasoning effort.",
            "medium": "Medium reasoning effort.",
            "high": "High reasoning effort.",
            "auto": "Tool or provider decides automatically.",
        },
    },
    "source": {
        "default": "explicit_env",
        "values": ALLOWED_METADATA_SOURCE,
        "description": "Where AIWF obtained the metadata.",
        "value_descriptions": {
            "unknown": "Source cannot be determined.",
            "explicit_env": "User explicitly configured metadata through env/init.",
            "shell_env": "Read from current shell environment variables.",
            "local_env": "Read from `.aiwf/metadata.local.env`.",
            "profile": "Read from `.aiwf/metadata_profiles/<name>.env`.",
        },
    },
    "confidence": {
        "default": "medium",
        "values": ALLOWED_METADATA_CONFIDENCE,
        "description": "Confidence in metadata attribution, not model quality or answer confidence.",
        "value_descriptions": {
            "low": "Metadata attribution is uncertain.",
            "medium": "Metadata attribution has a clear source but is not fully verified.",
            "high": "Metadata attribution was explicitly configured or profile-backed.",
        },
    },
}
METADATA_FALLBACK_HINTS = {
    "provider": "Fallback values for unlisted providers: local, self_hosted, custom, other",
    "tool": "Fallback values for unlisted tools: custom_agent, script, manual, other",
}
METADATA_VALIDATION_DIAGNOSTICS = {
    "AIWF-META-001": "Invalid metadata source",
    "AIWF-META-002": "Invalid confidence value",
    "AIWF-META-003": "Invalid provider value",
    "AIWF-META-004": "Invalid agent tool value",
    "AIWF-META-012": "Invalid reasoning_effort value",
}
AGENTS_BLOCK_BEGIN = "<!-- AIWF:BEGIN -->"
AGENTS_BLOCK_END = "<!-- AIWF:END -->"


@dataclass(frozen=True)
class WriteResult:
    path: Path
    action: str


@dataclass(frozen=True)
class PackageRecordsTaskCandidate:
    path: Path
    source_path: str
    package_path: str
    date: str
    task_id: str
    task_name: str
    metadata: dict[str, Any]
    metadata_valid: bool
    task_md_missing: bool


@dataclass(frozen=True)
class RelocationEntry:
    label: str
    source: Path
    destination: Path
    group: str
    exists: bool
    destination_exists: bool


@dataclass(frozen=True)
class AIWFLayoutConfig:
    aiwf_layout_version: int = 1
    docs_root: str = "docs"
    record_root: str = "docs"
    event_log: str = ".aiwf/events/events.jsonl"
    legacy_enabled: bool = True

    @property
    def records_root(self) -> str:
        return self.record_root


@dataclass(frozen=True)
class AIWFConfig:
    layout: AIWFLayoutConfig


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    message: str


@dataclass(frozen=True)
class Diagnostic:
    severity: str  # info | warn | error
    code: str
    path: str
    message: str
    suggested_fix: str
    blocker: bool = False


@dataclass(frozen=True)
class MetadataValueSource:
    value: str
    source_layer: str
    source_path: str


class SyncIndexError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DateValidationError(ValueError):
    def __init__(self, code: str, message: str, suggested_fix: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggested_fix = suggested_fix


DIAGNOSTICS: dict[str, dict[str, str]] = {
    "AIWF-META-001": {"severity": "error", "message": "Front matter exists but metadata cannot be parsed.", "suggested_fix": "Use valid YAML front matter with key: value pairs and close it with ---."},
    "AIWF-META-LEGACY-001": {"severity": "warn", "message": "Legacy task without metadata front matter.", "suggested_fix": "Keep as legacy, or add metadata front matter if this task is migrated."},
    "AIWF-META-002": {"severity": "error", "message": "Missing metadata field: {field}.", "suggested_fix": "Add `{field}` to task.md front matter."},
    "AIWF-META-003": {"severity": "error", "message": "Unsupported schema_version: {schema_version}.", "suggested_fix": "Use one of: legacy, ai-workflow-v1.2, ai-workflow-v1.3, ai-workflow-v1.4, ai-workflow-v1.5, ai-workflow-v1.6."},
    "AIWF-META-004": {"severity": "error", "message": "Invalid format for field {field}: {value}.", "suggested_fix": "Update `{field}` to match required format."},
    "AIWF-META-005": {"severity": "error", "message": "task_id mismatch: expected {expected}.", "suggested_fix": "Set `task_id: \"{expected}\"` to match the directory prefix."},
    "AIWF-META-006": {"severity": "error", "message": "task_name mismatch: expected {expected}.", "suggested_fix": "Set `task_name: \"{expected}\"` to match the directory suffix."},
    "AIWF-META-007": {"severity": "error", "message": "Invalid value for field {field}: {value}.", "suggested_fix": "Use one of: {allowed}."},
    "AIWF-META-008": {"severity": "error", "message": "status done requires review_status to be pass or not_required.", "suggested_fix": "Set review_status to pass/not_required, then run finalize."},
    "AIWF-META-009": {"severity": "error", "message": "Invalid metadata list item for field {field}: {value}.", "suggested_fix": "Use canonical item format for this metadata field."},
    "AIWF-META-010": {"severity": "error", "message": "Invalid task reference for field {field}: {value}.", "suggested_fix": "Use canonical task id format, for example: 014."},
    "AIWF-META-011": {"severity": "error", "message": "Invalid repo-relative path for field {field}: {value}.", "suggested_fix": "Use a repo-relative path without absolute path or '..'."},
    "AIWF-DATE-001": {"severity": "error", "message": "new-task date {date} does not match today {today}.", "suggested_fix": "Omit --date for normal new tasks, or use --allow-non-today-date for explicit historical/recovery work."},
    "AIWF-DATE-002": {"severity": "error", "message": "Invalid {field} format: {date}.", "suggested_fix": "Use YYYYMMDD format, for example: 20260603."},
    "AIWF-DATE-003": {"severity": "error", "message": "Invalid {field} value: {date}.", "suggested_fix": "Use a valid calendar date in YYYYMMDD format, for example: 20260603."},
    "AIWF-META-REF-001": {"severity": "error", "message": "Invalid task reference input for field {field}: {value}.", "suggested_fix": "Use a task id such as 014, or a task directory name such as 014_task_name."},
    "AIWF-PHASE-001": {"severity": "error", "message": "status done requires workflow_phase finalized.", "suggested_fix": "Do not set status done manually; run `ai_workflow.py finalize --path <task_dir>`."},
    "AIWF-PHASE-002": {"severity": "error", "message": "Illegal phase transition: {from_phase} -> {to_phase}.", "suggested_fix": "Use an allowed transition from the current phase."},
    "AIWF-PHASE-004": {"severity": "error", "message": "Phase transition attempted after finalized.", "suggested_fix": "Do not transition finalized tasks."},
    "AIWF-BLOCK-001": {"severity": "error", "message": "status blocked requires blocked_by or blocked_reason.", "suggested_fix": "Add blocked_by task id(s) or provide a non-empty blocked_reason."},
    "AIWF-META-OK": {"severity": "info", "message": "Metadata validated for schema {schema_version}.", "suggested_fix": ""},
    "AIWF-FILE-001": {"severity": "error", "message": "Missing required file: {filename}.", "suggested_fix": "Create `{filename}` in the task directory before finalize."},
    "AIWF-FILE-002": {"severity": "warn", "message": "Missing v1.1 file: {filename}.", "suggested_fix": "Create `{filename}` via ai_workflow new-task/backfill templates."},
    "AIWF-FILE-OK": {"severity": "info", "message": "{filename} exists.", "suggested_fix": ""},
    "AIWF-AGENTS-006": {"severity": "error", "message": "managed AIWF block template is missing.", "suggested_fix": "Create `.aiwf/templates/AGENTS.block.md` from the canonical managed block source."},
    "AIWF-AGENTS-OUTDATED": {"severity": "error", "message": "managed AIWF block does not match the template source.", "suggested_fix": "Run `./aiwf agents install --path AGENTS.md --yes` to rewrite the managed block from `.aiwf/templates/AGENTS.block.md`."},
    "AIWF-GUARD-PASS": {"severity": "info", "message": "task is open for pre-edit work", "suggested_fix": ""},
    "AIWF-GUARD-001": {"severity": "error", "message": "task path does not exist", "suggested_fix": "Provide a valid .aiwf/records/ai_YYYYMMDD/NNN_task_name path."},
    "AIWF-GUARD-002": {"severity": "error", "message": "required AIWF artifact missing", "suggested_fix": "Create the missing task artifacts before beginning pre-edit work."},
    "AIWF-GUARD-003": {"severity": "error", "message": "task metadata cannot be parsed", "suggested_fix": "Fix task.md front matter so metadata can be parsed."},
    "AIWF-GUARD-004": {"severity": "error", "message": "task is closed and cannot be used for pre-edit work", "suggested_fix": "Use an open task or create a follow-up task before editing."},
    "AIWF-GUARD-900": {"severity": "error", "message": "invalid guard invocation", "suggested_fix": "Run: ./aiwf guard --pre-edit --path <task_path>"},
    "AIWF-SECTION-001": {"severity": "error", "message": "{filename} missing required section: {section}.", "suggested_fix": "Add section header `{section}` to `{filename}`."},
    "AIWF-SECTION-OK": {"severity": "info", "message": "{filename} contains required section: {section}.", "suggested_fix": ""},
    "AIWF-PLACEHOLDER-001": {"severity": "error", "message": "Placeholder marker detected in {filename}: `{marker}`.", "suggested_fix": "Replace placeholder content in required sections with final task-specific text."},
    "AIWF-PLACEHOLDER-OK": {"severity": "info", "message": "No placeholder markers detected in required documents.", "suggested_fix": ""},
    "AIWF-PATH-001": {"severity": "error", "message": "Task directory does not exist.", "suggested_fix": "Provide a valid .aiwf/records/ai_YYYYMMDD/NNN_task path."},
    "AIWF-PATH-002": {"severity": "error", "message": "Path is not a task-specific directory.", "suggested_fix": "Use a path like .aiwf/records/ai_YYYYMMDD/NNN_task_name."},
    "AIWF-REVIEW-002": {"severity": "error", "message": "Finalize requires review_status to be pass or not_required.", "suggested_fix": "Set review_status to pass/not_required before finalize."},
    "AIWF-PATH-010": {"severity": "error", "message": "Missing validation pass before finalize.", "suggested_fix": "Record validation pass evidence before finalize."},
    "AIWF-PATH-011": {"severity": "error", "message": "Review fail without fix.", "suggested_fix": "Record a fix after the latest failed review before finalize."},
    "AIWF-PATH-012": {"severity": "error", "message": "Fix without re-validation pass.", "suggested_fix": "Record a validation pass after each fix before finalize."},
    "AIWF-PATH-013": {"severity": "error", "message": "Metadata finalized without finalize_success event.", "suggested_fix": "Finalize via `ai_workflow.py finalize --path <task_dir>` to generate finalize_success."},
    "AIWF-PATH-014": {"severity": "error", "message": "Latest effective review decision is missing, stale, or not final before finalize.", "suggested_fix": "Record a fresh review decision (pass/not_required) after the latest fail/fix."},
    "AIWF-PATH-015": {
        "severity": "error",
        "message": "Finalized artifact changed after finalize.",
        "suggested_fix": "Revert post-finalize edits, or use a controlled amend/reopen command if supported. Do not manually edit finalized task artifacts.",
    },
    "AIWF-PATH-016": {"severity": "error", "message": "Event log malformed or unreadable for v1.6 finalize.", "suggested_fix": "Repair .aiwf/events/events.jsonl malformed lines before finalize."},
    "AIWF-PATH-017": {"severity": "error", "message": "review not_required missing reason.", "suggested_fix": "Set review_not_required_reason with explicit rationale."},
    "AIWF-PATH-018": {"severity": "error", "message": "metadata review_status is inconsistent with latest review decision.", "suggested_fix": "Align metadata review_status with the latest review_recorded result."},
    "AIWF-PATH-019": {"severity": "error", "message": "Post-finalize evidence event detected: {event_type}.", "suggested_fix": "Remove post-finalize evidence events or reopen work in a new task before finalize."},
    "AIWF-PATH-020": {"severity": "error", "message": "Pending validation residue detected in closure artifact: {filename} / {section}.", "suggested_fix": "Replace pending validation template text with actual validation outcome or explicit skipped rationale before finalize."},
    "AIWF-PATH-021": {"severity": "error", "message": "Pending review residue detected in closure artifact: {filename} / {section}.", "suggested_fix": "Replace pending review template text with the actual review decision and reviewer attribution before finalize."},
    "AIWF-PATH-022": {"severity": "error", "message": "Default template residue detected in {filename} / {section}.", "suggested_fix": "Replace the generated template text in this required section with task-specific closure evidence before finalize."},
    "AIWF-PATH-023": {"severity": "error", "message": "Acceptance Criteria section exists but no item has a closure decision.", "suggested_fix": "Update each acceptance-criteria item to a closure state such as passed, deferred, or not applicable before finalize."},
    "AIWF-PATH-024": {"severity": "error", "message": "Acceptance Criteria contain unresolved or blocking closure states.", "suggested_fix": "Resolve unchecked/failed/blocked acceptance-criteria items, or mark them deferred/not applicable with rationale before finalize."},
    "AIWF-META-PROFILE-004": {"severity": "warn", "message": "Current profile points to a missing profile file.", "suggested_fix": "Run `./aiwf metadata profile list`, or `./aiwf metadata profile use <existing-profile>`, or create the missing profile."},
    "AIWF-META-RUNTIME-001": {"severity": "error", "message": "Invalid runtime metadata option {option}: {value}.", "suggested_fix": "Use `AIWF_EVENT_LOG=1` to enable event logging or `AIWF_EVENT_LOG=0` to disable it."},
    "AIWF-FINALIZED-001": {"severity": "warn", "message": "Finalized task modified after finalized_at.", "suggested_fix": "Review post-finalize edits and rerun check/doctor before additional changes."},
    "AIWF-FINALIZED-002": {"severity": "error", "message": "Finalized task cannot accept new evidence records.", "suggested_fix": "Do not run record on finalized tasks; create a new follow-up task for additional evidence."},
    "AIWF-DOCTOR-001": {"severity": "error", "message": "doctor only supports task-specific directory paths.", "suggested_fix": "Use a path like .aiwf/records/ai_YYYYMMDD/NNN_task_name."},
    "AIWF-FINALIZE-001": {"severity": "info", "message": "Task already finalized. No changes applied.", "suggested_fix": ""},
    "AIWF-FINALIZE-002": {"severity": "error", "message": "finalize only supports task-specific directory paths.", "suggested_fix": "Use a path like .aiwf/records/ai_YYYYMMDD/NNN_task_name."},
    "AIWF-FINALIZE-OK": {"severity": "info", "message": "finalize completed; metadata updated to done/finalized.", "suggested_fix": ""},
    "INDEX_ENTRY_MISSING": {"severity": "error", "message": "index.md entry missing for task `{task}`.", "suggested_fix": "Run: ./aiwf sync-index --path {task_path}"},
    "INDEX_STATUS_STALE": {"severity": "error", "message": "index.md status stale for task `{task}`: expected `{expected}`, found `{actual}`.", "suggested_fix": "Run: ./aiwf sync-index --path {task_path}"},
    "INDEX_STATUS_INVALID_DONE": {"severity": "error", "message": "index.md cannot show Done when task finalized_at is null.", "suggested_fix": "Run finalize to set finalized_at, or sync index after correcting metadata."},
    "AIWF-SYNC-001": {"severity": "error", "message": "sync-index only supports task-specific directory paths.", "suggested_fix": "Use a path like .aiwf/records/ai_YYYYMMDD/NNN_task_name."},
    "AIWF-SYNC-OK": {"severity": "info", "message": "index.md status synchronized from task metadata.", "suggested_fix": ""},
}


def today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def parse_aiwf_date_arg(raw: str, *, field: str = "date") -> str:
    text = str(raw).strip()
    if not re.fullmatch(r"\d{8}", text):
        diag = DIAGNOSTICS["AIWF-DATE-002"]
        raise DateValidationError(
            "AIWF-DATE-002",
            diag["message"].format(field=field, date=text),
            diag["suggested_fix"],
        )
    try:
        dt.datetime.strptime(text, "%Y%m%d")
    except ValueError:
        diag = DIAGNOSTICS["AIWF-DATE-003"]
        raise DateValidationError(
            "AIWF-DATE-003",
            diag["message"].format(field=field, date=text),
            diag["suggested_fix"],
        )
    return text


def _print_date_validation_error(exc: DateValidationError) -> None:
    print(f"[ERROR] {exc.code}")
    print(exc.message)
    print("Suggested Fix:")
    print(exc.suggested_fix)


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_simple_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        out[key] = _strip_env_quotes(value.strip())
    return out


def load_aiwf_env(root: Path) -> dict[str, str]:
    resolved = resolve_aiwf_runtime_options_with_sources(root)
    return {key: value.value for key, value in resolved.items()}


def _metadata_local_env_path(root: Path) -> Path:
    return root / ".aiwf" / "metadata.local.env"


def _metadata_current_profile_path(root: Path) -> Path:
    return root / ".aiwf" / "metadata.current"


def _metadata_profiles_dir(root: Path) -> Path:
    return root / ".aiwf" / "metadata_profiles"


def _metadata_profile_path(root: Path, name: str) -> Path:
    return _metadata_profiles_dir(root) / f"{name}.env"


def _extract_ai_agent_metadata_fields(values: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for field, env_key in AI_AGENT_METADATA_ENV_MAP.items():
        raw_value = values.get(env_key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            out[field] = value
    return out


def _normalize_ai_agent_metadata(metadata: dict[str, str]) -> dict[str, str]:
    normalized = dict(AI_AGENT_METADATA_DEFAULT)
    for field in AI_AGENT_METADATA_DEFAULT:
        raw_value = metadata.get(field)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            normalized[field] = value
    return normalized


def _active_metadata_profile_name(root: Path) -> Optional[str]:
    path = _metadata_current_profile_path(root)
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8", errors="replace").strip()
    if not value:
        return None
    if not METADATA_PROFILE_NAME_RE.match(value):
        return None
    return value


def _metadata_source_record(value: str, layer: str, path: str) -> MetadataValueSource:
    return MetadataValueSource(value=value, source_layer=layer, source_path=path)


def _metadata_source_label(record: MetadataValueSource) -> str:
    if record.source_layer == "shell_env":
        return "shell env"
    if record.source_layer == "local_env":
        return ".aiwf/metadata.local.env"
    return record.source_path


def _metadata_sources_are_uniform(sources: Mapping[str, MetadataValueSource]) -> bool:
    values = list(sources.values())
    if not values:
        return True
    first = (values[0].source_layer, values[0].source_path)
    return all((value.source_layer, value.source_path) == first for value in values[1:])


def _metadata_resolution_summary(
    resolved: Mapping[str, MetadataValueSource],
    *,
    active_profile_exists: bool,
) -> str:
    if not _metadata_sources_are_uniform(resolved):
        return "effective metadata has mixed sources."
    source = next(iter(resolved.values()))
    if source.source_layer == "active_profile":
        return "effective metadata comes from active profile."
    if source.source_layer == "local_env":
        if active_profile_exists:
            return "effective metadata is overridden by .aiwf/metadata.local.env."
        return "effective metadata comes from .aiwf/metadata.local.env."
    if source.source_layer == "shell_env":
        return "effective metadata is overridden by shell env."
    if source.source_layer == "default":
        return "effective metadata comes from built-in defaults."
    return f"effective metadata comes from {_metadata_source_label(source)}."


def _print_effective_metadata_with_sources(
    resolved: Mapping[str, MetadataValueSource],
    *,
    active_profile: Optional[str],
    active_profile_exists: bool,
    include_active_profile: bool = True,
    include_resolution: bool = True,
    include_source: bool = True,
    include_values: bool = True,
    indent: str = "",
) -> None:
    uniform = _metadata_sources_are_uniform(resolved)
    if include_active_profile:
        print(f"{indent}Active Profile: {active_profile or 'none'}")
    if include_resolution:
        print(f"{indent}Resolution: {_metadata_resolution_summary(resolved, active_profile_exists=active_profile_exists)}")
    if uniform and include_source:
        source = next(iter(resolved.values()))
        print(f"{indent}Source: {_metadata_source_label(source)}")
    if not include_values:
        return
    for label, field in METADATA_DISPLAY_FIELDS:
        record = resolved[field]
        print(f"{indent}{'  ' if indent == '' else ''}{label}: {record.value}")
        if not uniform:
            print(f"{indent}{'    ' if indent == '' else '  '}from: {_metadata_source_label(record)}")


def _current_profile_state(root: Path) -> dict[str, Any]:
    current_path = _metadata_current_profile_path(root)
    if not current_path.exists():
        return {
            "name": None,
            "display_name": "unknown",
            "path": None,
            "exists": False,
            "dangling": False,
            "configured": False,
        }
    raw = current_path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return {
            "name": None,
            "display_name": "unknown",
            "path": None,
            "exists": False,
            "dangling": False,
            "configured": False,
        }
    if not METADATA_PROFILE_NAME_RE.match(raw):
        return {
            "name": None,
            "display_name": raw,
            "path": None,
            "exists": False,
            "dangling": False,
            "configured": True,
        }
    profile_path = _metadata_profile_path(root, raw)
    return {
        "name": raw,
        "display_name": raw,
        "path": profile_path,
        "exists": profile_path.exists(),
        "dangling": not profile_path.exists(),
        "configured": True,
    }


def resolve_ai_agent_metadata_with_sources(
    root: Path,
    *,
    shell_env: Optional[Mapping[str, str]] = None,
) -> dict[str, MetadataValueSource]:
    resolved = {
        field: _metadata_source_record(AI_AGENT_METADATA_DEFAULT[field], "default", "built-in default")
        for field in AI_AGENT_METADATA_DEFAULT
    }

    profile_state = _current_profile_state(root)
    if profile_state.get("name") and profile_state.get("exists") and profile_state.get("path") is not None:
        profile_data = _parse_simple_env_file(profile_state["path"])
        for field, value in _extract_ai_agent_metadata_fields(profile_data).items():
            resolved[field] = _metadata_source_record(value, "active_profile", rel(root, profile_state["path"]))

    local_path = _metadata_local_env_path(root)
    local_data = _parse_simple_env_file(local_path)
    for field, value in _extract_ai_agent_metadata_fields(local_data).items():
        resolved[field] = _metadata_source_record(value, "local_env", rel(root, local_path))

    shell_source = shell_env if shell_env is not None else os.environ
    shell_fields = _extract_ai_agent_metadata_fields({key: str(value) for key, value in shell_source.items()})
    for field, value in shell_fields.items():
        resolved[field] = _metadata_source_record(value, "shell_env", "environment")

    return {field: _metadata_source_record(value.value, value.source_layer, value.source_path) for field, value in resolved.items()}


def resolve_ai_agent_metadata(root: Path, shell_env: Optional[dict[str, str]] = None) -> dict[str, str]:
    resolved = resolve_ai_agent_metadata_with_sources(root, shell_env=shell_env)
    return _normalize_ai_agent_metadata({field: record.value for field, record in resolved.items()})


def resolve_aiwf_runtime_options_with_sources(
    root: Path,
    *,
    shell_env: Optional[Mapping[str, str]] = None,
) -> dict[str, MetadataValueSource]:
    resolved = {
        name: _metadata_source_record(str(default), "default", "built-in default")
        for name, default in ENV_DEFAULTS.items()
    }

    profile_state = _current_profile_state(root)
    if profile_state.get("name") and profile_state.get("exists") and profile_state.get("path") is not None:
        profile_data = _parse_simple_env_file(profile_state["path"])
        for option in AIWF_PROFILE_RUNTIME_OPTIONS:
            if option in profile_data:
                resolved[option] = _metadata_source_record(profile_data[option], "active_profile", rel(root, profile_state["path"]))

    env_path = root / ".env"
    env_data = _parse_simple_env_file(env_path)
    for option in ENV_DEFAULTS:
        if option in env_data:
            resolved[option] = _metadata_source_record(env_data[option], "repo_env", rel(root, env_path))

    shell_source = shell_env if shell_env is not None else os.environ
    for option in ENV_DEFAULTS:
        if option in shell_source:
            resolved[option] = _metadata_source_record(str(shell_source[option]), "shell_env", "environment")

    return resolved


def format_allowed_values(field: str) -> str:
    registry = METADATA_VALUE_REGISTRY[field]
    values = registry.get("values")
    if values is None:
        return "free text"
    return ", ".join(sorted(values))


def metadata_field_default(field: str) -> str:
    return str(METADATA_VALUE_REGISTRY[field]["default"])


def metadata_allowed_values_hint(field: str) -> str:
    return f"Run `./aiwf metadata allowed-values --field {field}` to see valid values and descriptions."


def _metadata_prompt_defaults(*, source_default: Optional[str] = None) -> dict[str, str]:
    defaults = {field: metadata_field_default(field) for field in METADATA_FIELDS}
    if source_default is not None:
        defaults["source"] = source_default
    return defaults


def _seed_profile_metadata_defaults(resolved: dict[str, str]) -> dict[str, str]:
    seeded = _metadata_prompt_defaults(source_default="profile")
    for field in ("tool", "provider", "model_name", "reasoning_effort"):
        value = str(resolved.get(field, "")).strip()
        if value and value != AI_AGENT_METADATA_DEFAULT[field]:
            seeded[field] = value
    confidence = str(resolved.get("confidence", "")).strip()
    if confidence and confidence in ALLOWED_METADATA_CONFIDENCE and confidence != AI_AGENT_METADATA_DEFAULT["confidence"]:
        seeded["confidence"] = confidence
    return seeded


def _metadata_invalid_value_message(field: str, value: str) -> str:
    lines = [
        f"Invalid {field} value: {value or '(empty)'}",
        "Suggested Fix:",
        f"Use one of the allowed {field} values. Run:",
        f"  ./aiwf metadata allowed-values --field {field}",
    ]
    fallback = METADATA_FALLBACK_HINTS.get(field)
    if fallback:
        lines.append(fallback)
    return "\n".join(lines)


def _metadata_validation_errors(metadata: dict[str, str]) -> list[tuple[str, str]]:
    diagnostics: list[tuple[str, str]] = []

    source = str(metadata.get("source", "unknown")).strip()
    if source not in ALLOWED_METADATA_SOURCE:
        diagnostics.append(("AIWF-META-001", _metadata_invalid_value_message("source", source)))

    confidence = str(metadata.get("confidence", "low")).strip()
    if confidence not in ALLOWED_METADATA_CONFIDENCE:
        diagnostics.append(("AIWF-META-002", _metadata_invalid_value_message("confidence", confidence)))

    provider = str(metadata.get("provider", "unknown")).strip()
    if provider not in ALLOWED_METADATA_PROVIDER:
        diagnostics.append(("AIWF-META-003", _metadata_invalid_value_message("provider", provider)))

    tool = str(metadata.get("tool", "unknown")).strip()
    if tool not in ALLOWED_METADATA_TOOL:
        diagnostics.append(("AIWF-META-004", _metadata_invalid_value_message("tool", tool)))

    reasoning_effort = str(metadata.get("reasoning_effort", "unknown")).strip()
    if reasoning_effort not in ALLOWED_METADATA_REASONING_EFFORT:
        diagnostics.append(("AIWF-META-012", _metadata_invalid_value_message("reasoning_effort", reasoning_effort)))

    return diagnostics


def _runtime_option_validation_errors(options: Mapping[str, MetadataValueSource]) -> list[tuple[str, str]]:
    diagnostics: list[tuple[str, str]] = []
    event_log = options.get("AIWF_EVENT_LOG")
    if event_log is not None and event_log.value not in {"0", "1"}:
        spec = DIAGNOSTICS["AIWF-META-RUNTIME-001"]
        diagnostics.append(
            (
                "AIWF-META-RUNTIME-001",
                "\n".join(
                    [
                        spec["message"].format(option="AIWF_EVENT_LOG", value=event_log.value or "(empty)"),
                        "Suggested Fix:",
                        spec["suggested_fix"],
                    ]
                ),
            )
        )
    return diagnostics


def _dangling_profile_warning(root: Path) -> Optional[str]:
    profile_state = _current_profile_state(root)
    if not profile_state.get("dangling"):
        return None
    return "\n".join(
        [
            "[WARN] AIWF-META-PROFILE-004",
            DIAGNOSTICS["AIWF-META-PROFILE-004"]["message"],
            "Suggested Fix:",
            DIAGNOSTICS["AIWF-META-PROFILE-004"]["suggested_fix"],
        ]
    )


def _profile_metadata_values(path: Path) -> dict[str, str]:
    return _normalize_ai_agent_metadata(_extract_ai_agent_metadata_fields(_parse_simple_env_file(path)))


def _profile_runtime_options(path: Path) -> dict[str, str]:
    data = _parse_simple_env_file(path)
    return {name: data[name] for name in AIWF_PROFILE_RUNTIME_OPTIONS if name in data}


def _metadata_to_env_lines(metadata: dict[str, str]) -> list[str]:
    normalized = _normalize_ai_agent_metadata(metadata)
    lines = []
    for field, env_key in AI_AGENT_METADATA_ENV_MAP.items():
        lines.append(f"{env_key}={normalized[field]}")
    return lines


def _is_metadata_init_field_help_token(value: str) -> bool:
    return value.strip() in METADATA_INIT_FIELD_HELP_TOKENS


def _is_metadata_init_all_help_token(value: str) -> bool:
    return value.strip() in METADATA_INIT_ALL_HELP_TOKENS


def _print_metadata_allowed_values_for_env_key(env_key: str) -> None:
    field = ENV_KEY_TO_METADATA_FIELD.get(env_key)
    if field is None:
        print(f"Allowed values unavailable for {env_key}.")
        return
    spec = METADATA_VALUE_REGISTRY[field]
    print(f"Allowed values for {env_key}:")
    values = spec.get("values")
    if values is None:
        print("  This field may be free-form or model-specific.")
    else:
        for value in sorted(values):
            print(f"  {value}")
    print("Description:")
    print(f"  {spec.get('description')}")
    if spec.get("notes"):
        print("Notes:")
        print(f"  {spec.get('notes')}")
    print("Current default:")
    print(f"  {spec.get('default')}")


def _prompt_metadata_value(prompt: str, default: str) -> str:
    while True:
        try:
            raw = input(f"{prompt} [{default}] (? for allowed values): ")
        except EOFError:
            return default
        value = raw.strip()
        if _is_metadata_init_field_help_token(value):
            _print_metadata_allowed_values_for_env_key(prompt)
            continue
        if _is_metadata_init_all_help_token(value):
            print_metadata_allowed_values()
            continue
        return value or default


def print_metadata_allowed_values(field: Optional[str] = None) -> int:
    fields = [field] if field else list(METADATA_FIELDS)
    for name in fields:
        if name not in METADATA_VALUE_REGISTRY:
            print(f"[ERROR] unknown metadata field: {name}")
            print("Allowed fields: " + ", ".join(METADATA_VALUE_REGISTRY.keys()))
            return 2
        spec = METADATA_VALUE_REGISTRY[name]
        print(name)
        print(f"  default: {spec.get('default')}")
        print(f"  description: {spec.get('description')}")
        if spec.get("notes"):
            print(f"  notes: {spec.get('notes')}")
        values = spec.get("values")
        if values is None:
            print("  allowed: free text")
        else:
            print("  allowed:")
            value_descriptions = spec.get("value_descriptions", {})
            for value in sorted(values):
                desc = value_descriptions.get(value)
                if desc:
                    print(f"    {value:<14} - {desc}")
                else:
                    print(f"    {value}")
        print()
    return 0


def _iter_all_task_dirs(root: Path) -> list[Path]:
    config = load_aiwf_config(root)
    roots: list[Path] = [get_record_root(root)]
    if config.layout.legacy_enabled:
        legacy_root = (root / "docs").resolve()
        if legacy_root != roots[0]:
            roots.append(legacy_root)
    task_dirs: list[Path] = []
    seen: set[str] = set()
    for records_root in roots:
        if not records_root.exists():
            continue
        for ai_dir in sorted(p for p in records_root.iterdir() if p.is_dir() and AI_DATE_RE.match(p.name)):
            for task_dir in sorted(p for p in ai_dir.iterdir() if p.is_dir() and TASK_DIR_RE.match(p.name)):
                key = str(task_dir.resolve())
                if key in seen:
                    continue
                seen.add(key)
                task_dirs.append(task_dir)
    return task_dirs


def _extract_event_ai_agent(event: dict[str, Any]) -> dict[str, str]:
    if isinstance(event.get("ai_agent"), dict):
        metadata = {
            "tool": str(event["ai_agent"].get("tool", "unknown")),
            "provider": str(event["ai_agent"].get("provider", "unknown")),
            "model_name": str(event["ai_agent"].get("model_name", "unknown")),
            "reasoning_effort": str(event["ai_agent"].get("reasoning_effort", "unknown")),
            "source": str(event["ai_agent"].get("source", "unknown")),
            "confidence": str(event["ai_agent"].get("confidence", "low")),
        }
        return _normalize_ai_agent_metadata(metadata)
    model_payload = event.get("model")
    if isinstance(model_payload, dict):
        return _normalize_ai_agent_metadata(
            {
                "provider": str(model_payload.get("provider", "unknown")),
                "model_name": str(model_payload.get("name", "unknown")),
            }
        )
    return dict(AI_AGENT_METADATA_DEFAULT)


def aiwf_event_logging_enabled(env: dict[str, str]) -> bool:
    value = str(env.get("AIWF_EVENT_LOG", "")).strip().lower()
    return value in {"1", "true", "yes"}


def build_event_context(env: dict[str, str]) -> dict[str, Any]:
    return {
        "workflow_mode": str(env.get("AIWF_WORKFLOW_MODE", "unknown")),
        "actor": str(env.get("AIWF_ACTOR", "tool")),
        "model": {
            "name": str(env.get("AIWF_MODEL_NAME", "unknown")),
            "class": str(env.get("AIWF_MODEL_CLASS", "unknown")),
            "provider": str(env.get("AIWF_MODEL_PROVIDER", "unknown")),
        },
    }


def make_diagnostic(code: str, path: str, *, blocker: bool = False, severity: Optional[str] = None, **fmt: Any) -> Diagnostic:
    spec = DIAGNOSTICS[code]
    sev = severity or spec["severity"]
    message = spec["message"].format(**fmt) if fmt else spec["message"]
    suggested_fix = spec["suggested_fix"].format(**fmt) if spec["suggested_fix"] else ""
    return Diagnostic(sev, code, path, message, suggested_fix, blocker=blocker)


def _schema_field_order() -> list[str]:
    return list(TASK_METADATA_SCHEMA.keys())


def _field_required_in_version(field_name: str, schema_version: str) -> bool:
    required_in = TASK_METADATA_SCHEMA[field_name].get("required_in", set())
    return schema_version in required_in


def normalize_name(name: str) -> str:
    value = name.strip().replace("-", "_").replace(" ", "_").lower()
    value = re.sub(r"[^a-z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value or not SAFE_NAME_RE.match(value):
        raise ValueError(f"invalid task/name after normalization: {name!r} -> {value!r}")
    return value


def find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for p in [cur, *cur.parents]:
        if (p / ".aiwf" / "config.yaml").exists() or (p / ".aiwf" / "bin" / "ai_workflow.py").exists():
            return p
    raise SystemExit("ERROR: cannot find repo root. Run under a repo containing .aiwf/config.yaml or .aiwf/bin/ai_workflow.py.")


def _parse_aiwf_layout_config(text: str) -> dict[str, str]:
    section: Optional[str] = None
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            if ":" not in line:
                raise SystemExit(f"ERROR: invalid .aiwf/config.yaml line: {line}")
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "layout":
                section = "layout"
                continue
            if key not in {"aiwf_layout_version", "docs_root", "record_root", "event_log", "legacy_enabled"}:
                continue
            if key in {"aiwf_layout_version", "legacy_enabled"} and not value:
                raise SystemExit(f"ERROR: {key} in .aiwf/config.yaml cannot be empty.")
            values[key] = value
            continue
        if section != "layout":
            raise SystemExit("ERROR: invalid .aiwf/config.yaml structure; expected `layout:` section.")
        stripped = line.strip()
        if ":" not in stripped:
            raise SystemExit(f"ERROR: invalid .aiwf/config.yaml line: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key != "records_root":
            continue
        if not value:
            raise SystemExit("ERROR: records_root in .aiwf/config.yaml cannot be empty.")
        values[key] = value
    return values


def _validate_repo_relative_dir(value: str, *, label: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    if not normalized:
        raise SystemExit(f"ERROR: {label} in .aiwf/config.yaml cannot be empty.")
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in normalized:
        raise SystemExit(f"ERROR: {label} must be a repo-relative directory path.")
    if normalized.startswith("/"):
        raise SystemExit(f"ERROR: {label} must be repo-relative, not absolute.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", normalized):
        raise SystemExit(f"ERROR: {label} contains unsupported characters.")
    return normalized


def _validate_repo_relative_file(value: str, *, label: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    if not normalized:
        raise SystemExit(f"ERROR: {label} in .aiwf/config.yaml cannot be empty.")
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in normalized:
        raise SystemExit(f"ERROR: {label} must be a repo-relative path.")
    if normalized.startswith("/"):
        raise SystemExit(f"ERROR: {label} must be repo-relative, not absolute.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", normalized):
        raise SystemExit(f"ERROR: {label} contains unsupported characters.")
    return normalized


def _parse_boolish(value: str, *, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"ERROR: invalid boolean for {label} in .aiwf/config.yaml: {value}")


def default_aiwf_layout_config() -> AIWFLayoutConfig:
    return AIWFLayoutConfig()


def load_aiwf_config(repo_root: Path) -> AIWFConfig:
    config_path = repo_root / ".aiwf" / "config.yaml"
    if not config_path.exists():
        return AIWFConfig(layout=default_aiwf_layout_config())
    content = config_path.read_text(encoding="utf-8", errors="replace")
    parsed = _parse_aiwf_layout_config(content)
    version_raw = parsed.get("aiwf_layout_version", "1").strip()
    try:
        version = int(version_raw)
    except ValueError as exc:
        raise SystemExit(f"ERROR: invalid .aiwf/config.yaml aiwf_layout_version: {version_raw}") from exc
    if version >= 2 or any(key in parsed for key in ("docs_root", "record_root", "event_log", "legacy_enabled")):
        docs_root = _validate_repo_relative_dir(parsed.get("docs_root", ".aiwf/docs"), label="docs_root")
        record_root = _validate_repo_relative_dir(parsed.get("record_root", ".aiwf/records"), label="record_root")
        event_log = _validate_repo_relative_file(parsed.get("event_log", ".aiwf/events/events.jsonl"), label="event_log")
        legacy_enabled = _parse_boolish(parsed.get("legacy_enabled", "true"), label="legacy_enabled")
        return AIWFConfig(
            layout=AIWFLayoutConfig(
                aiwf_layout_version=2,
                docs_root=docs_root,
                record_root=record_root,
                event_log=event_log,
                legacy_enabled=legacy_enabled,
            )
        )
    records_root = _validate_repo_relative_dir(parsed.get("records_root", "docs"), label="records_root")
    return AIWFConfig(layout=AIWFLayoutConfig(aiwf_layout_version=1, docs_root="docs", record_root=records_root))


def resolve_records_root(repo_root: Path) -> Path:
    config = load_aiwf_config(repo_root)
    return (repo_root / config.layout.record_root).resolve()


def get_aiwf_root(repo_root: Path) -> Path:
    return (repo_root / ".aiwf").resolve()


def get_aiwf_docs_root(repo_root: Path) -> Path:
    return (repo_root / load_aiwf_config(repo_root).layout.docs_root).resolve()


def get_record_root(repo_root: Path) -> Path:
    return resolve_records_root(repo_root)


def get_event_log_path(repo_root: Path) -> Path:
    return (repo_root / load_aiwf_config(repo_root).layout.event_log).resolve()


def get_aiwf_runtime_path(repo_root: Path) -> Path:
    config = load_aiwf_config(repo_root)
    if config.layout.aiwf_layout_version >= 2:
        return (repo_root / ".aiwf" / "bin" / "ai_workflow.py").resolve()
    return (repo_root / "tools" / "ai_workflow.py").resolve()


def get_aiwf_agents_block_template_path(repo_root: Path) -> Path:
    return (get_aiwf_root(repo_root) / "templates" / "AGENTS.block.md").resolve()


def resolve_ai_day_dir(repo_root: Path, date: str) -> Path:
    return get_record_root(repo_root) / f"ai_{date}"


def resolve_task_dir(repo_root: Path, date: str, task_name: str) -> Path:
    ai_day_dir = resolve_ai_day_dir(repo_root, date)
    task_id = next_task_id(ai_day_dir)
    return ai_day_dir / f"{task_id}_{normalize_name(task_name)}"


def aiwf_agents_managed_block(repo_root: Optional[Path] = None) -> str:
    repo_root = find_repo_root(Path.cwd()) if repo_root is None else repo_root
    template_path = get_aiwf_agents_block_template_path(repo_root)
    if not template_path.exists():
        raise SystemExit(f"ERROR: missing AIWF managed block template: {rel(repo_root, template_path)}")
    return template_path.read_text(encoding="utf-8", errors="replace")


def _resolve_agents_path(root: Path, raw_path: str) -> Path:
    target = Path(raw_path)
    target = (root / target).resolve() if not target.is_absolute() else target.resolve()
    return target


def _find_agents_block_bounds(text: str) -> tuple[Optional[int], Optional[int]]:
    begin = text.find(AGENTS_BLOCK_BEGIN)
    end = text.find(AGENTS_BLOCK_END)
    if begin < 0 and end < 0:
        return None, None
    if begin < 0 or end < 0 or end < begin:
        return begin if begin >= 0 else None, end if end >= 0 else None
    end += len(AGENTS_BLOCK_END)
    return begin, end


def agents_print_block_command(root: Path) -> int:
    print(aiwf_agents_managed_block(root), end="")
    return 0


def agents_check_command(root: Path, raw_path: str) -> int:
    target = _resolve_agents_path(root, raw_path)
    if not target.exists():
        print("[ERROR] AIWF-AGENTS-001")
        print(f"{rel(root, target)}: AGENTS.md file not found.")
        return 2
    content = target.read_text(encoding="utf-8", errors="replace")
    begin, end = _find_agents_block_bounds(content)
    if begin is None and end is None:
        print("[ERROR] AIWF-AGENTS-002")
        print(f"{rel(root, target)}: managed AIWF block is missing.")
        return 2
    if begin is None or end is None:
        print("[ERROR] AIWF-AGENTS-003")
        print(f"{rel(root, target)}: managed AIWF block is incomplete.")
        return 2
    managed_block = content[begin:end]
    template = aiwf_agents_managed_block(root).rstrip("\n")
    if managed_block.rstrip("\n") != template:
        print("[ERROR] AIWF-AGENTS-OUTDATED")
        print(f"{rel(root, target)}: managed AIWF block does not match .aiwf/templates/AGENTS.block.md.")
        return 2
    print("[INFO] AIWF-AGENTS-OK")
    print(f"{rel(root, target)}: AIWF managed block present and matches template.")
    return 0


def agents_install_command(root: Path, raw_path: str, yes: bool) -> int:
    if not yes:
        print("[ERROR] AIWF-AGENTS-900")
        print("agents install requires --yes to write AGENTS.md.")
        return 1
    target = _resolve_agents_path(root, raw_path)
    managed = aiwf_agents_managed_block(root).rstrip("\n")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(managed + "\n", encoding="utf-8")
        print(f"[INFO] installed managed block to {rel(root, target)} (created file)")
        return 0

    original = target.read_text(encoding="utf-8", errors="replace")
    begin, end = _find_agents_block_bounds(original)
    if begin is None and end is None:
        base = original.rstrip("\n")
        updated = f"{base}\n\n{managed}\n" if base else f"{managed}\n"
    elif begin is None or end is None:
        print("[ERROR] AIWF-AGENTS-003")
        print(f"{rel(root, target)}: managed AIWF block is incomplete.")
        return 2
    else:
        updated = f"{original[:begin].rstrip()}\n\n{managed}\n{original[end:].lstrip()}"
        if not updated.endswith("\n"):
            updated += "\n"
    target.write_text(updated, encoding="utf-8")
    print(f"[INFO] installed managed block to {rel(root, target)}")
    return 0


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_write_path(root: Path, path: Path) -> None:
    try:
        rp = path.resolve().relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"ERROR: refusing to write outside repo root: {path}")
    parts = rp.parts
    records_root_rel = get_record_root(root).relative_to(root.resolve()).parts
    if len(parts) >= len(records_root_rel) and parts[: len(records_root_rel)] == records_root_rel:
        return
    aiwf_root_rel = get_aiwf_root(root).relative_to(root.resolve()).parts
    if len(parts) >= len(aiwf_root_rel) and parts[: len(aiwf_root_rel)] == aiwf_root_rel:
        return
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] == "knowledge":
        return
    raise SystemExit(f"ERROR: refusing to write outside the configured records root, .aiwf/, or .aiwf/docs/knowledge: {rp}")


def write_file(root: Path, path: Path, content: str, update_existing: bool = False) -> WriteResult:
    safe_write_path(root, path)
    ensure_dir(path.parent)
    if path.exists() and not update_existing:
        return WriteResult(path, "exists")
    action = "updated" if path.exists() else "created"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return WriteResult(path, action)


def _artifact_group_label(group: Sequence[str]) -> str:
    if len(group) == 1:
        return group[0]
    return f"{group[0]} (legacy alias: {', '.join(group[1:])})"


def _resolve_artifact_group(task_dir: Path, group: Sequence[str]) -> tuple[str, Path, bool]:
    for filename in group:
        path = task_dir / filename
        if path.exists():
            return filename, path, filename != group[0]
    return group[0], task_dir / group[0], False


def _resolved_required_artifacts(
    task_dir: Path,
    groups: Sequence[Sequence[str]],
) -> list[tuple[str, Path, bool, Sequence[str]]]:
    return [(*_resolve_artifact_group(task_dir, group), group) for group in groups]


def _agent_review_artifact_path(task_dir: Path) -> tuple[Optional[str], Optional[Path]]:
    filename, path, _legacy = _resolve_artifact_group(task_dir, AGENT_REVIEW_FILES)
    if path.exists():
        return filename, path
    return None, None


def _has_agent_review_artifact(task_dir: Path) -> bool:
    _filename, path = _agent_review_artifact_path(task_dir)
    return path is not None


def safe_dataset_output_path(root: Path, path: Path) -> None:
    try:
        rp = path.resolve().relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"ERROR: refusing to write outside repo root: {path}")

    if rp.name in {"task.md", "task_record.md", "self_validation.md", "review_agent.md", "review_codex.md", "review_final.md"}:
        raise SystemExit(f"ERROR: refusing to overwrite workflow evidence artifact: {rp}")
    if rp == Path("README.md"):
        raise SystemExit("ERROR: refusing to overwrite README.md during dataset export")
    if rp == Path(".aiwf") / "events" / "events.jsonl":
        raise SystemExit("ERROR: refusing to overwrite .aiwf/events/events.jsonl during dataset export")
    if len(rp.parts) >= 3 and rp.parts[0] == ".aiwf" and rp.parts[1] == "docs" and rp.parts[2] == "releases":
        raise SystemExit(f"ERROR: refusing to overwrite release artifact path: {rp}")
    if len(rp.parts) >= 3 and rp.parts[0] == ".aiwf" and rp.parts[1] == "records" and AI_DATE_RE.match(rp.parts[2]):
        raise SystemExit(f"ERROR: refusing to write dataset output inside workflow records: {rp}")


def _default_aiwf_layout_config_text() -> str:
    return "\n".join(
        [
            "aiwf_layout_version: 2",
            'docs_root: ".aiwf/docs"',
            'record_root: ".aiwf/records"',
            'event_log: ".aiwf/events/events.jsonl"',
            "legacy_enabled: true",
        ]
    ) + "\n"


def _is_aiwf_config_control_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return False
    if stripped == "layout:":
        return True
    for prefix in ("aiwf_layout_version:", "docs_root:", "record_root:", "event_log:", "legacy_enabled:", "records_root:"):
        if stripped.startswith(prefix):
            return True
    return False


def _merge_aiwf_config_text(base_text: str, existing_text: Optional[str]) -> str:
    merged_lines = base_text.rstrip("\n").splitlines()
    seen = set(merged_lines)
    if existing_text:
        for raw_line in existing_text.rstrip("\n").splitlines():
            if _is_aiwf_config_control_line(raw_line):
                continue
            if raw_line not in seen:
                merged_lines.append(raw_line)
                seen.add(raw_line)
    return "\n".join(merged_lines) + "\n"


def _prepare_aiwf_config(root: Path) -> tuple[str, str]:
    aiwf_root = get_aiwf_root(root)
    config_path = aiwf_root / "config.yaml"
    existing_config_text = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else None
    config_text = _merge_aiwf_config_text(_default_aiwf_layout_config_text(), existing_config_text)
    if not config_path.exists():
        config_action = "created"
    elif existing_config_text == config_text:
        config_action = "exists"
    else:
        config_action = "updated"
    return config_text, config_action


def _canonical_runtime_path(root: Path) -> Path:
    return get_aiwf_root(root) / "bin" / "ai_workflow.py"


def _canonical_runtime_exists(root: Path) -> bool:
    return _canonical_runtime_path(root).exists()


def _candidate_legacy_docs_relocation_paths(root: Path) -> list[RelocationEntry]:
    legacy_docs_root = root / "docs"
    destination_docs_root = get_aiwf_root(root) / "docs"
    destination_records_root = get_aiwf_root(root) / "records"

    def maybe_add(label: str, source: Path, destination: Path, group: str, entries: list[RelocationEntry]) -> None:
        if source.exists() or destination.exists():
            entries.append(
                RelocationEntry(
                    label=label,
                    source=source,
                    destination=destination,
                    group=group,
                    exists=source.exists(),
                    destination_exists=destination.exists(),
                )
            )

    entries: list[RelocationEntry] = []
    for filename in (
        "workflow_protocol.md",
        "diagnostics.md",
        "repo_boundary.md",
        "adoption_guide.md",
        "reporting.md",
        "agent_integration.md",
        "metadata.md",
        "packaging.md",
    ):
        maybe_add(
            f"docs/{filename}",
            legacy_docs_root / filename,
            destination_docs_root / filename,
            "docs",
            entries,
        )

    for dirname in ("agent_rules", "releases", "examples", "knowledge"):
        maybe_add(
            f"docs/{dirname}",
            legacy_docs_root / dirname,
            destination_docs_root / dirname,
            "docs",
            entries,
        )

    seen_dates: set[str] = set()
    for scan_root in (legacy_docs_root, destination_records_root):
        if not scan_root.exists():
            continue
        for candidate in sorted(p for p in scan_root.iterdir() if p.is_dir() and AI_DATE_RE.match(p.name)):
            if candidate.name in seen_dates:
                continue
            seen_dates.add(candidate.name)
            maybe_add(
                f"records/{candidate.name}",
                legacy_docs_root / candidate.name,
                destination_records_root / candidate.name,
                "records",
                entries,
            )

    return entries


def _relocation_report_text(root: Path, *, entries: Sequence[dict[str, Any]], config_action: str, event_log_action: str, dry_run: bool) -> str:
    moved_docs = [entry for entry in entries if entry["group"] == "docs" and entry["action"] == "moved"]
    moved_records = [entry for entry in entries if entry["group"] == "records" and entry["action"] == "moved"]
    moved_runtime = [entry for entry in entries if entry["group"] == "runtime" and entry["action"] == "moved"]
    skipped = [entry for entry in entries if entry["action"] in {"already_present", "skipped", "missing"}]
    warnings = [entry["message"] for entry in entries if entry.get("message")]

    lines = [
        "# AIWF Repo Boundary Relocation Report",
        "",
        f"- generated_at: {_now_iso_timestamp()}",
        f"- dry_run: {'true' if dry_run else 'false'}",
        f"- config_action: {config_action}",
        f"- event_log_action: {event_log_action}",
        "",
        "## Moved AIWF Docs",
    ]
    if moved_docs:
        lines.extend(f"- {entry['source']} -> {entry['destination']}" for entry in moved_docs)
    else:
        lines.append("- None")
    lines.extend(["", "## Moved AIWF Records"])
    if moved_records:
        lines.extend(f"- {entry['source']} -> {entry['destination']}" for entry in moved_records)
    else:
        lines.append("- None")
    lines.extend(["", "## Moved Runtime Tool"])
    if moved_runtime:
        lines.extend(f"- {entry['source']} -> {entry['destination']}" for entry in moved_runtime)
    else:
        lines.append("- None")
    lines.extend(["", "## Skipped Paths"])
    if skipped:
        lines.extend(f"- {entry['source']} -> {entry['destination']} ({entry['action']})" for entry in skipped)
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings"])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Summary",
            f"- docs_moved: {len(moved_docs)}",
            f"- records_moved: {len(moved_records)}",
            f"- runtime_moved: {len(moved_runtime)}",
            f"- skipped: {len(skipped)}",
        ]
    )
    return "\n".join(lines) + "\n"


def relocate_command(root: Path, dry_run: bool, *, legacy_docs: bool = False) -> int:
    entries = _candidate_legacy_docs_relocation_paths(root) if legacy_docs else []
    aiwf_root = get_aiwf_root(root)
    config_path = aiwf_root / "config.yaml"
    config_text, config_action = _prepare_aiwf_config(root)

    event_log_path = aiwf_root / "events" / "events.jsonl"
    event_log_action = "exists" if event_log_path.exists() else "created"

    action_entries: list[dict[str, Any]] = []
    for entry in entries:
        source_rel = rel(root, entry.source)
        destination_rel = rel(root, entry.destination)
        action = "missing"
        message = ""
        if entry.exists and entry.destination_exists:
            action = "skipped"
            message = "destination already exists"
        elif entry.exists:
            if dry_run:
                action = "would_move"
            else:
                ensure_dir(entry.destination.parent)
                shutil.move(str(entry.source), str(entry.destination))
                action = "moved"
        elif entry.destination_exists:
            action = "already_present"
            message = "already relocated"
        action_entries.append(
            {
                "label": entry.label,
                "group": entry.group,
                "source": source_rel,
                "destination": destination_rel,
                "action": action,
                "message": message,
            }
        )

    if dry_run:
        print("[INFO] AIWF-RELOCATE-DRY-RUN")
        if not legacy_docs:
            print("Legacy docs migration disabled by default. Use --legacy-docs to inspect root docs/ migration.")
        print("Planned relocations:")
        for item in action_entries:
            if item["action"] == "would_move":
                print(f"- {item['source']} -> {item['destination']}")
        print("Skipped paths:")
        skipped_items = [item for item in action_entries if item["action"] in {"already_present", "skipped", "missing"}]
        if skipped_items:
            for item in skipped_items:
                detail = item["message"] or item["action"]
                print(f"- {item['source']} -> {item['destination']} ({detail})")
        else:
            print("- None")
        return 0

    ensure_dir(aiwf_root)
    ensure_dir(aiwf_root / "docs")
    ensure_dir(aiwf_root / "records")
    ensure_dir(aiwf_root / "events")
    ensure_dir(aiwf_root / "bin")
    ensure_dir(aiwf_root / "migrations")

    if config_action != "exists":
        config_path.write_text(config_text, encoding="utf-8")
    if not event_log_path.exists():
        event_log_path.write_text("", encoding="utf-8")

    report_text = _relocation_report_text(root, entries=action_entries, config_action=config_action, event_log_action=event_log_action, dry_run=False)
    report_name = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}_repo_boundary_relocation.md"
    report_path = aiwf_root / "migrations" / report_name
    report_path.write_text(report_text, encoding="utf-8")

    print("[INFO] AIWF-RELOCATE-OK")
    print(f"{rel(root, report_path)}: migration report written.")
    if not legacy_docs:
        print("- legacy docs migration skipped by default")
    for item in action_entries:
        if item["action"] == "moved":
            print(f"- moved {item['source']} -> {item['destination']}")
    if config_action != "exists":
        print(f"- config {config_action}: {rel(root, config_path)}")
    if event_log_action != "exists":
        print(f"- event log {event_log_action}: {rel(root, event_log_path)}")
    return 0


def _read_version_constant(path: Path, symbol: str) -> Optional[str]:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"(?m)^\s*{re.escape(symbol)}\s*=\s*[\"']([^\"']+)[\"']\s*$", content)
    return match.group(1) if match else None


def _upgrade_source_requirements(source_root: Path) -> list[tuple[str, Path]]:
    return [
        ("aiwf", source_root / "aiwf"),
        (".aiwf/bin/ai_workflow.py", source_root / ".aiwf" / "bin" / "ai_workflow.py"),
        (".aiwf/docs", source_root / ".aiwf" / "docs"),
    ]


def _upgrade_validate_source(source_root: Path) -> list[str]:
    blockers: list[str] = []
    if not source_root.exists():
        blockers.append(f"source path does not exist: {source_root}")
        return blockers
    if not source_root.is_dir():
        blockers.append(f"source path is not a directory: {source_root}")
        return blockers
    for label, path in _upgrade_source_requirements(source_root):
        if not path.exists():
            blockers.append(f"missing {label}: {rel(source_root, path)}")
    aiwf_entrypoint = source_root / "aiwf"
    if aiwf_entrypoint.exists() and not os.access(aiwf_entrypoint, os.X_OK):
        blockers.append(f"aiwf is not executable: {rel(source_root, aiwf_entrypoint)}")
    return blockers


def _upgrade_target_runtime_path(root: Path) -> Path:
    runtime_path = get_aiwf_runtime_path(root)
    if runtime_path.exists():
        return runtime_path
    fallback = root / "tools" / "ai_workflow.py"
    return fallback if fallback.exists() else runtime_path


def _upgrade_current_info(root: Path) -> dict[str, Any]:
    runtime_path = _upgrade_target_runtime_path(root)
    runtime_rel = rel(root, runtime_path) if runtime_path.exists() else "missing"
    tool_version = _read_version_constant(runtime_path, "AIWF_TOOL_VERSION") if runtime_path.exists() else None
    protocol_version = _read_version_constant(runtime_path, "WORKFLOW_PROTOCOL_VERSION") if runtime_path.exists() else None
    config = load_aiwf_config(root)
    records_root = get_record_root(root)
    return {
        "tool_version": tool_version or "unknown",
        "protocol_version": protocol_version or "unknown",
        "layout_version": config.layout.aiwf_layout_version,
        "runtime": runtime_rel,
        "records_root": rel(root, records_root),
    }


def _upgrade_source_info(source_root: Path) -> dict[str, Any]:
    runtime_path = source_root / ".aiwf" / "bin" / "ai_workflow.py"
    tool_version = _read_version_constant(runtime_path, "AIWF_TOOL_VERSION")
    protocol_version = _read_version_constant(runtime_path, "WORKFLOW_PROTOCOL_VERSION")
    return {
        "tool_version": tool_version or "unknown",
        "protocol_version": protocol_version or "unknown",
        "layout_version": 2,
        "runtime": ".aiwf/bin/ai_workflow.py",
        "records_root": ".aiwf/records",
    }


def _ensure_aiwf_upgrade_skeleton(root: Path) -> tuple[str, str]:
    aiwf_root = get_aiwf_root(root)
    ensure_dir(aiwf_root)
    ensure_dir(aiwf_root / "docs")
    ensure_dir(aiwf_root / "records")
    ensure_dir(aiwf_root / "events")
    ensure_dir(aiwf_root / "bin")
    ensure_dir(aiwf_root / "migrations")

    config_path = aiwf_root / "config.yaml"
    config_text, config_action = _prepare_aiwf_config(root)
    if config_action != "exists":
        config_path.write_text(config_text, encoding="utf-8")

    event_log_path = aiwf_root / "events" / "events.jsonl"
    event_log_action = "exists" if event_log_path.exists() else "created"
    if event_log_action != "exists":
        event_log_path.write_text("", encoding="utf-8")
    return config_action, event_log_action


def _copy_upgrade_artifacts(source_root: Path, target_root: Path) -> list[str]:
    copied: list[str] = []
    for rel_path in ("aiwf", ".aiwf/bin/ai_workflow.py", ".aiwf/docs"):
        source = source_root / rel_path
        destination = target_root / rel_path
        if source.resolve() == destination.resolve():
            continue
        ensure_dir(destination.parent)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
        copied.append(rel_path)
    return copied


def _upgrade_report_text(
    *,
    source_root: Path,
    target_root: Path,
    source_info: Mapping[str, Any],
    current_info: Mapping[str, Any],
    copied: Sequence[str],
    preserved: Sequence[str],
    relocated: Sequence[str],
    config_action: str,
    warnings: Sequence[str],
    validation_result: str,
) -> str:
    lines = [
        "# AIWF Upgrade Report",
        "",
        f"- generated_at: {_now_iso_timestamp()}",
        f"- source_path: {source_root}",
        f"- target_path: {target_root}",
        f"- source_tool_version: {source_info['tool_version']}",
        f"- target_tool_version: {current_info['tool_version']}",
        f"- source_protocol_version: {source_info['protocol_version']}",
        f"- target_protocol_version: {current_info['protocol_version']}",
        f"- source_layout_version: {source_info['layout_version']}",
        f"- target_layout_version: {current_info['layout_version']}",
        "",
        "## Updated Files",
    ]
    if copied:
        lines.extend(f"- {path}" for path in copied)
    else:
        lines.append("- None")
    lines.extend(["", "## Preserved Paths"])
    if preserved:
        lines.extend(f"- {path}" for path in preserved)
    else:
        lines.append("- None")
    lines.extend(["", "## Relocated Paths"])
    if relocated:
        lines.extend(f"- {path}" for path in relocated)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Config Changes",
            f"- {config_action}",
            "",
            "## Warnings",
        ]
    )
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Validation Result", f"- {validation_result}"])
    return "\n".join(lines) + "\n"


def upgrade_command(
    root: Path,
    source: str,
    check: bool,
    dry_run: bool,
    apply: bool,
    no_relocate: bool,
    migrate_legacy_docs: bool,
) -> int:
    source_root = Path(source).expanduser().resolve()
    blockers = _upgrade_validate_source(source_root)
    current_info = _upgrade_current_info(root)
    source_info = _upgrade_source_info(source_root)
    relocation_entries = [
        entry
        for entry in (_candidate_legacy_docs_relocation_paths(root) if migrate_legacy_docs else [])
        if entry.group in {"docs", "records"} and entry.exists
    ]
    relocation_required = bool(relocation_entries)
    upgrade_required = (
        current_info["layout_version"] != source_info["layout_version"]
        or current_info["tool_version"] != source_info["tool_version"]
        or current_info["protocol_version"] != source_info["protocol_version"]
        or relocation_required
    )
    warnings = []
    if no_relocate:
        warnings.append("legacy layout relocation skipped by --no-relocate")
    if not migrate_legacy_docs:
        warnings.append("legacy docs migration is disabled by default; use --migrate-legacy-docs after reviewing root docs/ ownership")
    legacy_tools_runtime = root / "tools" / "ai_workflow.py"
    if legacy_tools_runtime.exists():
        warnings.append(
            "legacy tools/ai_workflow.py exists and is project-owned; AIWF will preserve it unchanged. "
            "Use ./aiwf as the supported entrypoint and remove the legacy file manually only after confirming no external callers depend on it."
        )

    if blockers:
        print("[INFO] AIWF-UPGRADE-CHECK")
        print("Current:")
        print(f"  tool_version: {current_info['tool_version']}")
        print(f"  layout_version: {current_info['layout_version']}")
        print(f"  runtime: {current_info['runtime']}")
        print(f"  records: {current_info['records_root']}")
        print("Target:")
        print(f"  tool_version: {source_info['tool_version']}")
        print(f"  layout_version: {source_info['layout_version']}")
        print(f"  runtime: {source_info['runtime']}")
        print(f"  records: {source_info['records_root']}")
        print("Status:")
        print(f"  upgrade_required: {'yes' if upgrade_required else 'no'}")
        print(f"  relocation_required: {'yes' if relocation_required else 'no'}")
        print(f"  blockers: {len(blockers)}")
        for blocker in blockers:
            print(f"  - {blocker}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        print("Next:")
        print("  fix the blockers, then rerun upgrade --check")
        return 2

    if check or dry_run:
        label = "CHECK" if check else "DRY-RUN"
        print(f"[INFO] AIWF-UPGRADE-{label}")
        print("Current:")
        print(f"  tool_version: {current_info['tool_version']}")
        print(f"  layout_version: {current_info['layout_version']}")
        print(f"  runtime: {current_info['runtime']}")
        print(f"  records: {current_info['records_root']}")
        print("Target:")
        print(f"  tool_version: {source_info['tool_version']}")
        print(f"  layout_version: {source_info['layout_version']}")
        print(f"  runtime: {source_info['runtime']}")
        print(f"  records: {source_info['records_root']}")
        print("Status:")
        print(f"  upgrade_required: {'yes' if upgrade_required else 'no'}")
        print(f"  relocation_required: {'yes' if relocation_required else 'no'}")
        print("  blockers: none")
        print("Will update:")
        for path in ("aiwf", ".aiwf/bin/ai_workflow.py", ".aiwf/docs/**"):
            print(f"  - {path}")
        print("Will preserve:")
        for path in (".aiwf/records/**", ".aiwf/events/**", ".aiwf/migrations/**", ".aiwf/config.yaml"):
            print(f"  - {path}")
        print("Will relocate:")
        if relocation_entries and migrate_legacy_docs and not no_relocate:
            for entry in relocation_entries:
                print(f"  - {entry.label}: {rel(root, entry.source)} -> {rel(root, entry.destination)}")
        elif no_relocate:
            print("  - disabled by --no-relocate")
        elif not migrate_legacy_docs:
            print("  - legacy docs migration disabled by default")
        else:
            print("  - None")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        else:
            print("Warnings:")
            print("  - None")
        print("No files changed.")
        if check:
            print("Next:")
            if upgrade_required:
                print(f"  ./aiwf upgrade --dry-run --source {source_root}")
            else:
                print("  none")
        return 0

    if not upgrade_required:
        print("[INFO] AIWF-UPGRADE-NOOP")
        print(f"Target already matches source package: {source_root}")
        return 0

    config_action = "created"
    event_log_action = "created"
    if no_relocate or not migrate_legacy_docs:
        config_action, event_log_action = _ensure_aiwf_upgrade_skeleton(root)
    else:
        relocate_rc = relocate_command(root, dry_run=False, legacy_docs=True)
        if relocate_rc != 0:
            return relocate_rc
        config_action = "relocated"
        event_log_action = "relocated"

    copied = _copy_upgrade_artifacts(source_root, root)
    preserved = [".aiwf/records/**", ".aiwf/events/**", ".aiwf/migrations/**", ".aiwf/config.yaml"]
    relocated = [
        f"{entry.label}: {rel(root, entry.source)} -> {rel(root, entry.destination)}"
        for entry in relocation_entries
    ] if migrate_legacy_docs and not no_relocate else []
    if no_relocate:
        config_note = f"{config_action} (legacy layout preserved)"
    elif not migrate_legacy_docs:
        config_note = f"{config_action} (legacy docs migration disabled)"
    else:
        config_note = config_action
    report_text = _upgrade_report_text(
        source_root=source_root,
        target_root=root,
        source_info=source_info,
        current_info=_upgrade_current_info(root),
        copied=copied,
        preserved=preserved,
        relocated=relocated,
        config_action=f"{config_note}; event_log={event_log_action}",
        warnings=warnings,
        validation_result="PASS",
    )
    aiwf_root = get_aiwf_root(root)
    ensure_dir(aiwf_root / "migrations")
    report_name = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}_upgrade.md"
    report_path = aiwf_root / "migrations" / report_name
    report_path.write_text(report_text, encoding="utf-8")

    print("[INFO] AIWF-UPGRADE-OK")
    print(f"Report: {rel(root, report_path)}")
    for path in copied:
        print(f"- installed {path}")
    if relocated:
        print(f"- relocated {len(relocated)} legacy paths")
    if warnings:
        for warning in warnings:
            print(f"- warning: {warning}")
    return 0


def write_dataset_output(root: Path, path: Path, content: str) -> WriteResult:
    safe_dataset_output_path(root, path)
    ensure_dir(path.parent)
    action = "updated" if path.exists() else "created"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return WriteResult(path, action)


def append_index(index_path: Path, entry: str) -> WriteResult:
    ensure_dir(index_path.parent)
    if not index_path.exists():
        index_path.write_text("# AI Work Records\n\n", encoding="utf-8")
    text = index_path.read_text(encoding="utf-8", errors="replace")
    if entry.strip() in text:
        return WriteResult(index_path, "exists")
    if not text.endswith("\n"):
        text += "\n"
    text += entry.rstrip() + "\n"
    index_path.write_text(text, encoding="utf-8")
    return WriteResult(index_path, "updated")


def _rollback_failed_task_creation(
    *,
    task_dir: Path,
    task_dir_existed_before: bool,
    index_path: Path,
    index_existed_before: bool,
    index_before_text: Optional[str],
) -> None:
    if not task_dir_existed_before and task_dir.exists():
        shutil.rmtree(task_dir)
    if index_existed_before:
        index_path.write_text(index_before_text or "", encoding="utf-8")
    elif index_path.exists():
        index_path.unlink()


def _index_entry_tokens(line: str) -> list[str]:
    return re.findall(r"`([^`]+)`", line)


def _find_task_index_line(lines: list[str], task_dir: Path) -> Optional[int]:
    task_id, task_name = split_task_dir_name(task_dir)
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        tokens = _index_entry_tokens(line)
        if len(tokens) >= 2 and tokens[0] == task_id and tokens[1] == task_dir.name:
            return idx
        if tokens and tokens[0] == task_dir.name:
            return idx
    return None


def _extract_index_status(line: str) -> Optional[str]:
    match = re.search(r"(^|\|)\s*status:\s*([^|]+?)\s*(?=\||$)", line, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(2).strip()


def _replace_index_status(line: str, new_status: str) -> str:
    pattern = re.compile(r"(^|\|)\s*status:\s*([^|]+?)(\s*)(?=\||$)", flags=re.IGNORECASE)
    if pattern.search(line):
        return pattern.sub(lambda m: f"{m.group(1)} status: {new_status}{m.group(3)}", line, count=1)
    if "|" in line:
        return f"{line} | status: {new_status}"
    return f"{line} | status: {new_status}"


def _project_index_status(front: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    status = str(front.get("status", "")).strip().lower()
    if status == "draft":
        return "Draft", None
    if status == "active":
        return "Active", None
    if status == "review":
        return "Review", None
    if status == "blocked":
        return "Blocked", None
    if status == "archived":
        return "Archived", None
    if status == "done":
        if not _has_non_empty_text(front.get("finalized_at")):
            return None, "INDEX_STATUS_INVALID_DONE"
        return "Done", None
    return None, None


def _collect_index_consistency_diagnostics(root: Path, task_dir: Path, metadata_payload: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    metadata = metadata_payload.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata:
        return diagnostics
    schema_version = str(metadata.get("schema_version", LEGACY_SCHEMA_VERSION))
    if schema_version == LEGACY_SCHEMA_VERSION or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return diagnostics

    expected_status, projection_error = _project_index_status(metadata)
    index_path = task_dir.parent / "index.md"
    if projection_error == "INDEX_STATUS_INVALID_DONE":
        diagnostics.append(make_diagnostic("INDEX_STATUS_INVALID_DONE", rel(root, index_path), blocker=True))
    if expected_status is None:
        return diagnostics
    if not index_path.exists():
        diagnostics.append(
            make_diagnostic(
                "INDEX_ENTRY_MISSING",
                rel(root, task_dir.parent),
                blocker=True,
                task=task_dir.name,
                task_path=rel(root, task_dir),
            )
        )
        return diagnostics

    lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
    line_index = _find_task_index_line(lines, task_dir)
    if line_index is None:
        diagnostics.append(
            make_diagnostic(
                "INDEX_ENTRY_MISSING",
                rel(root, index_path),
                blocker=True,
                task=task_dir.name,
                task_path=rel(root, task_dir),
            )
        )
        return diagnostics

    current_status = _extract_index_status(lines[line_index])
    if current_status is None:
        current_status = "<missing>"
    if current_status.lower() != expected_status.lower():
        diagnostics.append(
            make_diagnostic(
                "INDEX_STATUS_STALE",
                rel(root, index_path),
                blocker=True,
                task=task_dir.name,
                expected=expected_status,
                actual=current_status,
                task_path=rel(root, task_dir),
            )
        )
    return diagnostics


def _sync_index_entry_status(root: Path, task_dir: Path) -> WriteResult:
    if not is_task_specific_dir(task_dir):
        raise SyncIndexError("AIWF-SYNC-001", DIAGNOSTICS["AIWF-SYNC-001"]["message"])
    metadata_payload = load_task_metadata(task_dir)
    metadata = metadata_payload.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata:
        raise SyncIndexError("AIWF-META-001", "task metadata is missing; sync-index requires task front matter.")
    expected_status, projection_error = _project_index_status(metadata)
    if projection_error == "INDEX_STATUS_INVALID_DONE":
        raise SyncIndexError("INDEX_STATUS_INVALID_DONE", DIAGNOSTICS["INDEX_STATUS_INVALID_DONE"]["message"])
    if expected_status is None:
        raise SyncIndexError("INDEX_STATUS_STALE", "cannot project index status from current task metadata.")

    index_path = task_dir.parent / "index.md"
    if not index_path.exists():
        raise SyncIndexError("INDEX_ENTRY_MISSING", f"index.md missing at {rel(root, index_path)}")
    text = index_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    line_index = _find_task_index_line(lines, task_dir)
    if line_index is None:
        raise SyncIndexError("INDEX_ENTRY_MISSING", f"index entry missing for task {task_dir.name} in {rel(root, index_path)}")

    updated_line = _replace_index_status(lines[line_index], expected_status)
    if updated_line == lines[line_index]:
        return WriteResult(index_path, "exists")
    lines[line_index] = updated_line
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    index_path.write_text(new_text, encoding="utf-8")
    return WriteResult(index_path, "updated")


def is_ai_date_dir(path: Path) -> bool:
    return path.is_dir() and bool(AI_DATE_RE.match(path.name))


def is_task_specific_dir(path: Path) -> bool:
    return path.is_dir() and bool(TASK_DIR_RE.match(path.name)) and is_ai_date_dir(path.parent)


def next_task_id(ai_day_dir: Path) -> str:
    ensure_dir(ai_day_dir)
    max_id = 0
    for child in ai_day_dir.iterdir():
        if child.is_dir():
            m = re.match(r"^(\d{3})_", child.name)
            if m:
                max_id = max(max_id, int(m.group(1)))
    return f"{max_id + 1:03d}"


def title_from_path(path: Path) -> str:
    name = path.name
    if TASK_DIR_RE.match(name):
        name = re.sub(r"^\d{3}_", "", name)
    elif AI_DATE_RE.match(name):
        name = "legacy_backfill"
    return name.replace("_", " ")


def read_existing_summary(path: Path) -> str:
    for name in ["task_record.md", "review_final.md", "self_validation.md", "review_agent.md", "review_codex.md", "task.md"]:
        p = path / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text[:2000]
    return ""


def split_task_dir_name(task_dir: Path) -> tuple[Optional[str], Optional[str]]:
    m = TASK_ID_NAME_RE.match(task_dir.name)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _is_valid_repo_relative_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    normalized = text.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return False
    if any(part == ".." for part in path.parts):
        return False
    return True


def canonical_task_ref(raw: str, *, field: str) -> str:
    text = str(raw).strip().strip("'\"")
    if re.fullmatch(r"\d{1,3}", text):
        return text.zfill(3)
    normalized = text.replace("\\", "/")
    name = PurePosixPath(normalized).name
    match = re.fullmatch(r"(\d{1,3})_[a-z0-9_]+", name)
    if match:
        return match.group(1).zfill(3)
    raise ValueError(f"Invalid task reference for {field}: {raw}")


def canonical_task_ref_list(values: Optional[list[str]], *, field: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        ref = canonical_task_ref(value, field=field)
        if ref not in seen:
            result.append(ref)
            seen.add(ref)
    return result


def canonical_tag(raw: str) -> str:
    text = str(raw).strip()
    if not re.fullmatch(r"^[a-z0-9][a-z0-9_-]*$", text):
        raise ValueError(f"Invalid tag: {raw}")
    return text


def canonical_tag_list(values: Optional[list[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        tag = canonical_tag(value)
        if tag not in seen:
            result.append(tag)
            seen.add(tag)
    return result


def canonical_related_file(raw: str) -> str:
    text = str(raw).strip().replace("\\", "/")
    if not _is_valid_repo_relative_path(text):
        raise ValueError(f"Invalid related file path: {raw}")
    return text


def canonical_related_file_list(values: Optional[list[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = canonical_related_file(value)
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def resolve_new_task_date(date: Optional[str], *, allow_non_today_date: bool) -> Optional[str]:
    actual_today = today()
    if date is None:
        selected = actual_today
    else:
        try:
            selected = parse_aiwf_date_arg(date, field="new-task date")
        except DateValidationError as exc:
            _print_date_validation_error(exc)
            return None
    if selected != actual_today and not allow_non_today_date:
        print("[ERROR] AIWF-DATE-001")
        print(f"new-task date {selected} does not match today {actual_today}.")
        print("Suggested Fix:")
        print("Omit --date for normal new tasks, or use --allow-non-today-date for explicit historical/recovery work.")
        return None
    if selected != actual_today and allow_non_today_date:
        print(f"[WARN] non-today new-task date explicitly allowed: {selected}")
    return selected


def default_task_metadata(task_id: str, task_name: str, title: str, date: str) -> dict[str, Any]:
    metadata_date = date
    if re.match(r"^\d{8}$", date):
        metadata_date = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    metadata: dict[str, Any] = {}
    for field_name, spec in TASK_METADATA_SCHEMA.items():
        if field_name == "schema_version":
            metadata[field_name] = CURRENT_SCHEMA_VERSION
            continue
        if field_name in {"task_id", "task_name", "title"}:
            continue
        if field_name in {"created_at", "updated_at"}:
            metadata[field_name] = metadata_date
            continue
        if "default" in spec:
            value = spec["default"]
            metadata[field_name] = list(value) if isinstance(value, list) else value
    metadata["task_id"] = task_id
    metadata["task_name"] = task_name
    metadata["title"] = title
    if _is_v16_or_newer(str(metadata.get("schema_version", ""))):
        metadata["phase_entered_at"] = _now_iso_timestamp()
    return metadata


def _strip_yaml_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_yaml_scalar(raw: str) -> Any:
    value = raw.strip()
    if value in {"null", "~"}:
        return None
    if value == "[]":
        return []
    return _strip_yaml_quotes(value)


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, text

    metadata: dict[str, Any] = {}
    active_list_key: Optional[str] = None
    for raw_line in lines[1:end_index]:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if active_list_key and stripped.startswith("- "):
            metadata.setdefault(active_list_key, []).append(_parse_yaml_scalar(stripped[2:]))
            continue
        active_list_key = None
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        if raw_value == "":
            metadata[key] = []
            active_list_key = key
            continue
        metadata[key] = _parse_yaml_scalar(raw_value)

    body = "\n".join(lines[end_index + 1 :])
    if text.endswith("\n"):
        body += "\n"
    return metadata, body


def _format_front_matter_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def format_front_matter(metadata: dict[str, Any]) -> str:
    # Keep schema-defined fields first, then preserve unknown extension fields.
    ordered = [key for key in _schema_field_order() if key in metadata]
    ordered.extend(key for key in metadata.keys() if key not in TASK_METADATA_SCHEMA)
    lines = ["---"]
    for key in ordered:
        value = metadata.get(key)
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_format_front_matter_value(v)}" for v in value)
        else:
            lines.append(f"{key}: {_format_front_matter_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def load_task_metadata(task_dir: Path) -> dict[str, Any]:
    task_file = task_dir / "task.md"
    task_id, task_name = split_task_dir_name(task_dir)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "task_name": task_name,
        "path": str(task_dir).replace("\\", "/"),
        "schema_version": LEGACY_SCHEMA_VERSION,
        "metadata_valid": False,
        "has_front_matter": False,
        "metadata": {},
    }
    if not task_file.exists():
        return payload
    text = task_file.read_text(encoding="utf-8", errors="replace")
    payload["has_front_matter"] = text.startswith("---")
    metadata, _body = parse_front_matter(text)
    payload["metadata"] = metadata
    if metadata:
        payload["schema_version"] = str(metadata.get("schema_version", LEGACY_SCHEMA_VERSION))
    return payload


def _has_non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


SCHEMA_RANK = {
    SCHEMA_V12: 12,
    SCHEMA_V13: 13,
    SCHEMA_V14: 14,
    SCHEMA_V15: 15,
    SCHEMA_V16: 16,
}


def _schema_rank(schema_version: str) -> int:
    return SCHEMA_RANK.get(schema_version, 0)


def _is_v16_or_newer(schema_version: str) -> bool:
    return _schema_rank(schema_version) >= 16


def validate_task_metadata(root: Path, task_dir: Path, metadata: dict[str, Any]) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    task_file = task_dir / "task.md"
    if not task_file.exists():
        return findings

    has_front_matter = bool(metadata.get("has_front_matter"))
    front = metadata.get("metadata", {})
    if not front:
        if has_front_matter:
            findings.append(make_diagnostic("AIWF-META-001", rel(root, task_file), blocker=True))
        else:
            findings.append(make_diagnostic("AIWF-META-LEGACY-001", rel(root, task_file)))
        return findings

    schema_version = str(front.get("schema_version", LEGACY_SCHEMA_VERSION))
    if schema_version == LEGACY_SCHEMA_VERSION:
        findings.append(make_diagnostic("AIWF-META-LEGACY-001", rel(root, task_file)))
        return findings
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        findings.append(
            make_diagnostic(
                "AIWF-META-003",
                rel(root, task_file),
                blocker=True,
                schema_version=schema_version,
            )
        )
        return findings

    for field_name in _schema_field_order():
        field_spec = TASK_METADATA_SCHEMA[field_name]
        if _field_required_in_version(field_name, schema_version) and field_name not in front:
            findings.append(make_diagnostic("AIWF-META-002", rel(root, task_file), blocker=True, field=field_name))
            continue
        if field_name not in front:
            continue
        value = front.get(field_name)
        field_type = field_spec.get("type")
        if field_type == "string" and not isinstance(value, str):
            findings.append(make_diagnostic("AIWF-META-004", rel(root, task_file), blocker=True, field=field_name, value=value))
            continue
        if field_type == "nullable_string":
            if not (value is None or isinstance(value, str)):
                findings.append(make_diagnostic("AIWF-META-004", rel(root, task_file), blocker=True, field=field_name, value=value))
                continue
            if isinstance(value, str):
                pattern = field_spec.get("pattern")
                if pattern and not re.match(pattern, value):
                    findings.append(make_diagnostic("AIWF-META-010", rel(root, task_file), blocker=True, field=field_name, value=value))
                enum_values = field_spec.get("enum")
                if enum_values and value not in enum_values:
                    findings.append(
                        make_diagnostic(
                            "AIWF-META-007",
                            rel(root, task_file),
                            blocker=True,
                            field=field_name,
                            value=value,
                            allowed=", ".join(sorted(enum_values)),
                        )
                    )
            continue
        if field_type == "list":
            if not isinstance(value, list):
                findings.append(make_diagnostic("AIWF-META-004", rel(root, task_file), blocker=True, field=field_name, value=value))
                continue
            item_pattern = field_spec.get("item_pattern")
            if item_pattern:
                for item in value:
                    if not isinstance(item, str) or not re.match(item_pattern, item):
                        findings.append(
                            make_diagnostic(
                                "AIWF-META-009",
                                rel(root, task_file),
                                blocker=True,
                                field=field_name,
                                value=item,
                            )
                        )
            item_kind = field_spec.get("item_kind")
            if item_kind == "repo_relative_path":
                for item in value:
                    if not _is_valid_repo_relative_path(item):
                        findings.append(
                            make_diagnostic(
                                "AIWF-META-011",
                                rel(root, task_file),
                                blocker=True,
                                field=field_name,
                                value=item,
                            )
                        )
            continue
        if isinstance(value, str):
            pattern = field_spec.get("pattern")
            if pattern and not re.match(pattern, value):
                findings.append(make_diagnostic("AIWF-META-004", rel(root, task_file), blocker=True, field=field_name, value=value))
            enum_values = field_spec.get("enum")
            if enum_values and value not in enum_values:
                findings.append(
                    make_diagnostic(
                        "AIWF-META-007",
                        rel(root, task_file),
                        blocker=True,
                        field=field_name,
                        value=value,
                        allowed=", ".join(sorted(enum_values)),
                    )
                )

    expected_task_id, expected_task_name = split_task_dir_name(task_dir)
    task_id_value = str(front.get("task_id", ""))
    if expected_task_id and task_id_value != expected_task_id:
        findings.append(make_diagnostic("AIWF-META-005", rel(root, task_file), blocker=True, expected=expected_task_id))

    task_name_value = str(front.get("task_name", ""))
    if expected_task_name and task_name_value != expected_task_name:
        findings.append(make_diagnostic("AIWF-META-006", rel(root, task_file), blocker=True, expected=expected_task_name))

    status = str(front.get("status", ""))
    review_status = str(front.get("review_status", ""))
    workflow_phase = str(front.get("workflow_phase", ""))

    if status == "done":
        if review_status not in {"pass", "not_required"}:
            findings.append(make_diagnostic("AIWF-META-008", rel(root, task_file), blocker=True))
        if _field_required_in_version("workflow_phase", schema_version) and workflow_phase != "finalized":
            findings.append(make_diagnostic("AIWF-PHASE-001", rel(root, task_file), blocker=True))
    if status == "blocked":
        blocked_by = front.get("blocked_by", [])
        blocked_reason = front.get("blocked_reason")
        blocked_by_has_value = isinstance(blocked_by, list) and len(blocked_by) > 0
        blocked_reason_has_value = _has_non_empty_text(blocked_reason)
        if not blocked_by_has_value and not blocked_reason_has_value:
            findings.append(make_diagnostic("AIWF-BLOCK-001", rel(root, task_file), blocker=True))

    findings.append(make_diagnostic("AIWF-META-OK", rel(root, task_file), schema_version=schema_version))
    return findings


def _task_export_record(root: Path, task_dir: Path) -> dict[str, Any]:
    task_id, task_name = split_task_dir_name(task_dir)
    meta_info = load_task_metadata(task_dir)
    front = meta_info.get("metadata", {})
    date_value = _canonical_dataset_date(front.get("created_at")) or _canonical_dataset_date(front.get("date"))
    if date_value is None:
        date_value = _dataset_date_from_task_dir(task_dir)
    base: dict[str, Any] = {
        "task_id": task_id,
        "task_name": task_name,
        "path": rel(root, task_dir),
        "date": date_value,
    }
    if not front:
        base.update(
            {
                "schema_version": LEGACY_SCHEMA_VERSION,
                "metadata_valid": False,
            }
        )
        return base

    validation = validate_task_metadata(root, task_dir, meta_info)
    has_fail = any(item.severity == "error" for item in validation)
    status = str(front.get("status", ""))
    review_status = str(front.get("review_status", ""))
    workflow_phase = str(front.get("workflow_phase", ""))
    blocked_by = front.get("blocked_by", [])
    base.update(
        {
            "schema_version": str(front.get("schema_version", LEGACY_SCHEMA_VERSION)),
            "metadata_valid": bool(front.get("schema_version") in SUPPORTED_SCHEMA_VERSIONS and not has_fail),
            "status": status,
            "workflow_phase": workflow_phase,
            "phase_entered_at": front.get("phase_entered_at"),
            "priority": str(front.get("priority", "")),
            "risk": str(front.get("risk", "")),
            "review_status": review_status,
            "review_not_required_reason": front.get("review_not_required_reason"),
            "review_pending": review_status == "pending",
            "blocked": status == "blocked"
            or (isinstance(blocked_by, list) and len(blocked_by) > 0)
            or _has_non_empty_text(front.get("blocked_reason")),
            "blocked_reason": front.get("blocked_reason"),
            "finalized_at": front.get("finalized_at"),
            "finalized_by": front.get("finalized_by"),
            "parent_task": front.get("parent_task"),
            "related_tasks": front.get("related_tasks", []),
            "blocked_by": front.get("blocked_by", []),
            "supersedes": front.get("supersedes", []),
            "related_files": front.get("related_files", []),
            "tags": front.get("tags", []),
        }
    )
    return base


def export_tasks_json(root: Path, scope_path: Optional[Path]) -> dict[str, Any]:
    if scope_path is None:
        task_dirs = _iter_all_task_dirs(root)
    else:
        target = scope_path
        if is_task_specific_dir(target):
            task_dirs = [target]
        elif is_ai_date_dir(target):
            task_dirs = sorted(p for p in target.iterdir() if p.is_dir() and TASK_DIR_RE.match(p.name))
        else:
            raise ValueError("unsupported path type; expected .aiwf/records/ai_YYYYMMDD or task directory")

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "workflow_version": WORKFLOW_PROTOCOL_VERSION,
        "capabilities": EXPORT_CAPABILITIES,
        "tasks": [_task_export_record(root, task_dir) for task_dir in task_dirs],
    }


def task_md(title: str, metadata: Optional[dict[str, Any]] = None, source_path: Optional[str] = None, backfill: bool = False) -> str:
    source = f"\n## Source / Historical Path\n\n- `{source_path}`\n" if source_path else ""
    prefix = "Backfill" if backfill else "Task"
    front = format_front_matter(metadata or {})
    return f"""{front}
# {prefix}: {title}

## Background

Describe the source of this task, including bug report, review finding, historical record, or user request.
{source}
## Problem

Describe the concrete problem to solve. Keep it verifiable.

## Goal

Describe the expected final state.

## Constraints

- Keep changes surgical.
- Preserve historical records when this is a backfill task.
- Do not run real DUT, destructive, disruptive, RAID, disk-wipe, mkfs, firmware, or power-cycle operations unless explicitly approved.
- Prefer static validation, collect-only, or narrow offline checks.

## Acceptance Criteria

- [ ] Required workflow files exist.
- [ ] Existing historical files are preserved.
- [ ] Knowledge writeback is created or explicitly marked as not applicable.
- [ ] No unrelated files are changed.
- [ ] Validation results and limitations are documented.

## Risk

Document any hardware, storage, DUT, RAID, filesystem, or workflow risk.

## Validation Plan

- Static file existence check.
- Index entry check.
- Documentation-only diff review when git is available.
- No real DUT/destructive execution.
"""


def agent_md(title: str, backfill: bool = False) -> str:
    mode = "backfill" if backfill else "task"
    return f"""# Agent Instructions: {title}

## Role

You are an AI workflow implementation engineer working in a Python/pytest automation repository.

## Project Context

This repository may include storage, infrastructure, networking, hardware, or disruptive automation workflows depending on project context.

Treat hardware-impacting actions as unsafe unless explicitly approved.

## Execution Rules

1. Read `task.md` before editing.
2. This is a v1.1 workflow {mode}.
3. Keep changes minimal and scoped.
4. Preserve existing historical records and conclusions.
5. Do not modify business code unless the task explicitly requires it.
6. Do not run real DUT or destructive operations.
7. Prefer static validation and narrow offline checks.
8. Add or update reusable knowledge under `.aiwf/docs/knowledge/` when the lesson is reusable.
9. Avoid duplicate knowledge documents.
10. Document skipped validation and limitations.

## Safety Rules

- Treat logical-drive deletion, controller mode change, filesystem creation, disk wipe, rebuild, firmware update, and power-cycle as destructive/disruptive.
- Never assume a disk cleanup target is safe.
- Fail closed when target safety cannot be verified.

## Required Outputs

- `task.md`
- `agent.md`
- `task_record.md`
- `self_validation.md`
- `review_agent.md` (canonical agent review artifact; `review_codex.md` is a legacy alias)
- `review_final.md`
- Knowledge writeback when reusable

## Review Checklist

- Was the scope respected?
- Were original records preserved?
- Are v1.1 files complete?
- Are risks and skipped validations clear?
- Were no real DUT/destructive operations executed?
"""


def task_record_md(title: str, backfill_path: Optional[str] = None) -> str:
    selected = f"\n## Selected Path\n\n- `{backfill_path}`\n" if backfill_path else ""
    return f"""# Task Record: {title}

## Changed

Describe what was changed.
{selected}
## Why

Describe why these changes were needed.

## Compatibility Notes

Describe compatibility impact and legacy behavior.

## Files Modified

List changed files.

## Risk Control

- No real DUT/destructive operations were executed.
- Existing historical records were preserved.
- Changes were limited to workflow/documentation unless otherwise stated.

## Result

Pending validation.

## Known Limitations

Document limitations, skipped checks, or unavailable git/DUT validation.

## Future Improvement

Document follow-up improvements.
"""


def self_validation_md(title: str) -> str:
    return f"""# Self Validation: {title}

## Commands Run

Record exact commands if executed.

## Results

Pending.

## Known Limitations

Document skipped checks and environment limitations.
"""


def review_agent_md(title: str) -> str:
    return f"""# Agent Self Review: {title}

## Code / Documentation Quality

Pending.

## Logic Coverage

Pending.

## Safety Impact

Pending.

## v1.1 Completeness

Pending.

## Remaining Risks

Pending.
"""


def review_codex_md(title: str) -> str:
    return review_agent_md(title).replace("# Agent Self Review:", "# Codex Self Review:", 1)


def review_final_md(title: str) -> str:
    return f"""# Final Review: {title}

## Review Scope

Pending.

## Key Findings

Pending.

## Blocking Issues

Pending.

## Decision

Pending human review.

## Final Result

PENDING

## DUT Validation Conclusion

Not run. This task does not execute real DUT/destructive validation unless explicitly approved.

## Reviewer

Pending human reviewer.
"""


def knowledge_content(kind: str, name: str) -> str:
    title = name.replace("_", " ").title()
    if kind == "pattern":
        return f"""# Pattern: {title}

## Problem

Describe the recurring problem.

## Rule

Describe the reusable rule.

## Recommended Controls

- Keep changes scoped.
- Preserve diagnostics.
- Prefer static or offline validation first.
- Document limitations.

## Pitfalls

- Silent failure.
- Over-broad changes.
- Missing cleanup or missing index links.

## Related Tasks

- Add related `.aiwf/records/ai_YYYYMMDD/NNN_task/` paths here.
"""
    if kind == "bug":
        return f"""# Bug: {title}

## Symptom

Describe the observed failure.

## Root Cause

Describe the confirmed or inferred root cause.

## Fix Pattern

Describe the reusable fix pattern.

## Validation

Describe safe validation.

## Related Tasks

- Add related `.aiwf/records/ai_YYYYMMDD/NNN_task/` paths here.
"""
    if kind == "decision":
        return f"""# Decision: {title}

## Decision

State the decision.

## Rationale

Explain why this decision was made.

## Consequences

Describe trade-offs and expected future behavior.

## Applies To

- AI workflow governance
- AI coding agents
- Repository contributors

## Related Tasks

- Add related `.aiwf/records/ai_YYYYMMDD/NNN_task/` paths here.
"""
    raise ValueError(f"unsupported knowledge kind: {kind}")


def print_results(results: Iterable[WriteResult], root: Path) -> None:
    for r in results:
        print(f"{r.action.upper():8} {rel(root, r.path)}")


def _metadata_path(root: Path, task_dir: Path) -> Path:
    return task_dir / "task.md"


def _now_iso_date() -> str:
    return dt.date.today().isoformat()


def _now_iso_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_timestamp(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _section_header(section_name: str) -> str:
    return f"## {section_name}"


def _extract_markdown_section_block(text: str, section_name: str) -> Optional[str]:
    header = _section_header(section_name)
    section_pattern = re.compile(
        rf"^{re.escape(header)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE,
    )
    match = section_pattern.search(text)
    if not match:
        return None
    return match.group(1)


def _normalize_section_text(block: str) -> str:
    return "\n".join(line.rstrip() for line in block.strip().splitlines()).strip()


def _section_matches_template(text: str, section_name: str, expected: str) -> bool:
    block = _extract_markdown_section_block(text, section_name)
    if block is None:
        return False
    return _normalize_section_text(block) == _normalize_section_text(expected)


def _classify_acceptance_criteria_item(body: str, checked: bool) -> str:
    if checked:
        return "passed"
    normalized = body.strip().lower()
    if "not applicable" in normalized or "not_applicable" in normalized or re.search(r"\bn/?a\b", normalized):
        return "not_applicable"
    if "deferred" in normalized:
        return "deferred"
    if "blocked" in normalized:
        return "blocked"
    if re.search(r"\bfailed?\b", normalized):
        return "failed"
    return "unresolved"


def _acceptance_criteria_states(task_text: str) -> list[str]:
    block = _extract_markdown_section_block(task_text, "Acceptance Criteria")
    if block is None:
        return []
    states: list[str] = []
    pattern = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s*(?P<body>.+?)\s*$")
    for line in block.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        checked = match.group("mark").lower() == "x"
        states.append(_classify_acceptance_criteria_item(match.group("body"), checked))
    return states


def _is_already_finalized(metadata: dict[str, Any]) -> bool:
    return (
        str(metadata.get("status", "")) == "done"
        and str(metadata.get("workflow_phase", "")) == "finalized"
        and _has_non_empty_text(metadata.get("finalized_at"))
    )


def _resolve_target_path(root: Path, raw_target: str) -> Path:
    target = Path(raw_target)
    target = (root / target).resolve() if not target.is_absolute() else target.resolve()
    if not target.exists():
        raise SystemExit(f"ERROR: path does not exist: {target}")
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"ERROR: path is outside repo root: {target}")
    return target


def _resolve_guard_target_path(root: Path, raw_target: str) -> Optional[Path]:
    if not _has_non_empty_text(raw_target):
        return None
    target = Path(raw_target)
    target = (root / target).resolve() if not target.is_absolute() else target.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _guard_is_closed(metadata: dict[str, Any]) -> Optional[str]:
    workflow_phase = str(metadata.get("workflow_phase", "")).strip().lower()
    if workflow_phase == "finalized":
        return "workflow_phase=finalized"
    status = str(metadata.get("status", "")).strip().lower()
    if status in {"done", "archived"}:
        return f"status={status}"
    finalized_at = metadata.get("finalized_at")
    if finalized_at is None:
        return None
    if isinstance(finalized_at, str):
        normalized = finalized_at.strip().lower()
        if normalized in {"", "null"}:
            return None
        return "finalized_at present"
    return "finalized_at present"


def _guard_event_log_warning(root: Path, task_dir: Path) -> Optional[str]:
    event_log = _task_event_log_path(task_dir)
    if not event_log.exists():
        return None
    _events, malformed_count = _load_events_with_stats(task_dir)
    if malformed_count <= 0:
        return None
    return f"{rel(root, event_log)}: malformed lines detected ({malformed_count}); proceeding because event logs are optional."


def guard_pre_edit(root: Path, raw_target: Optional[str], *, pre_edit: bool) -> tuple[int, str]:
    if not pre_edit or not _has_non_empty_text(raw_target):
        diag = make_diagnostic("AIWF-GUARD-900", "", blocker=True)
        return 1, f"{diag.code}: {diag.message}\n"

    task_dir = _resolve_guard_target_path(root, raw_target or "")
    if task_dir is None:
        diag = make_diagnostic("AIWF-GUARD-900", "", blocker=True)
        return 1, f"{diag.code}: {diag.message}\n"

    display_path = rel(root, task_dir)
    if not task_dir.exists() or not task_dir.is_dir():
        diag = make_diagnostic("AIWF-GUARD-001", display_path, blocker=True)
        return 2, f"{diag.code}: {diag.message}\ntask_path: {display_path}\n"

    missing = [
        _artifact_group_label(group)
        for filename, path, _legacy, group in _resolved_required_artifacts(task_dir, PRE_EDIT_REQUIRED_FILE_GROUPS)
        if not path.exists()
    ]
    if missing:
        diag = make_diagnostic("AIWF-GUARD-002", display_path, blocker=True)
        lines = [f"{diag.code}: {diag.message}", f"task_path: {display_path}", "missing:"]
        lines.extend(f"- {filename}" for filename in missing)
        return 2, "\n".join(lines) + "\n"

    metadata_payload = load_task_metadata(task_dir)
    front = metadata_payload.get("metadata", {})
    if not isinstance(front, dict) or not front:
        diag = make_diagnostic("AIWF-GUARD-003", display_path, blocker=True)
        return 2, f"{diag.code}: {diag.message}\ntask_path: {display_path}\n"

    closed_reason = _guard_is_closed(front)
    if closed_reason:
        diag = make_diagnostic("AIWF-GUARD-004", display_path, blocker=True)
        return 2, f"{diag.code}: {diag.message}\ntask_path: {display_path}\nreason: {closed_reason}\n"

    warning = _guard_event_log_warning(root, task_dir)
    if warning:
        print(f"WARN: {warning}", file=sys.stderr)

    diag = make_diagnostic("AIWF-GUARD-PASS", display_path)
    return 0, f"{diag.code}: {diag.message}\ntask_path: {display_path}\n"


def _collect_required_file_diagnostics(root: Path, task_dir: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for filename, path, legacy, group in _resolved_required_artifacts(task_dir, FINALIZE_REQUIRED_FILE_GROUPS):
        if path.exists():
            label = filename if not legacy else _artifact_group_label(group)
            diagnostics.append(make_diagnostic("AIWF-FILE-OK", rel(root, path), filename=label))
            continue
        diagnostics.append(make_diagnostic("AIWF-FILE-001", rel(root, task_dir), blocker=True, filename=_artifact_group_label(group)))
    return diagnostics


def _collect_required_section_diagnostics(root: Path, task_dir: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for filename, required_sections in REQUIRED_DOC_SECTIONS.items():
        path = task_dir / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for section in required_sections:
            header = _section_header(section)
            if header in text:
                diagnostics.append(
                    make_diagnostic("AIWF-SECTION-OK", rel(root, path), filename=filename, section=header)
                )
                continue
            diagnostics.append(make_diagnostic("AIWF-SECTION-001", rel(root, path), blocker=True, filename=filename, section=header))
    return diagnostics


def _collect_placeholder_diagnostics(root: Path, task_dir: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    placeholder_line_patterns = (
        re.compile(r"^\s*(?:[-*]\s*)?TODO\s*$", re.IGNORECASE),
        re.compile(r"^\s*(?:[-*]\s*)?TBD\s*$", re.IGNORECASE),
        re.compile(r"^\s*(?:[-*]\s*)?PENDING\s*$", re.IGNORECASE),
        re.compile(r"^\s*(?:[-*]\s*)?<fill me>\s*$", re.IGNORECASE),
    )
    for filename, required_sections in REQUIRED_DOC_SECTIONS.items():
        path = task_dir / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for section in required_sections:
            block = _extract_markdown_section_block(text, section)
            if block is None:
                continue
            for line in block.splitlines():
                if any(pattern.match(line) for pattern in placeholder_line_patterns):
                    diagnostics.append(
                        make_diagnostic(
                            "AIWF-PLACEHOLDER-001",
                            rel(root, path),
                            blocker=True,
                            filename=filename,
                            marker=line.strip(),
                        )
                    )
    if not any(d.code == "AIWF-PLACEHOLDER-001" for d in diagnostics):
        diagnostics.append(make_diagnostic("AIWF-PLACEHOLDER-OK", rel(root, task_dir)))
    return diagnostics


def _collect_finalize_evidence_hygiene_diagnostics(root: Path, task_dir: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    pending_validation_markers = {
        ("task_record.md", "Result"): {"Pending validation."},
        ("self_validation.md", "Results"): {"Pending."},
    }
    pending_review_markers = {
        ("review_final.md", "Decision"): {"Pending human review."},
        ("review_final.md", "Reviewer"): {"Pending human reviewer."},
    }

    for (filename, section), markers in pending_validation_markers.items():
        path = task_dir / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        block = _extract_markdown_section_block(text, section)
        if block is None:
            continue
        if _normalize_section_text(block) in {_normalize_section_text(marker) for marker in markers}:
            diagnostics.append(
                make_diagnostic(
                    "AIWF-PATH-020",
                    rel(root, path),
                    blocker=True,
                    filename=filename,
                    section=section,
                )
            )

    for (filename, section), markers in pending_review_markers.items():
        path = task_dir / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        block = _extract_markdown_section_block(text, section)
        if block is None:
            continue
        if _normalize_section_text(block) in {_normalize_section_text(marker) for marker in markers}:
            diagnostics.append(
                make_diagnostic(
                    "AIWF-PATH-021",
                    rel(root, path),
                    blocker=True,
                    filename=filename,
                    section=section,
                )
            )

    for filename, section_map in DEFAULT_TEMPLATE_SECTION_BODIES.items():
        path = task_dir / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for section, expected in section_map.items():
            if _section_matches_template(text, section, expected):
                diagnostics.append(
                    make_diagnostic(
                        "AIWF-PATH-022",
                        rel(root, path),
                        blocker=True,
                        filename=filename,
                        section=section,
                    )
                )

    task_path = task_dir / "task.md"
    if task_path.exists():
        task_text = task_path.read_text(encoding="utf-8", errors="replace")
        ac_states = _acceptance_criteria_states(task_text)
        if ac_states:
            all_unresolved = all(state == "unresolved" for state in ac_states)
            if all_unresolved:
                diagnostics.append(make_diagnostic("AIWF-PATH-023", rel(root, task_path), blocker=True))
            if not all_unresolved and any(state in {"unresolved", "failed", "blocked"} for state in ac_states):
                diagnostics.append(make_diagnostic("AIWF-PATH-024", rel(root, task_path), blocker=True))

    return diagnostics


def _collect_finalized_mutation_warnings(root: Path, task_dir: Path, metadata_payload: dict[str, Any]) -> list[Diagnostic]:
    metadata = metadata_payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return []
    if str(metadata.get("workflow_phase", "")) != "finalized":
        return []
    finalized_at = _parse_iso_timestamp(metadata.get("finalized_at"))
    if finalized_at is None:
        return []

    diagnostics: list[Diagnostic] = []
    finalized_epoch = finalized_at.timestamp()
    for path in sorted(task_dir.glob("*.md")):
        if path.name == "task.md":
            continue
        if path.stat().st_mtime > finalized_epoch:
            diagnostics.append(make_diagnostic("AIWF-FINALIZED-001", rel(root, path)))
    return diagnostics


def _artifact_manifest(task_dir: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for filename, path, _legacy, _group in _resolved_required_artifacts(task_dir, FINALIZE_REQUIRED_FILE_GROUPS):
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[filename] = f"sha256:{digest}"
    return manifest


POST_FINALIZE_EVIDENCE_EVENT_TYPES = {
    "fix_recorded",
    "validation_recorded",
    "review_recorded",
    "safety_ack_recorded",
    "phase_transition",
}


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("event") or event.get("command") or "")


def _event_result_status(event: dict[str, Any]) -> str:
    result = event.get("result")
    if isinstance(result, dict):
        return str(result.get("status", ""))
    return str(result or "")


def _event_group(event_type: str) -> str:
    if event_type in {"phase_transition", "finalize_success"}:
        return "workflow"
    if event_type.endswith("_recorded"):
        return "evidence"
    return "unknown"


def _event_payload_from_legacy(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    for key in {
        "schema_version",
        "timestamp",
        "tool_version",
        "event",
        "event_type",
        "event_group",
        "task_path",
        "workflow_mode",
        "actor",
        "model",
        "result",
    }:
        payload.pop(key, None)
    return payload


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = _event_type(event)
    if "event_group" in event:
        group = str(event.get("event_group") or "")
    elif event.get("command") and not event.get("event") and not event.get("event_type"):
        group = "command"
    else:
        group = _event_group(event_type)
    status = _event_result_status(event)
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = _event_payload_from_legacy(event)
    out = dict(event)
    out["event_type"] = event_type
    out["event_group"] = group
    out["result_status"] = status
    out["payload"] = payload
    return out


def _latest_event(events: Sequence[dict[str, Any]], event_name: str) -> Optional[dict[str, Any]]:
    for event in reversed(events):
        if _event_type(event) == event_name:
            return event
    return None


def _latest_event_index(
    events: Sequence[dict[str, Any]],
    event_name: str,
    *,
    result: Optional[str] = None,
) -> int:
    for idx in range(len(events) - 1, -1, -1):
        event = events[idx]
        if _event_type(event) != event_name:
            continue
        if result is not None and _event_result_status(event) != result:
            continue
        return idx
    return -1


def _latest_review_decision(events: Sequence[dict[str, Any]]) -> tuple[int, Optional[dict[str, Any]]]:
    idx = _latest_event_index(events, "review_recorded")
    if idx < 0:
        return -1, None
    return idx, events[idx]


def _event_indexes(events: Sequence[dict[str, Any]], event_name: str, *, result: Optional[str] = None) -> list[int]:
    indexes: list[int] = []
    for idx, event in enumerate(events):
        if _event_type(event) != event_name:
            continue
        if result is not None and _event_result_status(event) != result:
            continue
        indexes.append(idx)
    return indexes


def _collect_path_policy_diagnostics(
    root: Path,
    task_dir: Path,
    metadata_payload: dict[str, Any],
    *,
    include_finalize_checks: bool,
) -> list[Diagnostic]:
    metadata = metadata_payload.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata:
        return []
    schema_version = str(metadata.get("schema_version", LEGACY_SCHEMA_VERSION))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return []

    events, malformed_count = _load_events_with_stats(task_dir)
    diagnostics: list[Diagnostic] = []
    is_v16 = _is_v16_or_newer(schema_version)
    if malformed_count > 0 and is_v16:
        diagnostics.append(
            make_diagnostic(
                "AIWF-PATH-016",
                rel(root, _task_event_log_path(task_dir)),
                blocker=include_finalize_checks,
                severity="error" if include_finalize_checks else "warn",
            )
        )
        if include_finalize_checks:
            return diagnostics

    is_metadata_finalized = str(metadata.get("status", "")) == "done" and str(metadata.get("workflow_phase", "")) == "finalized"
    finalize_success = _latest_event(events, "finalize_success")

    if is_metadata_finalized:
        if finalize_success is None:
            diagnostics.append(
                make_diagnostic(
                    "AIWF-PATH-013",
                    rel(root, _metadata_path(root, task_dir)),
                    blocker=is_v16,
                    severity="error" if is_v16 else "warn",
                )
            )
        elif is_v16:
            manifest = finalize_success.get("artifact_manifest")
            if not isinstance(manifest, dict):
                payload = finalize_success.get("payload")
                if isinstance(payload, dict):
                    manifest = payload.get("artifact_manifest")
            if not isinstance(manifest, dict):
                diagnostics.append(make_diagnostic("AIWF-PATH-015", rel(root, _metadata_path(root, task_dir)), blocker=True))
            else:
                actual_manifest = _artifact_manifest(task_dir)
                expected_manifest = {k: v for k, v in manifest.items() if k in FINALIZE_MANIFEST_FILES}
                if actual_manifest != expected_manifest:
                    diagnostics.append(make_diagnostic("AIWF-PATH-015", rel(root, _metadata_path(root, task_dir)), blocker=True))

    if is_v16 and include_finalize_checks:
        finalize_success_index = _latest_event_index(events, "finalize_success")
        if finalize_success_index >= 0:
            for event in events[finalize_success_index + 1 :]:
                event_type = _event_type(event)
                if event_type in POST_FINALIZE_EVIDENCE_EVENT_TYPES:
                    diagnostics.append(
                        make_diagnostic(
                            "AIWF-PATH-019",
                            rel(root, _task_event_log_path(task_dir)),
                            blocker=True,
                            event_type=event_type,
                        )
                    )
                    break

    if not include_finalize_checks or not is_v16:
        return diagnostics

    # Validation evidence policy.
    validation_pass_indexes = _event_indexes(events, "validation_recorded", result="pass")
    if not validation_pass_indexes:
        diagnostics.append(make_diagnostic("AIWF-PATH-010", rel(root, _metadata_path(root, task_dir)), blocker=True))

    # Review decision freshness policy (single invariant).
    review_status = str(metadata.get("review_status", ""))
    review_not_required_reason = metadata.get("review_not_required_reason")

    fix_indexes = _event_indexes(events, "fix_recorded")
    review_fail_indexes = _event_indexes(events, "review_recorded", result="fail")
    last_fix_index = _latest_event_index(events, "fix_recorded")
    last_review_fail_index = _latest_event_index(events, "review_recorded", result="fail")
    required_review_after = max(last_fix_index, last_review_fail_index)

    latest_review_index, latest_review_event = _latest_review_decision(events)
    if latest_review_event is None:
        diagnostics.append(make_diagnostic("AIWF-PATH-014", rel(root, _metadata_path(root, task_dir)), blocker=True))
    else:
        latest_review_result = _event_result_status(latest_review_event)
        if latest_review_result not in FINAL_REVIEW_RESULTS:
            diagnostics.append(make_diagnostic("AIWF-PATH-014", rel(root, _metadata_path(root, task_dir)), blocker=True))
        if latest_review_index <= required_review_after:
            diagnostics.append(make_diagnostic("AIWF-PATH-014", rel(root, _metadata_path(root, task_dir)), blocker=True))
        if latest_review_result == "not_required" and not _has_non_empty_text(review_not_required_reason):
            diagnostics.append(make_diagnostic("AIWF-PATH-017", rel(root, _metadata_path(root, task_dir)), blocker=True))
        if latest_review_result in FINAL_REVIEW_RESULTS and review_status != latest_review_result:
            diagnostics.append(make_diagnostic("AIWF-PATH-018", rel(root, _metadata_path(root, task_dir)), blocker=True))

    # Review fail -> fix policy.
    if review_fail_indexes:
        fix_indexes_after_review_fail = [idx for idx in fix_indexes if idx > last_review_fail_index]
        if not fix_indexes_after_review_fail:
            diagnostics.append(make_diagnostic("AIWF-PATH-011", rel(root, _metadata_path(root, task_dir)), blocker=True))

    # Fix -> re-validation policy.
    if fix_indexes:
        validation_pass_indexes_set = set(validation_pass_indexes)
        for fix_index in fix_indexes:
            if not any(val_index > fix_index for val_index in validation_pass_indexes_set):
                diagnostics.append(make_diagnostic("AIWF-PATH-012", rel(root, _metadata_path(root, task_dir)), blocker=True))
                break

    return diagnostics


def _collect_task_diagnostics(
    root: Path,
    task_dir: Path,
    *,
    v11_missing_is_fail: bool,
    include_finalize_checks: bool,
    include_index_consistency: bool = True,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not task_dir.exists():
        return [make_diagnostic("AIWF-PATH-001", rel(root, task_dir), blocker=True)]
    if not is_task_specific_dir(task_dir):
        return [make_diagnostic("AIWF-PATH-002", rel(root, task_dir), blocker=True)]

    for filename, path, legacy, group in _resolved_required_artifacts(
        task_dir,
        (("task_record.md",), ("self_validation.md",), AGENT_REVIEW_FILES, ("review_final.md",)),
    ):
        if path.exists():
            label = filename if not legacy else _artifact_group_label(group)
            diagnostics.append(make_diagnostic("AIWF-FILE-OK", rel(root, path), filename=label))
        else:
            diagnostics.append(make_diagnostic("AIWF-FILE-001", rel(root, task_dir), blocker=True, filename=_artifact_group_label(group)))

    for filename in ("task.md", "agent.md"):
        path = task_dir / filename
        if path.exists():
            diagnostics.append(make_diagnostic("AIWF-FILE-OK", rel(root, path), filename=f"v1.1 {filename}"))
            continue
        diagnostics.append(
            make_diagnostic(
                "AIWF-FILE-002",
                rel(root, task_dir),
                severity="error" if v11_missing_is_fail else "warn",
                blocker=v11_missing_is_fail,
                filename=f"v1.1 {filename}",
            )
        )

    metadata_payload = load_task_metadata(task_dir)
    diagnostics.extend(validate_task_metadata(root, task_dir, metadata_payload))
    if include_index_consistency:
        diagnostics.extend(_collect_index_consistency_diagnostics(root, task_dir, metadata_payload))
    diagnostics.extend(_collect_finalized_mutation_warnings(root, task_dir, metadata_payload))
    diagnostics.extend(
        _collect_path_policy_diagnostics(
            root,
            task_dir,
            metadata_payload,
            include_finalize_checks=include_finalize_checks,
        )
    )

    if include_finalize_checks:
        diagnostics.extend(_collect_required_file_diagnostics(root, task_dir))
        diagnostics.extend(_collect_required_section_diagnostics(root, task_dir))
        diagnostics.extend(_collect_placeholder_diagnostics(root, task_dir))
        diagnostics.extend(_collect_finalize_evidence_hygiene_diagnostics(root, task_dir))
        schema_version = str(metadata_payload.get("metadata", {}).get("schema_version", LEGACY_SCHEMA_VERSION))
        if not _is_v16_or_newer(schema_version):
            review_status = str(metadata_payload.get("metadata", {}).get("review_status", ""))
            if review_status not in {"pass", "not_required"}:
                diagnostics.append(make_diagnostic("AIWF-REVIEW-002", rel(root, _metadata_path(root, task_dir)), blocker=True))

    return diagnostics


def _print_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[int, int]:
    err = warn = 0
    for item in diagnostics:
        label = item.severity.upper()
        print(f"[{label}] {item.code}")
        print(f"{item.path}: {item.message}")
        if item.suggested_fix and item.severity in {"error", "warn"}:
            print("Suggested Fix:")
            print(item.suggested_fix)
        err += int(item.severity == "error")
        warn += int(item.severity == "warn")
    return err, warn


def _diagnostic_exit_code(diagnostics: Iterable[Diagnostic], strict: bool) -> int:
    err = sum(1 for item in diagnostics if item.severity == "error")
    warn = sum(1 for item in diagnostics if item.severity == "warn")
    if err:
        return 2
    if strict and warn:
        return 1
    return 0


def summarize_diagnostics(diagnostics: Sequence[Diagnostic]) -> dict[str, Any]:
    errors = sum(1 for item in diagnostics if item.severity == "error")
    warnings = sum(1 for item in diagnostics if item.severity == "warn")
    finalize_blockers = sum(1 for item in diagnostics if item.blocker and item.severity == "error")
    codes = sorted({item.code for item in diagnostics})
    return {
        "errors": errors,
        "warnings": warnings,
        "finalize_blockers": finalize_blockers,
        "codes": codes,
    }


def _event_status_from(exit_code: int, diagnostics_summary: dict[str, Any]) -> str:
    blockers = int(diagnostics_summary.get("finalize_blockers", 0))
    errors = int(diagnostics_summary.get("errors", 0))
    warnings = int(diagnostics_summary.get("warnings", 0))
    if blockers > 0:
        return "blocked"
    if exit_code != 0 or errors > 0:
        return "error"
    if warnings > 0:
        return "warn"
    return "ok"


def append_aiwf_event(
    root: Path,
    task_dir: Path,
    *,
    command: str,
    exit_code: int,
    diagnostics: Sequence[Diagnostic],
    extra_result: Optional[dict[str, Any]] = None,
) -> None:
    if not is_task_specific_dir(task_dir):
        return
    env = load_aiwf_env(root)
    if not aiwf_event_logging_enabled(env):
        return

    context = build_event_context(env)
    ai_agent = resolve_ai_agent_metadata(root)
    diagnostics_summary = summarize_diagnostics(diagnostics)
    status = _event_status_from(exit_code, diagnostics_summary)
    result_payload: dict[str, Any] = {"exit_code": exit_code, "status": status}
    if extra_result:
        result_payload.update(extra_result)
    event = {
        "schema_version": AIWF_EVENT_SCHEMA_VERSION,
        "timestamp": _now_iso_timestamp(),
        "tool_version": AIWF_TOOL_VERSION,
        "command": command,
        "task_path": rel(root, task_dir),
        "workflow_mode": context["workflow_mode"],
        "actor": context["actor"],
        "model": context["model"],
        "ai_agent": ai_agent,
        "result": result_payload,
        "diagnostics": diagnostics_summary,
    }
    _append_raw_event(root, task_dir, event)


def _try_append_aiwf_event(
    root: Path,
    task_dir: Path,
    *,
    command: str,
    exit_code: int,
    diagnostics: Sequence[Diagnostic],
    extra_result: Optional[dict[str, Any]] = None,
) -> None:
    try:
        append_aiwf_event(
            root,
            task_dir,
            command=command,
            exit_code=exit_code,
            diagnostics=diagnostics,
            extra_result=extra_result,
        )
    except Exception as exc:
        print(f"WARN: failed to append AIWF event log: {exc}", file=sys.stderr)


def _finalize_task_metadata(root: Path, task_dir: Path) -> None:
    task_file = _metadata_path(root, task_dir)
    text = task_file.read_text(encoding="utf-8", errors="replace")
    metadata, body = parse_front_matter(text)
    metadata["status"] = "done"
    metadata["workflow_phase"] = "finalized"
    metadata["phase_entered_at"] = _now_iso_timestamp()
    metadata["finalized_at"] = _now_iso_timestamp()
    metadata["finalized_by"] = "tool"
    metadata["updated_at"] = _now_iso_date()
    task_file.write_text(format_front_matter(metadata) + body.lstrip("\n"), encoding="utf-8")


def _build_finalize_preview(root: Path, task_dir: Path) -> list[str]:
    task_file = _metadata_path(root, task_dir)
    text = task_file.read_text(encoding="utf-8", errors="replace")
    metadata, _body = parse_front_matter(text)
    target_updated = _now_iso_date()
    preview: list[str] = []
    if _is_already_finalized(metadata):
        return preview
    preview.append(f"status: {metadata.get('status')} -> done")
    preview.append(f"workflow_phase: {metadata.get('workflow_phase')} -> finalized")
    preview.append(f"phase_entered_at: {metadata.get('phase_entered_at')} -> {_now_iso_timestamp()}")
    preview.append(f"finalized_at: {metadata.get('finalized_at')} -> {_now_iso_timestamp()}")
    preview.append(f"finalized_by: {metadata.get('finalized_by')} -> tool")
    preview.append(f"updated_at: {metadata.get('updated_at')} -> {target_updated}")
    return preview


def _rewrite_task_metadata_file(task_dir: Path, metadata: dict[str, Any]) -> None:
    task_file = task_dir / "task.md"
    text = task_file.read_text(encoding="utf-8", errors="replace")
    _old_metadata, body = parse_front_matter(text)
    task_file.write_text(format_front_matter(metadata) + body.lstrip("\n"), encoding="utf-8")


def transition_command(root: Path, raw_target: str, to_phase: str) -> int:
    target = _resolve_target_path(root, raw_target)
    if not is_task_specific_dir(target):
        print("[ERROR] AIWF-PATH-002")
        print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-PATH-002']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-PATH-002"]["suggested_fix"])
        return 2

    task_file = _metadata_path(root, target)
    metadata_payload = load_task_metadata(target)
    metadata = metadata_payload.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata:
        print("[ERROR] AIWF-META-001")
        print(f"{rel(root, task_file)}: {DIAGNOSTICS['AIWF-META-001']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-META-001"]["suggested_fix"])
        return 2

    current_phase = str(metadata.get("workflow_phase", ""))
    if current_phase == "finalized":
        diag = make_diagnostic("AIWF-PHASE-004", rel(root, task_file), blocker=True)
        _print_diagnostics([diag])
        return 2

    if to_phase == "finalized":
        diag = make_diagnostic("AIWF-PHASE-002", rel(root, task_file), blocker=True, from_phase=current_phase, to_phase=to_phase)
        _print_diagnostics([diag])
        return 2

    allowed_next = ALLOWED_PHASE_TRANSITIONS.get(current_phase, set())
    if to_phase not in ALLOWED_WORKFLOW_PHASE or to_phase not in allowed_next:
        diag = make_diagnostic("AIWF-PHASE-002", rel(root, task_file), blocker=True, from_phase=current_phase, to_phase=to_phase)
        _print_diagnostics([diag])
        return 2

    metadata["workflow_phase"] = to_phase
    metadata["phase_entered_at"] = _now_iso_timestamp()
    metadata["updated_at"] = _now_iso_date()
    _rewrite_task_metadata_file(target, metadata)
    _append_evidence_event(
        root,
        target,
        {
            "event_type": "phase_transition",
            "event_group": "workflow",
            "from": current_phase,
            "to": to_phase,
            "implicit": False,
            "reason": "transition",
            "payload": {
                "from": current_phase,
                "to": to_phase,
                "implicit": False,
                "reason": "transition",
            },
            "result": "ok",
        },
    )
    print(f"[INFO] phase transition: {current_phase} -> {to_phase}")
    return 0


def record_command(
    root: Path,
    raw_target: str,
    *,
    kind: str,
    result: Optional[str],
    command: Optional[str],
    reviewer: Optional[str],
    summary: Optional[str],
) -> int:
    target = _resolve_target_path(root, raw_target)
    if not is_task_specific_dir(target):
        print("[ERROR] AIWF-PATH-002")
        print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-PATH-002']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-PATH-002"]["suggested_fix"])
        return 2

    if kind not in ALLOWED_RECORD_KIND:
        print("[ERROR] AIWF-META-007")
        print(f"{rel(root, target)}: invalid record kind: {kind}")
        print("Suggested Fix:")
        print(f"Use one of: {', '.join(sorted(ALLOWED_RECORD_KIND))}.")
        return 2

    metadata_payload = load_task_metadata(target)
    metadata = metadata_payload.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata:
        print("[ERROR] AIWF-META-001")
        print(f"{rel(root, _metadata_path(root, target))}: {DIAGNOSTICS['AIWF-META-001']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-META-001"]["suggested_fix"])
        return 2

    is_finalized = str(metadata.get("workflow_phase", "")) == "finalized" or str(metadata.get("status", "")) == "done"
    if is_finalized:
        diag = make_diagnostic("AIWF-FINALIZED-002", rel(root, _metadata_path(root, target)), blocker=True)
        _print_diagnostics([diag])
        return 2

    event: dict[str, Any]
    if kind == "validation":
        if result not in VALIDATION_RECORD_RESULTS:
            print("[ERROR] AIWF-META-007")
            print(f"{rel(root, target)}: invalid validation result: {result}")
            print("Suggested Fix:")
            print(f"Use one of: {', '.join(sorted(VALIDATION_RECORD_RESULTS))}.")
            return 2
        event = {"event": "validation_recorded", "result": result, "kind": kind}
        if command:
            event["command"] = command
    elif kind == "review":
        if result not in REVIEW_RECORD_RESULTS:
            print("[ERROR] AIWF-META-007")
            print(f"{rel(root, target)}: invalid review result: {result}")
            print("Suggested Fix:")
            print(f"Use one of: {', '.join(sorted(REVIEW_RECORD_RESULTS))}.")
            return 2
        event = {"event": "review_recorded", "result": result, "kind": kind}
        if reviewer:
            event["reviewer"] = reviewer
        if summary:
            event["summary"] = summary
        metadata["review_status"] = result
        if reviewer:
            metadata["reviewer"] = reviewer
        if result == "not_required":
            metadata["review_not_required_reason"] = summary if _has_non_empty_text(summary) else metadata.get("review_not_required_reason")
        else:
            metadata["review_not_required_reason"] = None
    elif kind == "fix":
        if not _has_non_empty_text(summary):
            print("[ERROR] AIWF-META-004")
            print(f"{rel(root, target)}: fix record requires --summary")
            print("Suggested Fix:")
            print("Provide --summary with the fix details.")
            return 2
        event = {"event": "fix_recorded", "summary": str(summary), "kind": kind}
    else:  # safety_ack
        if not _has_non_empty_text(summary):
            print("[ERROR] AIWF-META-004")
            print(f"{rel(root, target)}: safety_ack record requires --summary")
            print("Suggested Fix:")
            print("Provide --summary with the safety acknowledgement.")
            return 2
        event = {"event": "safety_ack_recorded", "summary": str(summary), "kind": kind}

    metadata["updated_at"] = _now_iso_date()
    _rewrite_task_metadata_file(target, metadata)
    _append_evidence_event(root, target, event)
    print(f"[INFO] recorded {kind} evidence")
    return 0


def create_task(
    root: Path,
    name: str,
    date: Optional[str],
    update_existing: bool,
    *,
    title: Optional[str] = None,
    priority: Optional[str] = None,
    risk: Optional[str] = None,
    project: Optional[str] = None,
    parent_task: Optional[str] = None,
    related_tasks: Optional[list[str]] = None,
    blocked_by: Optional[list[str]] = None,
    supersedes: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    related_files: Optional[list[str]] = None,
    allow_non_today_date: bool = False,
) -> int:
    selected_date = resolve_new_task_date(date, allow_non_today_date=allow_non_today_date)
    if selected_date is None:
        return 2
    task_dir = resolve_task_dir(root, selected_date, name)
    task_id, norm = split_task_dir_name(task_dir)
    if task_id is None or norm is None:
        raise SystemExit(f"ERROR: failed to resolve task directory: {task_dir}")
    ai_day = task_dir.parent
    resolved_title = title or norm.replace("_", " ")
    try:
        metadata = default_task_metadata(task_id=task_id, task_name=norm, title=resolved_title, date=selected_date)
        # owner/reviewer are workflow roles, not tool/provider/model provenance.
        metadata["owner"] = "ai-agent"
        metadata["reviewer"] = "human"
        if priority:
            metadata["priority"] = priority
        if risk:
            metadata["risk"] = risk
        if project and project.strip():
            metadata["project"] = project.strip()
        if parent_task:
            metadata["parent_task"] = canonical_task_ref(parent_task, field="parent_task")
        metadata["related_tasks"] = canonical_task_ref_list(related_tasks, field="related_tasks")
        metadata["blocked_by"] = canonical_task_ref_list(blocked_by, field="blocked_by")
        metadata["supersedes"] = canonical_task_ref_list(supersedes, field="supersedes")
        metadata["tags"] = canonical_tag_list(tags)
        metadata["related_files"] = canonical_related_file_list(related_files)
    except ValueError as exc:
        field = "metadata"
        value = str(exc)
        match = re.match(r"Invalid task reference for ([a-z_]+): (.+)", str(exc))
        if match:
            field = match.group(1)
            value = match.group(2)
        elif str(exc).startswith("Invalid tag: "):
            field = "tags"
            value = str(exc)[len("Invalid tag: ") :]
        elif str(exc).startswith("Invalid related file path: "):
            field = "related_files"
            value = str(exc)[len("Invalid related file path: ") :]
        print("[ERROR] AIWF-META-REF-001")
        print(f"Invalid task reference input for field {field}: {value}.")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-META-REF-001"]["suggested_fix"])
        return 2
    files = {
        "task.md": task_md(resolved_title, metadata=metadata),
        "agent.md": agent_md(resolved_title),
        "task_record.md": task_record_md(resolved_title),
        "self_validation.md": self_validation_md(resolved_title),
        "review_agent.md": review_agent_md(resolved_title),
        "review_final.md": review_final_md(resolved_title),
    }
    index_path = ai_day / "index.md"
    task_dir_existed_before = task_dir.exists()
    index_existed_before = index_path.exists()
    index_before_text = index_path.read_text(encoding="utf-8", errors="replace") if index_existed_before else None
    results: list[WriteResult] = []
    entry = (
        f"- `{task_id}` `{task_dir.name}` | scope: workflow | status: {metadata['status']} "
        f"| priority: {metadata['priority']} | note: created by .aiwf/bin/ai_workflow.py"
    )
    try:
        results = [write_file(root, task_dir / fn, content, update_existing) for fn, content in files.items()]
        results.append(append_index(index_path, entry))
        metadata_payload = load_task_metadata(task_dir)
        diagnostics = validate_task_metadata(root, task_dir, metadata_payload)
        blockers = [item for item in diagnostics if item.blocker and item.severity == "error"]
        print(f"Task directory: {rel(root, task_dir)}")
        print_results(results, root)
        if blockers:
            _rollback_failed_task_creation(
                task_dir=task_dir,
                task_dir_existed_before=task_dir_existed_before,
                index_path=index_path,
                index_existed_before=index_existed_before,
                index_before_text=index_before_text,
            )
            _print_diagnostics(blockers)
            return 2
        return 0
    except BaseException:
        _rollback_failed_task_creation(
            task_dir=task_dir,
            task_dir_existed_before=task_dir_existed_before,
            index_path=index_path,
            index_existed_before=index_existed_before,
            index_before_text=index_before_text,
        )
        raise


def backfill(root: Path, raw_target: str, date: Optional[str], update_existing: bool, no_decision: bool) -> int:
    target = Path(raw_target)
    target = (root / target).resolve() if not target.is_absolute() else target.resolve()
    if not target.exists() or not target.is_dir():
        raise SystemExit(f"ERROR: target path does not exist or is not a directory: {target}")
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"ERROR: target outside repo root: {target}")

    if date is None:
        selected_date = today()
    else:
        try:
            selected_date = parse_aiwf_date_arg(date, field="date")
        except DateValidationError as exc:
            _print_date_validation_error(exc)
            return 2

    target_rel = rel(root, target)
    title = title_from_path(target)

    if is_task_specific_dir(target):
        selected = target
        selection_reason = "target is already a task-specific directory"
    elif is_ai_date_dir(target):
        task_id = next_task_id(target)
        selected = target / f"{task_id}_{normalize_name(title)}_backfill"
        selection_reason = "target is a date-level directory; created task-specific backfill subdirectory"
    elif is_ai_date_dir(target.parent):
        task_id = next_task_id(target.parent)
        selected = target.parent / f"{task_id}_{normalize_name(target.name)}_backfill"
        selection_reason = "target is a legacy/mixed AI-date child; created sibling backfill subdirectory"
    else:
        selected = target
        selection_reason = "target is non-standard but not date-level; using target directly"

    selected_rel = rel(root, selected)
    summary = read_existing_summary(target) or "No existing summary file was found. Fill manually if needed."

    historical_task = f"""# Backfill: {title}

## Background

This is a v1.1 workflow backfill for a historical AI work record.

## Original Historical Path

- `{target_rel}`

## Selected Backfill Path

- `{selected_rel}`

## Selection Reason

{selection_reason}.

## Existing Historical Summary

```text
{summary}
```

## Problem

The historical task record did not fully follow AI Workflow v1.1, which expects task-level `task.md`, task-level `agent.md`, execution traceability, and reusable knowledge writeback when applicable.

## Goal

- Add missing v1.1 task-level files.
- Preserve original historical files and conclusions.
- Create a current-day execution record for this backfill.
- Add reusable knowledge writeback if applicable.

## Constraints

- Do not rewrite historical conclusions.
- Do not delete or relocate historical files.
- Do not modify business code.
- Do not run real DUT or destructive tests.
- Keep changes limited to .aiwf/records/ai_* and .aiwf/docs/knowledge.

## Acceptance Criteria

- [ ] `task.md` exists in the selected historical/backfill task directory.
- [ ] `agent.md` exists in the selected historical/backfill task directory.
- [ ] Current-day execution record exists.
- [ ] Index files are updated.
- [ ] Knowledge writeback exists or is explicitly not applicable.
- [ ] No business code changed.
- [ ] No real DUT/destructive operation executed.

## Risk

Backfill errors can reduce traceability if files are placed at date-root level or if old records are rewritten. Preserve historical structure and link old/new paths clearly.

## Validation Plan

- Static file existence check.
- Index content check.
- Documentation-only scope check.
- No real DUT/destructive execution.
"""
    historical_agent = f"""# Agent Instructions: backfill {title}

## Role

You are an AI workflow backfill agent.

## Scope

- Original path: `{target_rel}`
- Selected backfill path: `{selected_rel}`

## Execution Rules

1. Treat this as a v1.1 workflow backfill.
2. Operate only on the specified path and the current-day execution record.
3. Preserve all existing historical files.
4. Do not rewrite historical conclusions.
5. Do not modify business code.
6. Do not run real DUT or destructive operations.
7. Prefer static validation only.
8. Add reusable knowledge under `.aiwf/docs/knowledge/` if applicable.

## Safety Rules

- Never add task-specific files directly under `.aiwf/records/ai_YYYYMMDD/`.
- Use a task-specific directory.
- Keep historical and current-day records linked.
- Avoid duplicate knowledge files.

## Required Outputs

- Historical/backfill `task.md`
- Historical/backfill `agent.md`
- Current-day execution record
- Index updates
- Knowledge writeback when applicable

## Review Checklist

- Correct path selected?
- Old records preserved?
- v1.1 files complete?
- Knowledge written or not-applicable reason documented?
- No code changes?
- No destructive operations?
"""
    selected_task_id, selected_task_name = split_task_dir_name(selected)
    if selected_task_id is None or selected_task_name is None:
        selected_task_id = "000"
        selected_task_name = normalize_name(selected.name)
    historical_metadata = default_task_metadata(
        task_id=selected_task_id,
        task_name=selected_task_name,
        title=title,
        date=selected_date,
    )

    results = [
        write_file(root, selected / "task.md", format_front_matter(historical_metadata) + historical_task, update_existing),
        write_file(root, selected / "agent.md", historical_agent, update_existing),
    ]

    if is_ai_date_dir(selected.parent):
        results.append(append_index(selected.parent / "index.md", f"- `{selected.name}` | scope: v1.1 backfill | status: added | note: original `{target_rel}`"))

    current_ai_day = resolve_ai_day_dir(root, selected_date)
    cur_id = next_task_id(current_ai_day)
    backfill_name = normalize_name("backfill_" + target_rel.replace("/", "_").replace("\\", "_"))
    current = current_ai_day / f"{cur_id}_{backfill_name}"
    current_rel = rel(root, current)
    current_metadata = default_task_metadata(
        task_id=cur_id,
        task_name=backfill_name,
        title=f"backfill {target_rel}",
        date=selected_date,
    )

    record_files = {
        "task.md": task_md(f"backfill {target_rel}", metadata=current_metadata, source_path=target_rel, backfill=True),
        "agent.md": agent_md(f"backfill {target_rel}", backfill=True),
        "task_record.md": task_record_md(f"backfill {target_rel}", backfill_path=selected_rel),
        "self_validation.md": self_validation_md(f"backfill {target_rel}"),
        "review_agent.md": review_agent_md(f"backfill {target_rel}"),
        "review_final.md": review_final_md(f"backfill {target_rel}"),
    }
    for fn, content in record_files.items():
        results.append(write_file(root, current / fn, content, update_existing))
    results.append(append_index(current_ai_day / "index.md", f"- `{cur_id}` `{current.name}` | scope: backfill | status: generated | note: original `{target_rel}` -> selected `{selected_rel}`"))

    if not no_decision:
        decision_path = root / "docs" / "knowledge" / "decisions" / "v11_backfill_preserve_historical_structure.md"
        decision = f"""# Decision: Preserve historical structure during v1.1 backfill

## Decision

When backfilling historical AI work records, preserve original historical files and add v1.1 task/agent files in a task-specific directory.

## Rationale

Historical records are audit artifacts. Rewriting or relocating them can damage traceability. Backfill should improve future retrieval without changing what happened historically.

## Required Behavior

- Do not place task-specific files directly under `.aiwf/records/ai_YYYYMMDD/`.
- Use or create a task-specific subdirectory.
- Create a current-day execution record for the backfill.
- Link original and selected paths in records and indexes.
- Do not rewrite historical conclusions.

## Related Backfill

- Original: `{target_rel}`
- Selected: `{selected_rel}`
- Execution: `{current_rel}`
"""
        results.append(write_file(root, decision_path, decision, update_existing=False))

    print(f"Selected historical/backfill path: {selected_rel}")
    print(f"Current execution record:        {current_rel}")
    print_results(results, root)
    return 0



def check_task_dir(root: Path, task_dir: Path, *, v11_missing_is_fail: bool = True) -> list[Finding]:
    diagnostics = _collect_task_diagnostics(
        root,
        task_dir,
        v11_missing_is_fail=v11_missing_is_fail,
        include_finalize_checks=False,
    )
    findings: list[Finding] = []
    severity_map = {"info": "PASS", "warn": "WARN", "error": "FAIL"}
    for item in diagnostics:
        findings.append(Finding(severity_map.get(item.severity, "WARN"), item.path, f"[{item.code}] {item.message}"))
    return findings


def check_path(root: Path, raw_target: str, strict: bool, *, finalize_ready: bool = False) -> int:
    target = _resolve_target_path(root, raw_target)
    if is_task_specific_dir(target):
        diagnostics = _collect_task_diagnostics(
            root,
            target,
            v11_missing_is_fail=True,
            include_finalize_checks=finalize_ready,
        )
        err, warn = _print_diagnostics(diagnostics)
        if finalize_ready:
            blockers = sum(1 for item in diagnostics if item.blocker and item.severity == "error")
            print(f"\nSummary: {len(diagnostics)} findings, {err} ERROR, {warn} WARN, {blockers} finalize blockers")
            exit_code = 2 if blockers > 0 else 0
        else:
            print(f"\nSummary: {len(diagnostics)} findings, {err} ERROR, {warn} WARN")
            exit_code = _diagnostic_exit_code(diagnostics, strict)
        _try_append_aiwf_event(
            root,
            target,
            command="check_finalize_ready" if finalize_ready else "check",
            exit_code=exit_code,
            diagnostics=diagnostics,
        )
        return exit_code

    if finalize_ready:
        print("[ERROR] AIWF-PATH-002")
        print(f"{rel(root, target)}: finalize-ready check requires a task-specific directory path.")
        print("Suggested Fix:")
        print("Use a path like .aiwf/records/ai_YYYYMMDD/NNN_task_name with --finalize-ready.")
        return 2

    findings: list[Finding] = []
    if is_ai_date_dir(target):
        index = target / "index.md"
        findings.append(
            Finding(
                "PASS" if index.exists() else "WARN",
                rel(root, index if index.exists() else target),
                "index exists" if index.exists() else "missing index.md",
            )
        )

        if (target / "task.md").exists() or (target / "agent.md").exists():
            findings.append(
                Finding(
                    "FAIL",
                    rel(root, target),
                    "task-specific task.md/agent.md found at date-root level",
                )
            )

        task_dirs = sorted(p for p in target.iterdir() if p.is_dir() and TASK_DIR_RE.match(p.name))
        if not task_dirs:
            findings.append(Finding("WARN", rel(root, target), "no task-specific directories found"))
        for task_dir in task_dirs:
            findings.extend(check_task_dir(root, task_dir, v11_missing_is_fail=False))
    else:
        findings.append(
            Finding(
                "WARN",
                rel(root, target),
                "unsupported path type; expected .aiwf/records/ai_YYYYMMDD or .aiwf/records/ai_YYYYMMDD/NNN_task",
            )
        )

    fail = warn = 0
    for f in findings:
        print(f"{f.severity:5} {f.path}: {f.message}")
        fail += int(f.severity == "FAIL")
        warn += int(f.severity == "WARN")

    print(f"\nSummary: {len(findings)} findings, {fail} FAIL, {warn} WARN")
    if fail:
        return 2
    if strict and warn:
        return 1
    return 0


def check_command(root: Path, raw_target: Optional[str], strict: bool, finalize_ready: bool) -> int:
    if finalize_ready and not raw_target:
        print("[ERROR] AIWF-PATH-002")
        print("docs: --finalize-ready requires --path to a task-specific directory.")
        print("Suggested Fix:")
        print("Run: ./aiwf check --path .aiwf/records/ai_YYYYMMDD/NNN_task_name --finalize-ready")
        return 2
    if raw_target:
        return check_path(root, raw_target, strict, finalize_ready=finalize_ready)
    return check_repo(root, strict)


def guard_command(root: Path, pre_edit: bool, raw_target: Optional[str]) -> int:
    exit_code, output = guard_pre_edit(root, raw_target, pre_edit=pre_edit)
    print(output, end="")
    return exit_code


def check_repo(root: Path, strict: bool) -> int:
    findings: list[Finding] = []
    records_root = get_record_root(root)
    ai_dirs = sorted(p for p in records_root.iterdir() if p.is_dir() and AI_DATE_RE.match(p.name)) if records_root.exists() else []
    if not ai_dirs:
        findings.append(Finding("WARN", rel(root, records_root), "no ai_YYYYMMDD directories found under records root"))

    for ai_dir in ai_dirs:
        index = ai_dir / "index.md"
        findings.append(Finding("PASS" if index.exists() else "WARN", rel(root, index if index.exists() else ai_dir), "index exists" if index.exists() else "missing index.md"))
        if (ai_dir / "task.md").exists() or (ai_dir / "agent.md").exists():
            findings.append(Finding("FAIL", rel(root, ai_dir), "task-specific task.md/agent.md found at date-root level"))
        for task_dir in sorted(p for p in ai_dir.iterdir() if p.is_dir() and TASK_DIR_RE.match(p.name)):
            findings.extend(check_task_dir(root, task_dir, v11_missing_is_fail=False))

    knowledge = get_aiwf_docs_root(root) / "knowledge"
    if knowledge.exists():
        for sub in ["patterns", "bugs", "decisions"]:
            p = knowledge / sub
            findings.append(Finding("PASS" if p.exists() else "WARN", rel(root, p), "knowledge category exists" if p.exists() else "knowledge category missing"))
    else:
        findings.append(Finding("WARN", rel(root, knowledge), "knowledge directory missing"))

    fail = warn = 0
    for f in findings:
        print(f"{f.severity:5} {f.path}: {f.message}")
        fail += int(f.severity == "FAIL")
        warn += int(f.severity == "WARN")
    print(f"\nSummary: {len(findings)} findings, {fail} FAIL, {warn} WARN")
    if fail:
        return 2
    if strict and warn:
        return 1
    return 0


def create_knowledge(root: Path, kind: str, name: str, update_existing: bool) -> int:
    norm = normalize_name(name)
    folder = {"pattern": "patterns", "bug": "bugs", "decision": "decisions"}[kind]
    p = get_aiwf_docs_root(root) / "knowledge" / folder / f"{norm}.md"
    result = write_file(root, p, knowledge_content(kind, norm), update_existing)
    print_results([result], root)
    return 0


def _task_event_log_path(task_dir: Path) -> Path:
    return task_dir / ".aiwf" / "events.jsonl"


def _load_events_with_stats(task_dir: Path) -> tuple[list[dict[str, Any]], int]:
    path = _task_event_log_path(task_dir)
    if not path.exists():
        return [], 0
    events: list[dict[str, Any]] = []
    malformed_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            malformed_count += 1
            continue
        if isinstance(item, dict):
            events.append(item)
        else:
            malformed_count += 1
    return events, malformed_count


def _load_events(task_dir: Path) -> list[dict[str, Any]]:
    events, _malformed_count = _load_events_with_stats(task_dir)
    return events


def _append_raw_event(root: Path, task_dir: Path, event: dict[str, Any]) -> None:
    if not is_task_specific_dir(task_dir):
        return
    event_file = _task_event_log_path(task_dir)
    repo_event_file = get_event_log_path(root)
    for path in [event_file, repo_event_file]:
        safe_write_path(root, path)
        ensure_dir(path.parent)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False))
            f.write("\n")


def _append_evidence_event(root: Path, task_dir: Path, event: dict[str, Any]) -> None:
    env = load_aiwf_env(root)
    context = build_event_context(env)
    ai_agent = resolve_ai_agent_metadata(root)
    event_type = _event_type(event)
    result_status = _event_result_status(event)
    if not result_status:
        result_status = "ok"

    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_data = dict(payload)
    else:
        payload_data = _event_payload_from_legacy(event)

    normalized = {
        "schema_version": AIWF_EVIDENCE_EVENT_SCHEMA_VERSION,
        "timestamp": _now_iso_timestamp(),
        "tool_version": AIWF_TOOL_VERSION,
        "event_type": event_type,
        "event": event_type,
        "event_group": str(event.get("event_group") or _event_group(event_type)),
        "task_path": rel(root, task_dir),
        "actor": context["actor"],
        "workflow_mode": context["workflow_mode"],
        "model": context["model"],
        "ai_agent": ai_agent,
        "result": {"status": result_status},
        "payload": payload_data,
    }
    for key, value in payload_data.items():
        normalized.setdefault(key, value)
    _append_raw_event(root, task_dir, normalized)


def _derive_experiment_context_from_events(events: Sequence[dict[str, Any]]) -> Optional[dict[str, Any]]:
    rows: list[tuple[str, str, str, str]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        workflow_mode = str(event.get("workflow_mode", "unknown"))
        model = event.get("model", {})
        if not isinstance(model, dict):
            model = {}
        row = (
            workflow_mode,
            str(model.get("name", "unknown")),
            str(model.get("class", "unknown")),
            str(model.get("provider", "unknown")),
        )
        rows.append(row)
    if not rows:
        return None
    first = rows[0]
    consistent = all(item == first for item in rows)
    if consistent:
        workflow_mode, name, cls, provider = first
        return {
            "workflow_mode": workflow_mode,
            "model": {
                "name": name,
                "class": cls,
                "provider": provider,
            },
            "source": "events",
            "consistent": True,
        }
    return {
        "workflow_mode": "mixed",
        "model": {
            "name": "mixed",
            "class": "mixed",
            "provider": "mixed",
        },
        "source": "events",
        "consistent": False,
    }


def export_experiment_command(root: Path, raw_target: str) -> int:
    target = _resolve_target_path(root, raw_target)
    if not is_task_specific_dir(target):
        raise SystemExit(f"ERROR: path is not a task-specific directory: {target}")

    events, malformed_count = _load_events_with_stats(target)
    if malformed_count > 0:
        print(
            f"WARN: skipped {malformed_count} malformed event line(s) in {rel(root, _task_event_log_path(target))}",
            file=sys.stderr,
        )
    event_context = _derive_experiment_context_from_events(events)
    if event_context is None:
        env = load_aiwf_env(root)
        env_context = build_event_context(env)
        context = {
            "workflow_mode": env_context["workflow_mode"],
            "model": env_context["model"],
            "source": "current_env",
            "consistent": True,
        }
    else:
        context = event_context
    doctor_events = [e for e in events if e.get("command") == "doctor"]
    check_events = [e for e in events if e.get("command") == "check"]
    finalize_dry_run_events = [e for e in events if e.get("command") == "finalize_dry_run"]
    finalize_events = [e for e in events if e.get("command") == "finalize"]

    total_errors = sum(int(e.get("diagnostics", {}).get("errors", 0)) for e in events)
    total_warnings = sum(int(e.get("diagnostics", {}).get("warnings", 0)) for e in events)
    total_finalize_blockers = sum(int(e.get("diagnostics", {}).get("finalize_blockers", 0)) for e in events)
    unique_codes = sorted({code for e in events for code in e.get("diagnostics", {}).get("codes", [])})

    finalize_success_indexes = [
        idx
        for idx, e in enumerate(finalize_events, start=1)
        if int(e.get("result", {}).get("exit_code", 1)) == 0
        and str(e.get("result", {}).get("status", "")) in {"ok", "warn"}
    ]
    finalize_success = len(finalize_success_indexes) > 0
    finalize_attempts_before_success = finalize_success_indexes[0] if finalize_success_indexes else 0
    failed_attempts = sum(
        1
        for e in finalize_events
        if int(e.get("result", {}).get("exit_code", 1)) != 0
        or str(e.get("result", {}).get("status", "")) in {"error", "blocked"}
    )
    had_failed_before_success = False
    if finalize_success:
        success_position = finalize_success_indexes[0]
        had_failed_before_success = any(
            int(e.get("result", {}).get("exit_code", 1)) != 0
            or str(e.get("result", {}).get("status", "")) in {"error", "blocked"}
            for e in finalize_events[: success_position - 1]
        )

    payload = {
        "schema_version": AIWF_EXPERIMENT_SCHEMA_VERSION,
        "task": {"path": rel(root, target)},
        "context": context,
        "run_summary": {
            "event_count": len(events),
            "doctor_run_count": len(doctor_events),
            "check_run_count": len(check_events),
            "finalize_dry_run_count": len(finalize_dry_run_events),
            "finalize_run_count": len(finalize_events),
        },
        "diagnostics_summary": {
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "total_finalize_blockers": total_finalize_blockers,
            "unique_codes": unique_codes,
        },
        "finalize_summary": {
            "attempted": len(finalize_events) > 0,
            "dry_run_attempted": len(finalize_dry_run_events) > 0,
            "success": finalize_success,
            "failed_attempts": failed_attempts,
        },
        "derived_metrics": {
            "finalized_successfully": finalize_success,
            "finalize_attempts_before_success": finalize_attempts_before_success,
            "deterministic_blockers_detected": total_finalize_blockers,
            "recovered_after_diagnostics": had_failed_before_success and finalize_success,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def export_json_command(root: Path, raw_target: Optional[str]) -> int:
    target: Optional[Path] = None
    if raw_target:
        target = Path(raw_target)
        target = (root / target).resolve() if not target.is_absolute() else target.resolve()
        if not target.exists():
            raise SystemExit(f"ERROR: path does not exist: {target}")
        try:
            target.relative_to(root.resolve())
        except ValueError:
            raise SystemExit(f"ERROR: path is outside repo root: {target}")

    payload = export_tasks_json(root, target)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _dataset_warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _append_dataset_warning(warnings: list[dict[str, str]], code: str, message: str) -> None:
    item = _dataset_warning(code, message)
    if item not in warnings:
        warnings.append(item)


def _canonical_dataset_date(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


def _dataset_date_from_task_dir(task_dir: Path) -> Optional[str]:
    if not AI_DATE_RE.match(task_dir.parent.name):
        return None
    return _canonical_dataset_date(task_dir.parent.name.replace("ai_", "", 1))


def _normalize_repo_relative_path(root: Path, value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    text = raw.replace("\\", "/")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / text
    try:
        rel_path = candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return str(PurePosixPath(rel_path.as_posix()))


def _dataset_event_name(event: dict[str, Any]) -> str:
    name = _event_type(event).strip()
    if name.endswith(DATASET_RECORDED_EVENT_SUFFIX):
        return name[: -len(DATASET_RECORDED_EVENT_SUFFIX)]
    return name


def _load_jsonl_events_with_stats(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    events: list[dict[str, Any]] = []
    malformed_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            malformed_count += 1
            continue
        if not isinstance(item, dict):
            malformed_count += 1
            continue
        events.append(item)
    return events, malformed_count


def _dataset_task_indexes(root: Path, task_dirs: Sequence[Path]) -> dict[str, dict[str, set[str]]]:
    path_index: dict[str, set[str]] = {}
    name_index: dict[str, set[str]] = {}
    id_index: dict[str, set[str]] = {}
    record_index: dict[str, set[str]] = {}
    for task_dir in task_dirs:
        task_rel = rel(root, task_dir)
        path_index.setdefault(task_rel, set()).add(task_rel)
        name_index.setdefault(task_dir.name, set()).add(task_rel)
        task_id, _task_name = split_task_dir_name(task_dir)
        if task_id:
            id_index.setdefault(task_id, set()).add(task_rel)
        for filename in DATASET_RECORD_REFERENCE_FILES:
            record_rel = f"{task_rel}/{filename}"
            record_index.setdefault(record_rel, set()).add(task_rel)
    return {
        "path": path_index,
        "name": name_index,
        "id": id_index,
        "record": record_index,
    }


def _dataset_field_matches(
    root: Path,
    event: dict[str, Any],
    indexes: dict[str, dict[str, set[str]]],
    field_name: str,
) -> Optional[set[str]]:
    if field_name not in event:
        return None
    value = event.get(field_name)

    if field_name == "task_id":
        if not isinstance(value, str):
            return set()
        return set(indexes["id"].get(value.strip(), set()))

    if field_name == "record_path":
        record_rel = _normalize_repo_relative_path(root, value)
        if record_rel is None:
            return set()
        return set(indexes["record"].get(record_rel, set()))

    if field_name in {"task_path", "task_dir"}:
        task_rel = _normalize_repo_relative_path(root, value)
        if task_rel is None:
            return set()
        return set(indexes["path"].get(task_rel, set()))

    if field_name == "task":
        task_rel = _normalize_repo_relative_path(root, value)
        if task_rel is not None:
            return set(indexes["path"].get(task_rel, set()))
        if not isinstance(value, str):
            return set()
        return set(indexes["name"].get(value.strip(), set()))

    return None


def associate_events_to_task(
    root: Path,
    event: dict[str, Any],
    indexes: dict[str, dict[str, set[str]]],
) -> Optional[str]:
    candidate_sets: list[set[str]] = []
    for field_name in ("task_id", "task_dir", "task_path", "task", "record_path"):
        matches = _dataset_field_matches(root, event, indexes, field_name)
        if matches is None:
            continue
        if not matches:
            return None
        candidate_sets.append(matches)
    if not candidate_sets:
        return None
    candidates = set(candidate_sets[0])
    for matches in candidate_sets[1:]:
        candidates &= matches
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def _dataset_event_inventory(
    root: Path,
    task_dirs: Sequence[Path],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, str]]]]:
    task_paths = [rel(root, task_dir) for task_dir in task_dirs]
    associated: dict[str, list[dict[str, Any]]] = {task_path: [] for task_path in task_paths}
    warning_map: dict[str, list[dict[str, str]]] = {task_path: [] for task_path in task_paths}
    indexes = _dataset_task_indexes(root, task_dirs)

    repo_event_path = get_event_log_path(root)
    if repo_event_path.exists():
        events, malformed_count = _load_jsonl_events_with_stats(repo_event_path)
        unassociated_count = 0
        for event in events:
            task_path = associate_events_to_task(root, event, indexes)
            if task_path is None:
                unassociated_count += 1
                continue
            associated[task_path].append(event)
        if malformed_count > 0:
            for task_path in task_paths:
                _append_dataset_warning(
                    warning_map[task_path],
                    "AIWF-DATASET-INVALID-EVENT-JSON",
                    f"Malformed JSON lines were skipped from {rel(root, repo_event_path)}.",
                )
        if unassociated_count > 0:
            for task_path in task_paths:
                _append_dataset_warning(
                    warning_map[task_path],
                    "AIWF-DATASET-UNASSOCIATED-EVENTS",
                    "Some events could not be deterministically associated with a task and were not counted.",
                )
        return associated, warning_map

    for task_dir in task_dirs:
        task_path = rel(root, task_dir)
        events, malformed_count = _load_events_with_stats(task_dir)
        unassociated_count = 0
        for event in events:
            matched_task_path = associate_events_to_task(root, event, indexes)
            if matched_task_path is None:
                unassociated_count += 1
                continue
            associated[matched_task_path].append(event)
        if malformed_count > 0:
            _append_dataset_warning(
                warning_map[task_path],
                "AIWF-DATASET-INVALID-EVENT-JSON",
                f"Malformed JSON lines were skipped from {rel(root, _task_event_log_path(task_dir))}.",
            )
        if unassociated_count > 0:
            _append_dataset_warning(
                warning_map[task_path],
                "AIWF-DATASET-UNASSOCIATED-EVENTS",
                "Some events could not be deterministically associated with a task and were not counted.",
            )
    return associated, warning_map


def _dataset_relationship_count(
    front: dict[str, Any],
    field_name: str,
    warnings: list[dict[str, str]],
) -> int:
    value = front.get(field_name)
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    _append_dataset_warning(
        warnings,
        "AIWF-DATASET-INVALID-RELATIONSHIP-FIELD",
        f"Metadata field `{field_name}` is not a list and was exported as count 0.",
    )
    return 0


def collect_task_dataset_record(
    root: Path,
    task_dir: Path,
    associated_events: Sequence[dict[str, Any]],
    seed_warnings: Sequence[dict[str, str]],
) -> dict[str, Any]:
    meta_info = load_task_metadata(task_dir)
    front = meta_info.get("metadata", {})
    if not isinstance(front, dict):
        front = {}

    warnings = list(seed_warnings)
    task_id, _task_name = split_task_dir_name(task_dir)
    metadata_task_id = front.get("task_id")
    if isinstance(metadata_task_id, str) and metadata_task_id.strip():
        task_id_value = metadata_task_id.strip()
    else:
        task_id_value = task_id
        if not task_id_value:
            _append_dataset_warning(
                warnings,
                "AIWF-DATASET-MISSING-TASK-METADATA",
                "Task metadata is missing canonical task_id; directory prefix fallback was used.",
            )

    date_value = _canonical_dataset_date(front.get("created_at")) or _canonical_dataset_date(front.get("date"))
    if date_value is None:
        date_value = _dataset_date_from_task_dir(task_dir)
        if date_value is None:
            _append_dataset_warning(
                warnings,
                "AIWF-DATASET-MISSING-TASK-METADATA",
                "Task metadata is missing canonical date; no date fallback was available.",
            )

    project_value = front.get("project") if isinstance(front.get("project"), str) and front.get("project") else None
    workflow_phase_value = (
        front.get("workflow_phase")
        if isinstance(front.get("workflow_phase"), str) and front.get("workflow_phase")
        else None
    )
    if not front:
        _append_dataset_warning(
            warnings,
            "AIWF-DATASET-MISSING-TASK-METADATA",
            "Task metadata front matter is missing or unreadable.",
        )

    event_type_counts: dict[str, int] = {}
    for event in associated_events:
        event_name = _dataset_event_name(event)
        if not event_name:
            continue
        event_type_counts[event_name] = event_type_counts.get(event_name, 0) + 1
    event_types = sorted(event_type_counts.keys())

    record = {
        "task_id": task_id_value,
        "date": date_value,
        "project": project_value,
        "workflow_phase_from_metadata": workflow_phase_value,
        "event_count": len(associated_events),
        "event_types": event_types,
        "event_type_counts": event_type_counts,
        "has_task_artifact": (task_dir / "task.md").exists(),
        "has_task_record_artifact": (task_dir / "task_record.md").exists(),
        "has_self_validation_artifact": (task_dir / "self_validation.md").exists(),
        "has_validation_event": event_type_counts.get("validation", 0) > 0,
        "has_agent_review_artifact": _has_agent_review_artifact(task_dir),
        "has_review_codex_artifact": (task_dir / "review_codex.md").exists(),
        "has_review_final_artifact": (task_dir / "review_final.md").exists(),
        "has_review_event": event_type_counts.get("review", 0) > 0,
        "has_finalize_event": any(event_type_counts.get(name, 0) > 0 for name in DATASET_FINALIZE_EVENT_TYPES),
        "related_task_count": _dataset_relationship_count(front, "related_tasks", warnings),
        "blocked_by_count": _dataset_relationship_count(front, "blocked_by", warnings),
        "supersedes_count": _dataset_relationship_count(front, "supersedes", warnings),
        "export_warnings": warnings,
    }
    return {field: record[field] for field in DATASET_ALLOWED_TASK_FIELDS}


def collect_dataset_records_for_task_dirs(root: Path, task_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    associated_events, warning_map = _dataset_event_inventory(root, task_dirs)
    records: list[dict[str, Any]] = []
    for task_dir in task_dirs:
        task_path = rel(root, task_dir)
        records.append(
            collect_task_dataset_record(
                root,
                task_dir,
                associated_events.get(task_path, []),
                warning_map.get(task_path, []),
            )
        )
    return records


def collect_dataset_records(root: Path) -> list[dict[str, Any]]:
    return collect_dataset_records_for_task_dirs(root, _iter_all_task_dirs(root))


def build_dataset_export_payload(root: Path, task_dirs: Optional[Sequence[Path]] = None) -> dict[str, Any]:
    records_root = get_record_root(root)
    tasks = collect_dataset_records_for_task_dirs(root, task_dirs) if task_dirs is not None else collect_dataset_records(root)
    return {
        "dataset_version": AIWF_DATASET_SCHEMA_VERSION,
        "generated_at": _now_iso_timestamp(),
        "records_root": rel(root, records_root),
        "task_count": len(tasks),
        "tasks": tasks,
    }


def dataset_export_command(root: Path, output: str, output_format: str) -> int:
    if output_format != "json":
        raise SystemExit(f"ERROR: unsupported dataset export format: {output_format}")
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    payload = build_dataset_export_payload(root)
    result = write_dataset_output(root, target.resolve(), json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"{result.action.upper()}  {rel(root, result.path)}")
    return 0


def _package_records_manifest_output_label(root: Path, path: Path) -> str:
    try:
        return rel(root, path)
    except OSError:
        return str(path)


def _package_records_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _package_records_parse_date(raw: str, *, field: str) -> str:
    text = str(raw).strip()
    if re.fullmatch(r"\d{8}", text):
        parsed = parse_aiwf_date_arg(text, field=field)
        return f"{parsed[0:4]}-{parsed[4:6]}-{parsed[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            dt.datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise DateValidationError(
                "AIWF-DATE-003",
                f"Invalid {field} value: {text}.",
                "Use a valid calendar date in YYYY-MM-DD format, for example: 2026-06-03.",
            )
        return text
    raise DateValidationError(
        "AIWF-DATE-002",
        f"Invalid {field} format: {text}.",
        "Use YYYY-MM-DD format, for example: 2026-06-03.",
    )


def _package_records_finding(severity: str, code: str, message: str, path: Optional[str] = None) -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if path:
        item["path"] = path
    return item


def _package_records_validation_result(findings: Sequence[dict[str, str]]) -> str:
    if any(item.get("severity") == "error" for item in findings):
        return "fail"
    if any(item.get("severity") == "warn" for item in findings):
        return "warn"
    return "pass"


def _package_records_status(result: str, **fields: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"result": result}
    item.update(fields)
    return item


def _package_records_validation_status(findings: Sequence[dict[str, str]]) -> dict[str, Any]:
    workflow_result = _package_records_validation_result(findings)
    finding_count = len(findings)
    return {
        # Backward-compatible workflow evidence summary.
        "result": workflow_result,
        "finding_count": finding_count,
        "findings": list(findings),
        "scope": "workflow_evidence",
        "package_generation": _package_records_status("pass"),
        "manifest_schema": _package_records_status("pass"),
        "package_integrity": _package_records_status("pass"),
        "privacy_security": _package_records_status("pass"),
        "workflow_evidence": _package_records_status(workflow_result, finding_count=finding_count),
    }


def _package_records_result_label(result: Any) -> str:
    return {
        "pass": "PASS",
        "warn": "WARNING",
        "fail": "FAIL",
    }.get(str(result), "UNKNOWN")


def _package_records_package_path(records_root: Path, task_dir: Path) -> str:
    rel_to_records = task_dir.resolve().relative_to(records_root.resolve()).as_posix()
    return f"records/{rel_to_records}"


def _package_records_discover_tasks(root: Path) -> tuple[list[PackageRecordsTaskCandidate], list[dict[str, str]], list[dict[str, str]]]:
    records_root = get_record_root(root)
    candidates: list[PackageRecordsTaskCandidate] = []
    excluded: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []

    if not records_root.exists():
        findings.append(
            _package_records_finding(
                "warn",
                "AIWF-PACKAGE-RECORDS-NO-RECORDS-ROOT",
                f"Records root does not exist: {rel(root, records_root)}.",
            )
        )
        return candidates, excluded, findings

    for day_dir in sorted(records_root.iterdir(), key=lambda item: item.name):
        source_path = rel(root, day_dir)
        if not day_dir.is_dir():
            continue
        match = AI_DATE_RE.match(day_dir.name)
        if not match:
            excluded.append({"source_path": source_path, "reason": "invalid_date_dir"})
            continue
        task_date = f"{match.group(1)[0:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}"
        for task_dir in sorted(day_dir.iterdir(), key=lambda item: item.name):
            task_source_path = rel(root, task_dir)
            if not task_dir.is_dir():
                continue
            if not TASK_DIR_RE.match(task_dir.name):
                excluded.append({"source_path": task_source_path, "reason": "invalid_task_dir"})
                continue
            task_id, task_name = split_task_dir_name(task_dir)
            package_path = _package_records_package_path(records_root, task_dir)
            metadata_info = load_task_metadata(task_dir)
            front = metadata_info.get("metadata", {})
            metadata = front if isinstance(front, dict) else {}
            diagnostics = validate_task_metadata(root, task_dir, metadata_info)
            metadata_valid = bool(metadata) and not any(item.severity == "error" for item in diagnostics)
            for diagnostic in diagnostics:
                if diagnostic.code == "AIWF-META-OK":
                    continue
                findings.append(
                    _package_records_finding(
                        diagnostic.severity,
                        diagnostic.code,
                        diagnostic.message,
                        f"{package_path}/task.md",
                    )
                )
            task_md_missing = not (task_dir / "task.md").exists()
            if task_md_missing:
                findings.append(
                    _package_records_finding(
                        "warn",
                        "AIWF-PACKAGE-RECORDS-MISSING-TASK-MD",
                        "Task directory is missing task.md; task remains discoverable but metadata filters may not match.",
                        f"{package_path}/task.md",
                    )
                )
            candidates.append(
                PackageRecordsTaskCandidate(
                    path=task_dir,
                    source_path=task_source_path,
                    package_path=package_path,
                    date=task_date,
                    task_id=task_id or "",
                    task_name=task_name or "",
                    metadata=metadata,
                    metadata_valid=metadata_valid,
                    task_md_missing=task_md_missing,
                )
            )

    return candidates, excluded, findings


def _package_records_metadata_filter_value(candidate: PackageRecordsTaskCandidate, field_name: str) -> str:
    value = candidate.metadata.get(field_name)
    return value if isinstance(value, str) else ""


def _package_records_matches_date(
    candidate: PackageRecordsTaskCandidate,
    *,
    from_date: Optional[str],
    to_date: Optional[str],
    dates: set[str],
) -> bool:
    if dates and candidate.date not in dates:
        return False
    if from_date and candidate.date < from_date:
        return False
    if to_date and candidate.date > to_date:
        return False
    return True


def _package_records_normalize_task_path_selector(root: Path, raw: str) -> Optional[str]:
    text = raw.strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return None
    rel_text = text.replace("\\", "/").rstrip("/")
    while rel_text.startswith("./"):
        rel_text = rel_text[2:]
    if not rel_text or rel_text in {".", ".."} or rel_text.startswith("../") or "/../" in f"/{rel_text}/":
        return None
    return rel_text


def _package_records_resolve_task_selectors(
    root: Path,
    candidates: Sequence[PackageRecordsTaskCandidate],
    task_selectors: Sequence[str],
    *,
    from_date: Optional[str],
    to_date: Optional[str],
    dates: set[str],
) -> tuple[Optional[set[str]], Optional[str]]:
    if not task_selectors:
        return None, None

    date_scoped = [
        candidate
        for candidate in candidates
        if _package_records_matches_date(candidate, from_date=from_date, to_date=to_date, dates=dates)
    ]
    selected_paths: set[str] = set()
    for raw in task_selectors:
        text = raw.strip()
        if not text:
            return None, "empty --task selector"
        if TASK_ID_VALUE_RE.match(text):
            matches = [candidate for candidate in date_scoped if candidate.task_id == text]
            if len(matches) != 1:
                return None, f"ambiguous task id selector: {text}"
            selected_paths.add(matches[0].source_path)
            continue
        task_path = _package_records_normalize_task_path_selector(root, text)
        if task_path is None:
            return None, f"invalid task path selector: {text}"
        matches = [candidate for candidate in date_scoped if candidate.source_path == task_path]
        if len(matches) != 1:
            return None, f"task path selector did not match exactly one task: {text}"
        selected_paths.add(matches[0].source_path)

    return selected_paths, None


def _package_records_candidate_exclusion_reason(
    candidate: PackageRecordsTaskCandidate,
    *,
    from_date: Optional[str],
    to_date: Optional[str],
    dates: set[str],
    selected_task_paths: Optional[set[str]],
    statuses: set[str],
    workflow_phases: set[str],
    review_statuses: set[str],
    projects: set[str],
    tags: set[str],
) -> Optional[str]:
    if not _package_records_matches_date(candidate, from_date=from_date, to_date=to_date, dates=dates):
        return "filtered_by_date"
    if selected_task_paths is not None and candidate.source_path not in selected_task_paths:
        return "filtered_by_task"
    if statuses and _package_records_metadata_filter_value(candidate, "status") not in statuses:
        return "filtered_by_status"
    if workflow_phases and _package_records_metadata_filter_value(candidate, "workflow_phase") not in workflow_phases:
        return "filtered_by_workflow_phase"
    if review_statuses and _package_records_metadata_filter_value(candidate, "review_status") not in review_statuses:
        return "filtered_by_review_status"
    if projects and _package_records_metadata_filter_value(candidate, "project") not in projects:
        return "filtered_by_project"
    if tags:
        raw_tags = candidate.metadata.get("tags")
        task_tags = set(raw_tags) if isinstance(raw_tags, list) and all(isinstance(item, str) for item in raw_tags) else set()
        if not task_tags.intersection(tags):
            return "filtered_by_tag"
    return None


def _package_records_task_entry(candidate: PackageRecordsTaskCandidate) -> dict[str, str]:
    entry = {
        "task_id": candidate.task_id,
        "task_name": candidate.task_name,
        "source_path": candidate.source_path,
        "package_path": candidate.package_path,
    }
    for field_name in ("status", "workflow_phase", "review_status"):
        value = candidate.metadata.get(field_name)
        if isinstance(value, str):
            entry[field_name] = value
    return entry


def _package_records_select_tasks(
    root: Path,
    *,
    from_date: Optional[str],
    to_date: Optional[str],
    dates: set[str],
    task_selectors: Sequence[str],
    statuses: set[str],
    workflow_phases: set[str],
    review_statuses: set[str],
    projects: set[str],
    tags: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], Optional[str]]:
    candidates, excluded, findings = _package_records_discover_tasks(root)
    selected_task_paths, selector_error = _package_records_resolve_task_selectors(
        root,
        candidates,
        task_selectors,
        from_date=from_date,
        to_date=to_date,
        dates=dates,
    )
    if selector_error:
        return [], excluded, findings, selector_error

    selected: list[dict[str, str]] = []
    for candidate in candidates:
        reason = _package_records_candidate_exclusion_reason(
            candidate,
            from_date=from_date,
            to_date=to_date,
            dates=dates,
            selected_task_paths=selected_task_paths,
            statuses=statuses,
            workflow_phases=workflow_phases,
            review_statuses=review_statuses,
            projects=projects,
            tags=tags,
        )
        if reason:
            excluded.append({"source_path": candidate.source_path, "reason": reason})
        else:
            selected.append(_package_records_task_entry(candidate))

    selected.sort(key=lambda item: (item.get("source_path", ""), item.get("task_id", ""), item.get("task_name", "")))
    excluded = sorted(excluded, key=lambda item: (item.get("source_path", ""), item.get("reason", "")))
    return selected, excluded, findings, None


def _package_records_git_output(root: Path, args: Sequence[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _package_records_repository_metadata(root: Path) -> dict[str, Any]:
    inside = _package_records_git_output(root, ["rev-parse", "--is-inside-work-tree"])
    if inside != "true":
        return {
            "git_available": False,
            "dirty_tree": False,
            "privacy_profile_applied": True,
        }

    status = _package_records_git_output(root, ["status", "--porcelain=v1"])
    commit = _package_records_git_output(root, ["rev-parse", "HEAD"])
    branch = _package_records_git_output(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    metadata: dict[str, Any] = {
        "git_available": True,
        "dirty_tree": bool(status),
        "privacy_profile_applied": True,
    }
    if commit:
        metadata["commit"] = commit
    if branch:
        metadata["branch"] = branch
    return metadata


def _package_records_artifact_class(filename: str) -> str:
    if filename in {"task.md", "agent.md"}:
        return "task_content"
    if filename in AGENT_REVIEW_FILES:
        return "agent_review"
    return "workflow_evidence"


def _package_records_apply_redactions(text: str, profile: str) -> tuple[str, bool]:
    if profile != "safe":
        return text, False
    redacted = text
    changed = False
    for rule, pattern in _package_records_redaction_rule_patterns():
        replacement = f"[AIWF-REDACTED:{rule}]"
        redacted, count = re.subn(pattern, replacement, redacted)
        if count:
            changed = True
    return redacted, changed


def _package_records_artifact_bytes(path: Path, redaction_profile: str) -> tuple[bytes, str]:
    if path.is_symlink():
        return os.readlink(path).encode("utf-8"), "none"
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, "none"
    redacted, changed = _package_records_apply_redactions(text, redaction_profile)
    if not changed:
        return raw, "none"
    return redacted.encode("utf-8"), "redacted"


def _package_records_build_artifact_inventory(
    root: Path,
    selected_tasks: Sequence[dict[str, str]],
    *,
    redaction_profile: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []

    for task in stable_sort(selected_tasks, key=lambda item: item.get("package_path", "")):
        source_path = task.get("source_path", "")
        package_path = task.get("package_path", "")
        if not source_path or not package_path:
            continue
        task_dir = (root / source_path).resolve()
        package_task_path = normalize_package_path(package_path)
        for filename, source, _legacy, group in _resolved_required_artifacts(task_dir, PRE_EDIT_REQUIRED_FILE_GROUPS):
            source = task_dir / filename
            artifact_source_path = rel(root, source)
            if not source.exists() and not source.is_symlink():
                excluded.append({"source_path": artifact_source_path, "reason": "missing_task_artifact"})
                continue
            if not source.is_file() and not source.is_symlink():
                excluded.append({"source_path": artifact_source_path, "reason": "non_file_task_artifact"})
                continue
            artifact_package_path = normalize_package_path(f"{package_task_path}/{filename}")
            content, redaction = _package_records_artifact_bytes(source, redaction_profile)
            included.append(
                {
                    "source_path": artifact_source_path,
                    "package_path": artifact_package_path,
                    "artifact_class": _package_records_artifact_class(filename),
                    "bytes": len(content),
                    "mode": git_mode(source),
                    "sha256": sha256_bytes(content),
                    "redaction": redaction,
                }
            )
            if tuple(group) == AGENT_REVIEW_FILES and filename == AGENT_REVIEW_CANONICAL_FILE:
                legacy_source = task_dir / AGENT_REVIEW_LEGACY_FILE
                if legacy_source.exists() or legacy_source.is_symlink():
                    excluded.append(
                        {
                            "source_path": rel(root, legacy_source),
                            "reason": "legacy_duplicate_agent_review_alias",
                        }
                    )

    included = stable_sort(included, key=lambda item: item.get("package_path", ""))
    excluded = stable_sort(excluded, key=lambda item: (item.get("source_path", ""), item.get("reason", "")))
    return included, excluded


def _package_records_package_tree_manifest_rows(included_artifacts: Sequence[dict[str, Any]]) -> list[tuple[str, str, int, str]]:
    rows = []
    for artifact in stable_sort(included_artifacts, key=lambda item: item.get("package_path", "")):
        row = build_manifest_row(
            sha256=str(artifact["sha256"]),
            git_mode=str(artifact.get("mode", "100644")),
            size=int(artifact["bytes"]),
            package_relative_path=str(artifact["package_path"]),
        )
        rows.append((row.sha256, row.git_mode, row.size, row.package_relative_path))
    return rows


def _package_records_package_tree_manifest_tsv(included_artifacts: Sequence[dict[str, Any]]) -> str:
    rows = []
    for sha256, mode, size, package_path in _package_records_package_tree_manifest_rows(included_artifacts):
        rows.append(build_manifest_row(sha256=sha256, git_mode=mode, size=size, package_relative_path=package_path))
    return "".join(manifest_row_tsv(row) for row in rows)


def _package_records_identity(included_artifacts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    tree_manifest = _package_records_package_tree_manifest_tsv(included_artifacts)
    return {
        "hash_policy": AIWF_PACKAGE_RECORDS_HASH_POLICY,
        "reproducible_evidence_sha256": sha256_bytes(tree_manifest.encode("utf-8")),
        "content_file_count": len(included_artifacts),
        "content_total_bytes": sum(int(item.get("bytes", 0)) for item in included_artifacts),
        "excluded_identity_fields": [
            "generated_at_utc",
            "repository.git_available",
            "repository.dirty_tree",
            "repository.commit",
            "repository.branch",
            "host_platform",
            "runtime_duration",
            "archive_timestamp",
            "temporary_paths",
        ],
    }


def _package_records_dataset_metadata(
    root: Path,
    selected_tasks: Sequence[dict[str, str]],
    *,
    include_dataset: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if not include_dataset:
        return {"included": False, "warning_count": 0}, []

    task_dirs = [(root / task["source_path"]).resolve() for task in selected_tasks if task.get("source_path")]
    payload = build_dataset_export_payload(root, task_dirs=task_dirs)
    warnings: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    for task in payload.get("tasks", []):
        if not isinstance(task, Mapping):
            continue
        task_id = task.get("task_id")
        task_label = f"task {task_id}" if isinstance(task_id, str) and task_id else "a selected task"
        task_warnings = task.get("export_warnings")
        if not isinstance(task_warnings, list):
            continue
        for warning in task_warnings:
            if not isinstance(warning, Mapping):
                continue
            code = warning.get("code")
            message = warning.get("message")
            if not isinstance(code, str) or not isinstance(message, str):
                continue
            warning_item = {"code": code, "message": message}
            warnings.append(warning_item)
            findings.append(
                _package_records_finding(
                    "warn",
                    "AIWF-PACKAGE-RECORDS-DATASET-WARNING",
                    f"{task_label}: {code}: {message}",
                    AIWF_PACKAGE_RECORDS_DATASET_PATH,
                )
            )

    return (
        {
            "included": True,
            "schema_version": str(payload.get("dataset_version", AIWF_DATASET_SCHEMA_VERSION)),
            "path": AIWF_PACKAGE_RECORDS_DATASET_PATH,
            "warning_count": len(warnings),
        },
        stable_sort(findings, key=lambda item: (item.get("message", ""), item.get("path", ""))),
    )


def _package_records_read_artifact_text(root: Path, artifact: Mapping[str, Any]) -> str:
    source_path = artifact.get("source_path")
    if not isinstance(source_path, str) or not source_path:
        return ""
    source = (root / source_path).resolve()
    if source.is_symlink():
        return os.readlink(source)
    if not source.is_file():
        return ""
    return source.read_text(encoding="utf-8", errors="replace")


def _package_records_secret_rules(text: str) -> list[tuple[str, int]]:
    rules = [
        ("private_key", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
        ("bearer_token", r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        (
            "access_token",
            r"(?i)\b(?:access[_-]?token|auth[_-]?token|api[_-]?key|secret[_-]?key|credential)\b\s*[:=]\s*['\"]?[A-Za-z0-9][A-Za-z0-9_._~+/=-]{7,}",
        ),
        ("password", r"(?i)\b(?:password|passwd|pwd)\b\s*[:=]\s*['\"]?[^'\"\s]{4,}"),
    ]
    matches: list[tuple[str, int]] = []
    for rule, pattern in rules:
        count = len(list(re.finditer(pattern, text)))
        if count:
            matches.append((rule, count))
    return matches


def _package_records_redaction_rule_patterns() -> list[tuple[str, str]]:
    users_root = r"/Users" + r"/[A-Za-z0-9._-]+(?:/[^\s'\"<>)]*)?"
    home_root = r"/home" + r"/[A-Za-z0-9._-]+(?:/[^\s'\"<>)]*)?"
    private_tmp_root = r"/private" + r"/tmp/[^\s'\"<>)]*"
    windows_users_root = r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\[^\s'\"<>)]*)?"
    return [
        (
            "internal_url",
            r"(?i)https?://(?:localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|[a-z0-9.-]+\.(?:local|lan|internal|corp))(?:[^\s'\"<>)]*)?",
        ),
        (
            "absolute_path",
            rf"(?:{users_root}|{home_root}|{private_tmp_root}|{windows_users_root})",
        ),
        (
            "private_ip",
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b",
        ),
        ("hostname", r"(?i)\b(?:localhost|[a-z0-9][a-z0-9-]*\.(?:local|lan|internal|corp))\b"),
    ]


def _package_records_redaction_rules(text: str) -> list[tuple[str, int]]:
    rules = _package_records_redaction_rule_patterns()
    matches: list[tuple[str, int]] = []
    for rule, pattern in rules:
        count = len(list(re.finditer(pattern, text)))
        if count:
            matches.append((rule, count))
    return matches


def _package_records_prohibited_artifact_reason(path: Path) -> Optional[str]:
    name = path.name.lower()
    suffixes = tuple(suffix.lower() for suffix in path.suffixes)
    if name in {".env", ".netrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}:
        return "prohibited_secret_path"
    if suffixes and suffixes[-1] in {".pem", ".key", ".p12", ".pfx"}:
        return "prohibited_secret_path"
    return None


def _package_records_detect_prohibited_artifacts(
    root: Path,
    selected_tasks: Sequence[dict[str, str]],
    included_artifacts: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    included_sources = {
        artifact.get("source_path")
        for artifact in included_artifacts
        if isinstance(artifact.get("source_path"), str)
    }
    excluded: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    for task in selected_tasks:
        source_path = task.get("source_path")
        if not source_path:
            continue
        task_dir = (root / source_path).resolve()
        if not task_dir.exists():
            continue
        for path in sorted((item for item in task_dir.rglob("*") if item.is_file() or item.is_symlink()), key=lambda item: rel(root, item)):
            source_rel = rel(root, path)
            if source_rel in included_sources:
                continue
            reason = _package_records_prohibited_artifact_reason(path)
            if not reason:
                continue
            excluded.append({"source_path": source_rel, "reason": reason})
            findings.append(
                _package_records_finding(
                    "warn",
                    "AIWF-PACKAGE-RECORDS-PROHIBITED-ARTIFACT",
                    f"Prohibited artifact path was excluded: {source_rel}.",
                )
            )
    return (
        stable_sort(excluded, key=lambda item: (item.get("source_path", ""), item.get("reason", ""))),
        stable_sort(findings, key=lambda item: (item.get("message", ""), item.get("path", ""))),
    )


def _package_records_redaction_summary(
    root: Path,
    *,
    profile: str,
    included_artifacts: Sequence[dict[str, Any]],
    selected_tasks: Sequence[dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    redaction_report: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []

    for artifact in stable_sort(included_artifacts, key=lambda item: item.get("package_path", "")):
        source_path = str(artifact.get("source_path", ""))
        package_path = str(artifact.get("package_path", ""))
        text = _package_records_read_artifact_text(root, artifact)
        for rule, count in _package_records_secret_rules(text):
            findings.append(
                _package_records_finding(
                    "error",
                    "AIWF-PACKAGE-RECORDS-SECRET-DETECTED",
                    f"Detected {rule} in {source_path}; package records fails closed.",
                    package_path,
                )
            )

        if profile == "safe":
            for rule, count in _package_records_redaction_rules(text):
                redaction_report.append(
                    {
                        "source_path": source_path,
                        "package_path": package_path,
                        "rule": rule,
                        "action": "would_redact",
                        "count": count,
                    }
                )

    excluded_artifacts, exclusion_findings = _package_records_detect_prohibited_artifacts(root, selected_tasks, included_artifacts)
    findings.extend(exclusion_findings)
    redaction_report = stable_sort(
        redaction_report,
        key=lambda item: (str(item.get("package_path", "")), str(item.get("rule", ""))),
    )
    redaction_count = sum(int(item.get("count", 0)) for item in redaction_report)
    summary = {
        "profile": profile,
        "redaction_count": redaction_count,
        "excluded_artifact_count": len(excluded_artifacts),
        "secret_finding_count": sum(1 for item in findings if item.get("code") == "AIWF-PACKAGE-RECORDS-SECRET-DETECTED"),
        "redaction_report": redaction_report,
        "exclusion_report": excluded_artifacts,
    }
    return (
        summary,
        stable_sort(findings, key=lambda item: (item.get("severity", ""), item.get("code", ""), item.get("message", ""), item.get("path", ""))),
        excluded_artifacts,
    )


def _package_records_event_field(event: Mapping[str, Any], field_name: str) -> Any:
    if field_name in event:
        return event.get(field_name)
    payload = event.get("payload")
    if isinstance(payload, Mapping) and field_name in payload:
        return payload.get(field_name)
    return None


def _package_records_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    if not path.exists():
        return [], []
    events: list[dict[str, Any]] = []
    malformed_lines: list[int] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            malformed_lines.append(line_number)
            continue
        if isinstance(item, dict):
            events.append({"event": item, "source_line": line_number})
        else:
            malformed_lines.append(line_number)
    return events, malformed_lines


def _package_records_selected_task_indexes(selected_tasks: Sequence[dict[str, str]]) -> dict[str, Any]:
    path_index: dict[str, dict[str, str]] = {}
    id_index: dict[str, list[dict[str, str]]] = {}
    for task in selected_tasks:
        source_path = task.get("source_path")
        task_id = task.get("task_id")
        if source_path:
            path_index[source_path] = task
        if task_id:
            id_index.setdefault(task_id, []).append(task)
    return {"path": path_index, "id": id_index}


def _package_records_normalize_event_task_path(root: Path, value: Any) -> Optional[str]:
    normalized = _normalize_repo_relative_path(root, value)
    return normalized.replace("\\", "/") if normalized else None


def _package_records_associate_global_event(
    root: Path,
    event: Mapping[str, Any],
    indexes: Mapping[str, Any],
) -> tuple[Optional[str], Optional[dict[str, str]]]:
    path_index: Mapping[str, dict[str, str]] = indexes.get("path", {})
    id_index: Mapping[str, list[dict[str, str]]] = indexes.get("id", {})

    task_path_value = _package_records_event_field(event, "task_path")
    if task_path_value is not None:
        task_path = _package_records_normalize_event_task_path(root, task_path_value)
        if task_path is not None and task_path in path_index:
            return task_path, None
        return None, None

    task_id_value = _package_records_event_field(event, "task_id")
    if task_id_value is not None:
        task_id = str(task_id_value).strip()
        matches = id_index.get(task_id, [])
        if len(matches) == 1:
            return matches[0].get("source_path"), None
        if len(matches) > 1:
            return None, _package_records_finding(
                "warn",
                "AIWF-PACKAGE-RECORDS-AMBIGUOUS-EVENT-TASK-ID",
                f"Global event task_id is ambiguous within selected tasks: {task_id}.",
            )
        return None, None

    task_dir_value = _package_records_event_field(event, "task_dir")
    if task_dir_value is not None:
        task_path = _package_records_normalize_event_task_path(root, task_dir_value)
        if task_path is not None and task_path in path_index:
            return task_path, None
        return None, None

    record_path_value = _package_records_event_field(event, "record_path")
    if record_path_value is not None:
        record_path = _package_records_normalize_event_task_path(root, record_path_value)
        if record_path is None:
            return None, None
        matches = [task_path for task_path in path_index if record_path == task_path or record_path.startswith(f"{task_path}/")]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, _package_records_finding(
                "warn",
                "AIWF-PACKAGE-RECORDS-AMBIGUOUS-EVENT-LEGACY-MAPPING",
                f"Global event legacy record_path is ambiguous: {record_path}.",
            )
    return None, None


def _package_records_parse_event_timestamp(event: Mapping[str, Any]) -> Optional[dt.datetime]:
    value = event.get("timestamp")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _package_records_canonical_event_sort_key(item: Mapping[str, Any]) -> tuple[int, str, str, int]:
    parsed = item.get("parsed_timestamp")
    if isinstance(parsed, dt.datetime):
        return (0, parsed.isoformat(), str(item.get("source_path", "")), int(item.get("source_line", 0)))
    return (1, "", str(item.get("source_path", "")), int(item.get("source_line", 0)))


def _package_records_event_plan(
    root: Path,
    selected_tasks: Sequence[dict[str, str]],
    *,
    include_global_events: bool,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    findings: list[dict[str, str]] = []
    sources: list[dict[str, Any]] = []
    canonical_events: list[dict[str, Any]] = []
    task_local_count = 0
    global_count = 0
    malformed_count = 0
    unassociated_count = 0
    selected_indexes = _package_records_selected_task_indexes(selected_tasks)

    for task in stable_sort(selected_tasks, key=lambda item: item.get("source_path", "")):
        source_path = task.get("source_path")
        if not source_path:
            continue
        event_path = root / source_path / ".aiwf" / "events.jsonl"
        if not event_path.exists():
            continue
        source_rel = rel(root, event_path)
        rows, malformed_lines = _package_records_jsonl_rows(event_path)
        task_local_count += len(rows)
        malformed_count += len(malformed_lines)
        sources.append(
            {
                "source_path": source_rel,
                "event_count": len(rows),
                "malformed_count": len(malformed_lines),
            }
        )
        for line_number in malformed_lines:
            findings.append(
                _package_records_finding(
                    "warn",
                    "AIWF-PACKAGE-RECORDS-MALFORMED-EVENT",
                    f"Malformed task-local event JSON at line {line_number}.",
                    source_rel,
                )
            )
        for row in rows:
            event = row["event"]
            line_number = int(row["source_line"])
            parsed_timestamp = _package_records_parse_event_timestamp(event)
            if parsed_timestamp is None:
                findings.append(
                    _package_records_finding(
                        "warn",
                        "AIWF-PACKAGE-RECORDS-INVALID-EVENT-TIMESTAMP",
                        f"Task-local event timestamp is missing or invalid at line {line_number}.",
                        source_rel,
                    )
                )
            referenced_path = _package_records_event_field(event, "task_path")
            normalized_path = _package_records_normalize_event_task_path(root, referenced_path) if referenced_path is not None else None
            if normalized_path is not None and normalized_path not in selected_indexes["path"]:
                findings.append(
                    _package_records_finding(
                        "warn",
                        "AIWF-PACKAGE-RECORDS-EVENT-TASK-REFERENCE",
                        f"Task-local event references a task outside the selected set at line {line_number}: {normalized_path}.",
                        source_rel,
                    )
                )
            task_id_value = _package_records_event_field(event, "task_id")
            if task_id_value is not None and str(task_id_value).strip() not in selected_indexes["id"]:
                findings.append(
                    _package_records_finding(
                        "warn",
                        "AIWF-PACKAGE-RECORDS-EVENT-TASK-REFERENCE",
                        f"Task-local event references a task_id outside the selected set at line {line_number}: {task_id_value}.",
                        source_rel,
                    )
                )
            canonical_events.append(
                {
                    "event": event,
                    "source_path": source_rel,
                    "source_line": line_number,
                    "parsed_timestamp": parsed_timestamp,
                }
            )

    if include_global_events:
        global_path = get_event_log_path(root)
        if global_path.exists():
            source_rel = rel(root, global_path)
            rows, malformed_lines = _package_records_jsonl_rows(global_path)
            associated_count = 0
            malformed_count += len(malformed_lines)
            for line_number in malformed_lines:
                findings.append(
                    _package_records_finding(
                        "warn",
                        "AIWF-PACKAGE-RECORDS-MALFORMED-EVENT",
                        f"Malformed global event JSON at line {line_number}.",
                        source_rel,
                    )
                )
            for row in rows:
                event = row["event"]
                line_number = int(row["source_line"])
                task_path, association_finding = _package_records_associate_global_event(root, event, selected_indexes)
                if association_finding is not None:
                    association_finding["path"] = source_rel
                    association_finding["message"] = f"{association_finding['message']} Line {line_number}."
                    findings.append(association_finding)
                    unassociated_count += 1
                    continue
                if task_path is None:
                    unassociated_count += 1
                    findings.append(
                        _package_records_finding(
                            "warn",
                            "AIWF-PACKAGE-RECORDS-UNASSOCIATED-EVENT",
                            f"Global event was not deterministically associated at line {line_number}.",
                            source_rel,
                        )
                    )
                    continue
                parsed_timestamp = _package_records_parse_event_timestamp(event)
                if parsed_timestamp is None:
                    findings.append(
                        _package_records_finding(
                            "warn",
                            "AIWF-PACKAGE-RECORDS-INVALID-EVENT-TIMESTAMP",
                            f"Global event timestamp is missing or invalid at line {line_number}.",
                            source_rel,
                        )
                    )
                associated_count += 1
                global_count += 1
                canonical_events.append(
                    {
                        "event": event,
                        "source_path": source_rel,
                        "source_line": line_number,
                        "parsed_timestamp": parsed_timestamp,
                    }
                )
            sources.append(
                {
                    "source_path": source_rel,
                    "event_count": associated_count,
                    "malformed_count": len(malformed_lines),
                }
            )

    canonical_events = stable_sort(canonical_events, key=_package_records_canonical_event_sort_key)
    event_summary = {
        "task_local_event_count": task_local_count,
        "global_event_count": global_count,
        "canonical_event_count": len(canonical_events),
        "malformed_event_count": malformed_count,
        "unassociated_event_count": unassociated_count,
        "sources": stable_sort(sources, key=lambda item: item.get("source_path", "")),
    }
    findings = stable_sort(findings, key=lambda item: (item.get("path", ""), item.get("code", ""), item.get("message", "")))
    return event_summary, findings, canonical_events


def _package_records_event_summary(
    root: Path,
    selected_tasks: Sequence[dict[str, str]],
    *,
    include_global_events: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    event_summary, findings, _canonical_events = _package_records_event_plan(
        root,
        selected_tasks,
        include_global_events=include_global_events,
    )
    return event_summary, findings


def _package_records_selected_task_dirs(root: Path, selected_tasks: Sequence[dict[str, str]]) -> list[Path]:
    return [(root / task["source_path"]).resolve() for task in selected_tasks if task.get("source_path")]


def _package_records_csv(rows: Sequence[Sequence[object]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for row in rows:
        writer.writerow([str(value) for value in row])
    return output.getvalue()


def _package_records_task_inventory_csv(selected_tasks: Sequence[dict[str, str]]) -> str:
    rows: list[list[object]] = [["task_id", "task_name", "source_path", "package_path", "status", "workflow_phase", "review_status"]]
    for task in stable_sort(selected_tasks, key=lambda item: item.get("package_path", "")):
        rows.append(
            [
                task.get("task_id", ""),
                task.get("task_name", ""),
                task.get("source_path", ""),
                task.get("package_path", ""),
                task.get("status", ""),
                task.get("workflow_phase", ""),
                task.get("review_status", ""),
            ]
        )
    return _package_records_csv(rows)


def _package_records_event_inventory_csv(canonical_events: Sequence[dict[str, Any]]) -> str:
    rows: list[list[object]] = [["source_path", "source_line", "event_name", "timestamp"]]
    for item in stable_sort(canonical_events, key=_package_records_canonical_event_sort_key):
        event = item.get("event")
        event_mapping = event if isinstance(event, Mapping) else {}
        timestamp = event_mapping.get("timestamp") if isinstance(event_mapping.get("timestamp"), str) else ""
        rows.append(
            [
                item.get("source_path", ""),
                item.get("source_line", ""),
                _dataset_event_name(dict(event_mapping)),
                timestamp,
            ]
        )
    return _package_records_csv(rows)


def _package_records_artifact_inventory_tsv(included_artifacts: Sequence[dict[str, Any]]) -> str:
    rows: list[list[object]] = [["source_path", "package_path", "artifact_class", "bytes", "sha256", "mode", "redaction"]]
    for artifact in stable_sort(included_artifacts, key=lambda item: item.get("package_path", "")):
        rows.append(
            [
                artifact.get("source_path", ""),
                artifact.get("package_path", ""),
                artifact.get("artifact_class", ""),
                artifact.get("bytes", 0),
                artifact.get("sha256", ""),
                artifact.get("mode", ""),
                artifact.get("redaction", ""),
            ]
        )
    return stable_tsv_dump(rows)


def _package_records_canonical_events_jsonl(canonical_events: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in stable_sort(canonical_events, key=_package_records_canonical_event_sort_key):
        event = item.get("event")
        if isinstance(event, Mapping):
            lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "".join(f"{line}\n" for line in lines)


def _package_records_summary_md(manifest: Mapping[str, Any]) -> str:
    validation = manifest.get("validation", {})
    if not isinstance(validation, Mapping):
        validation = {}
    workflow_evidence = validation.get("workflow_evidence", {})
    if not isinstance(workflow_evidence, Mapping):
        workflow_evidence = {}
    workflow_finding_count = workflow_evidence.get("finding_count", validation.get("finding_count", 0))
    return "\n".join(
        [
            "# AIWF Records Package",
            "",
            f"- Package type: {manifest.get('package_type', '')}",
            f"- Package version: {manifest.get('package_version', '')}",
            f"- Selected tasks: {len(manifest.get('selected_tasks', []))}",
            f"- Artifact files: {len(manifest.get('artifacts', {}).get('included', [])) if isinstance(manifest.get('artifacts'), Mapping) else 0}",
            f"- Canonical events: {manifest.get('events', {}).get('canonical_event_count', 0) if isinstance(manifest.get('events'), Mapping) else 0}",
            f"- Dataset included: {manifest.get('dataset', {}).get('included', False) if isinstance(manifest.get('dataset'), Mapping) else False}",
            f"- Redaction profile: {manifest.get('redaction_profile', '')}",
            f"- Package Generation: {_package_records_result_label(validation.get('package_generation', {}).get('result') if isinstance(validation.get('package_generation'), Mapping) else '')}",
            f"- Manifest Schema: {_package_records_result_label(validation.get('manifest_schema', {}).get('result') if isinstance(validation.get('manifest_schema'), Mapping) else '')}",
            f"- Package Integrity: {_package_records_result_label(validation.get('package_integrity', {}).get('result') if isinstance(validation.get('package_integrity'), Mapping) else '')}",
            f"- Privacy/Security: {_package_records_result_label(validation.get('privacy_security', {}).get('result') if isinstance(validation.get('privacy_security'), Mapping) else '')}",
            f"- Workflow Evidence Findings: {_package_records_result_label(workflow_evidence.get('result', validation.get('result', '')))} ({workflow_finding_count} findings packaged)",
            "",
            "Workflow evidence findings describe historical source workflow records packaged for review. They do not by themselves mean package generation failed.",
            "",
        ]
    )


def _package_records_file_rows(
    files: Mapping[str, bytes],
    artifact_modes: Optional[Mapping[str, str]] = None,
) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    modes = artifact_modes or {}
    for package_path, content in sorted(files.items()):
        rows.append(
            build_manifest_row(
                sha256=sha256_bytes(content),
                git_mode=modes.get(package_path, "100644"),
                size=len(content),
                package_relative_path=package_path,
            )
        )
    return rows


def _package_records_file_manifest_tsv(
    files: Mapping[str, bytes],
    artifact_modes: Optional[Mapping[str, str]] = None,
) -> str:
    return "".join(manifest_row_tsv(row) for row in _package_records_file_rows(files, artifact_modes))


def _package_records_package_files(
    root: Path,
    manifest: Mapping[str, Any],
    selected_tasks: Sequence[dict[str, str]],
    *,
    redaction_profile: str,
    include_global_events: bool,
) -> dict[str, bytes]:
    event_summary, _event_findings, canonical_events = _package_records_event_plan(
        root,
        selected_tasks,
        include_global_events=include_global_events,
    )
    if event_summary.get("canonical_event_count") != manifest.get("events", {}).get("canonical_event_count"):
        raise SystemExit("ERROR: package records event inventory changed while building package")

    files: dict[str, bytes] = {}
    artifact_modes: dict[str, str] = {}
    artifacts = manifest.get("artifacts", {}).get("included", []) if isinstance(manifest.get("artifacts"), Mapping) else []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        source_path = artifact.get("source_path")
        package_path = artifact.get("package_path")
        if not isinstance(source_path, str) or not isinstance(package_path, str):
            continue
        source = (root / source_path).resolve()
        content, redaction = _package_records_artifact_bytes(source, redaction_profile)
        if sha256_bytes(content) != artifact.get("sha256") or len(content) != artifact.get("bytes") or redaction != artifact.get("redaction"):
            raise SystemExit(f"ERROR: package records artifact changed while building package: {source_path}")
        package_path = normalize_package_path(package_path)
        files[package_path] = content
        artifact_modes[package_path] = str(artifact.get("mode", "100644"))

    dataset = manifest.get("dataset")
    if isinstance(dataset, Mapping) and dataset.get("included") is True:
        dataset_path = normalize_package_path(str(dataset.get("path", AIWF_PACKAGE_RECORDS_DATASET_PATH)))
        dataset_payload = build_dataset_export_payload(root, task_dirs=_package_records_selected_task_dirs(root, selected_tasks))
        dataset_payload["generated_at"] = "1970-01-01T00:00:00Z"
        files[dataset_path] = stable_json_dump(dataset_payload).encode("utf-8")

    files["events/events.jsonl"] = _package_records_canonical_events_jsonl(canonical_events).encode("utf-8")
    files["task_inventory.csv"] = _package_records_task_inventory_csv(selected_tasks).encode("utf-8")
    files["event_inventory.csv"] = _package_records_event_inventory_csv(canonical_events).encode("utf-8")
    files["artifact_inventory.tsv"] = _package_records_artifact_inventory_tsv(artifacts).encode("utf-8")
    files["package_manifest.json"] = stable_json_dump(manifest).encode("utf-8")
    files["package_summary.md"] = _package_records_summary_md(manifest).encode("utf-8")
    files["integrity/redaction_report.json"] = stable_json_dump({"redaction_report": manifest.get("redaction", {}).get("redaction_report", [])}).encode("utf-8")
    files["integrity/exclusion_report.json"] = stable_json_dump({"exclusion_report": manifest.get("redaction", {}).get("exclusion_report", [])}).encode("utf-8")

    tree_manifest = _package_records_file_manifest_tsv(files, artifact_modes).encode("utf-8")
    files["integrity/package_tree_manifest.tsv"] = tree_manifest
    package_identity = {
        "hash_policy": AIWF_PACKAGE_RECORDS_HASH_POLICY,
        "package_tree_sha256": sha256_bytes(tree_manifest),
        "package_file_count": len(files) + 1,
        "package_total_bytes": sum(len(content) for content in files.values()),
    }
    files["integrity/package_identity.json"] = stable_json_dump(package_identity).encode("utf-8")
    return {normalize_package_path(path): content for path, content in sorted(files.items())}


def _package_records_write_directory(output_path: Path, files: Mapping[str, bytes]) -> None:
    ensure_dir(output_path)
    for package_path, content in sorted(files.items()):
        target = output_path / package_path
        ensure_dir(target.parent)
        target.write_bytes(content)


def _package_records_write_zip(output_path: Path, files: Mapping[str, bytes]) -> None:
    ensure_dir(output_path.parent)
    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for package_path, content in sorted(files.items()):
            archive_path = f"{AIWF_PACKAGE_RECORDS_ROOT_DIR}/{package_path}"
            info = zipfile.ZipInfo(archive_path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, content)


def _package_records_manifest_schema_path() -> Path:
    return AIWF_BIN_DIR.parent / "docs" / "schemas" / AIWF_PACKAGE_RECORDS_MANIFEST_SCHEMA_FILENAME


def _package_records_manifest_schema() -> dict[str, Any]:
    schema_path = _package_records_manifest_schema_path()
    try:
        data = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: failed to load package records manifest schema: {schema_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: package records manifest schema is not a JSON object: {schema_path}")
    return data


def _package_records_schema_error(path: str, message: str) -> dict[str, str]:
    return {"path": path, "message": message}


def _package_records_schema_required(schema: Mapping[str, Any], *path: str) -> list[str]:
    node: Any = schema
    for key in path:
        if not isinstance(node, Mapping):
            return []
        node = node.get(key, {})
    required = node.get("required") if isinstance(node, Mapping) else None
    return list(required) if isinstance(required, list) and all(isinstance(item, str) for item in required) else []


def _package_records_schema_const(schema: Mapping[str, Any], *path: str) -> Optional[str]:
    node: Any = schema
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key, {})
    value = node.get("const") if isinstance(node, Mapping) else None
    return value if isinstance(value, str) else None


def _package_records_schema_enum(schema: Mapping[str, Any], *path: str) -> set[str]:
    node: Any = schema
    for key in path:
        if not isinstance(node, Mapping):
            return set()
        node = node.get(key, {})
    values = node.get("enum") if isinstance(node, Mapping) else None
    return {item for item in values if isinstance(item, str)} if isinstance(values, list) else set()


def _package_records_validate_manifest_schema(
    manifest: Mapping[str, Any],
    schema: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, str]]:
    schema = schema or _package_records_manifest_schema()
    errors: list[dict[str, str]] = []

    for field_name in _package_records_schema_required(schema):
        if field_name not in manifest:
            errors.append(_package_records_schema_error(f"$.{field_name}", "required field is missing"))

    for field_name, expected in (
        ("schema_version", _package_records_schema_const(schema, "properties", "schema_version")),
        ("package_type", _package_records_schema_const(schema, "properties", "package_type")),
        ("package_version", _package_records_schema_const(schema, "properties", "package_version")),
    ):
        if expected is not None and manifest.get(field_name) != expected:
            errors.append(_package_records_schema_error(f"$.{field_name}", f'expected "{expected}"'))

    capabilities = manifest.get("capabilities")
    if isinstance(capabilities, Mapping):
        for field_name in _package_records_schema_required(schema, "properties", "capabilities"):
            value = capabilities.get(field_name)
            if not isinstance(value, bool):
                errors.append(_package_records_schema_error(f"$.capabilities.{field_name}", "expected boolean"))
    elif "capabilities" in manifest:
        errors.append(_package_records_schema_error("$.capabilities", "expected object"))

    options = manifest.get("options")
    if isinstance(options, Mapping):
        format_values = _package_records_schema_enum(schema, "properties", "options", "properties", "format")
        if format_values and options.get("format") not in format_values:
            errors.append(
                _package_records_schema_error(
                    "$.options.format",
                    "expected one of: " + ", ".join(sorted(format_values)),
                )
            )
        for field_name in ("include_dataset", "include_global_events", "include_related", "strict"):
            if not isinstance(options.get(field_name), bool):
                errors.append(_package_records_schema_error(f"$.options.{field_name}", "expected boolean"))
        redaction_values = _package_records_schema_enum(schema, "properties", "options", "properties", "redaction_profile")
        if redaction_values and options.get("redaction_profile") not in redaction_values:
            errors.append(
                _package_records_schema_error(
                    "$.options.redaction_profile",
                    "expected one of: " + ", ".join(sorted(redaction_values)),
                )
            )
    elif "options" in manifest:
        errors.append(_package_records_schema_error("$.options", "expected object"))

    top_redaction_values = _package_records_schema_enum(schema, "properties", "redaction_profile")
    if top_redaction_values and manifest.get("redaction_profile") not in top_redaction_values:
        errors.append(
            _package_records_schema_error(
                "$.redaction_profile",
                "expected one of: " + ", ".join(sorted(top_redaction_values)),
            )
        )
    for field_name in ("redaction_count", "excluded_artifact_count"):
        value = manifest.get(field_name)
        if not isinstance(value, int) or value < 0:
            errors.append(_package_records_schema_error(f"$.{field_name}", "expected non-negative integer"))

    artifact_classes = _package_records_schema_enum(
        schema,
        "$defs",
        "artifact_entry",
        "properties",
        "artifact_class",
    )
    redaction_values = _package_records_schema_enum(
        schema,
        "$defs",
        "artifact_entry",
        "properties",
        "redaction",
    )
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, Mapping):
        included = artifacts.get("included")
        if isinstance(included, list):
            for index, artifact in enumerate(included):
                path = f"$.artifacts.included[{index}]"
                if not isinstance(artifact, Mapping):
                    errors.append(_package_records_schema_error(path, "expected object"))
                    continue
                artifact_class = artifact.get("artifact_class")
                if artifact_classes and artifact_class not in artifact_classes:
                    errors.append(
                        _package_records_schema_error(
                            f"{path}.artifact_class",
                            "expected one of: " + ", ".join(sorted(artifact_classes)),
                        )
                    )
                redaction = artifact.get("redaction")
                if redaction_values and redaction not in redaction_values:
                    errors.append(
                        _package_records_schema_error(
                            f"{path}.redaction",
                            "expected one of: " + ", ".join(sorted(redaction_values)),
                        )
                    )
                if not isinstance(artifact.get("bytes"), int) or int(artifact.get("bytes", -1)) < 0:
                    errors.append(_package_records_schema_error(f"{path}.bytes", "expected non-negative integer"))
                sha256 = artifact.get("sha256")
                if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                    errors.append(_package_records_schema_error(f"{path}.sha256", "expected sha256 hex string"))
        elif "included" in artifacts:
            errors.append(_package_records_schema_error("$.artifacts.included", "expected array"))
    elif "artifacts" in manifest:
        errors.append(_package_records_schema_error("$.artifacts", "expected object"))

    events = manifest.get("events")
    if isinstance(events, Mapping):
        for field_name in (
            "task_local_event_count",
            "global_event_count",
            "canonical_event_count",
            "malformed_event_count",
            "unassociated_event_count",
        ):
            value = events.get(field_name)
            if not isinstance(value, int) or value < 0:
                errors.append(_package_records_schema_error(f"$.events.{field_name}", "expected non-negative integer"))
        sources = events.get("sources")
        if isinstance(sources, list):
            for index, source in enumerate(sources):
                path = f"$.events.sources[{index}]"
                if not isinstance(source, Mapping):
                    errors.append(_package_records_schema_error(path, "expected object"))
                    continue
                if not isinstance(source.get("source_path"), str) or not source.get("source_path"):
                    errors.append(_package_records_schema_error(f"{path}.source_path", "expected non-empty string"))
                event_count = source.get("event_count")
                if not isinstance(event_count, int) or event_count < 0:
                    errors.append(_package_records_schema_error(f"{path}.event_count", "expected non-negative integer"))
                if "malformed_count" in source:
                    malformed = source.get("malformed_count")
                    if not isinstance(malformed, int) or malformed < 0:
                        errors.append(_package_records_schema_error(f"{path}.malformed_count", "expected non-negative integer"))
        elif "sources" in events:
            errors.append(_package_records_schema_error("$.events.sources", "expected array"))
    elif "events" in manifest:
        errors.append(_package_records_schema_error("$.events", "expected object"))

    dataset = manifest.get("dataset")
    if isinstance(dataset, Mapping):
        if not isinstance(dataset.get("included"), bool):
            errors.append(_package_records_schema_error("$.dataset.included", "expected boolean"))
        if dataset.get("included") is True:
            if not isinstance(dataset.get("schema_version"), str) or not dataset.get("schema_version"):
                errors.append(_package_records_schema_error("$.dataset.schema_version", "expected non-empty string"))
            dataset_path = dataset.get("path")
            if not isinstance(dataset_path, str) or not dataset_path:
                errors.append(_package_records_schema_error("$.dataset.path", "expected non-empty package-relative path"))
            else:
                try:
                    normalize_package_path(dataset_path)
                except ValueError as exc:
                    errors.append(_package_records_schema_error("$.dataset.path", str(exc)))
        if "warning_count" in dataset:
            warning_count = dataset.get("warning_count")
            if not isinstance(warning_count, int) or warning_count < 0:
                errors.append(_package_records_schema_error("$.dataset.warning_count", "expected non-negative integer"))
    elif "dataset" in manifest:
        errors.append(_package_records_schema_error("$.dataset", "expected object"))

    redaction = manifest.get("redaction")
    if isinstance(redaction, Mapping):
        if top_redaction_values and redaction.get("profile") not in top_redaction_values:
            errors.append(
                _package_records_schema_error(
                    "$.redaction.profile",
                    "expected one of: " + ", ".join(sorted(top_redaction_values)),
                )
            )
        for field_name in ("redaction_count", "excluded_artifact_count", "secret_finding_count"):
            value = redaction.get(field_name)
            if not isinstance(value, int) or value < 0:
                errors.append(_package_records_schema_error(f"$.redaction.{field_name}", "expected non-negative integer"))
        report = redaction.get("redaction_report")
        if isinstance(report, list):
            for index, item in enumerate(report):
                path = f"$.redaction.redaction_report[{index}]"
                if not isinstance(item, Mapping):
                    errors.append(_package_records_schema_error(path, "expected object"))
                    continue
                for field_name in ("source_path", "package_path", "rule", "action"):
                    if not isinstance(item.get(field_name), str) or not item.get(field_name):
                        errors.append(_package_records_schema_error(f"{path}.{field_name}", "expected non-empty string"))
                count = item.get("count")
                if not isinstance(count, int) or count < 1:
                    errors.append(_package_records_schema_error(f"{path}.count", "expected positive integer"))
        elif "redaction_report" in redaction:
            errors.append(_package_records_schema_error("$.redaction.redaction_report", "expected array"))
        exclusion_report = redaction.get("exclusion_report")
        if isinstance(exclusion_report, list):
            for index, item in enumerate(exclusion_report):
                path = f"$.redaction.exclusion_report[{index}]"
                if not isinstance(item, Mapping):
                    errors.append(_package_records_schema_error(path, "expected object"))
                    continue
                if not isinstance(item.get("source_path"), str) or not item.get("source_path"):
                    errors.append(_package_records_schema_error(f"{path}.source_path", "expected non-empty string"))
                if not isinstance(item.get("reason"), str) or not item.get("reason"):
                    errors.append(_package_records_schema_error(f"{path}.reason", "expected non-empty string"))
        elif "exclusion_report" in redaction:
            errors.append(_package_records_schema_error("$.redaction.exclusion_report", "expected array"))
    elif "redaction" in manifest:
        errors.append(_package_records_schema_error("$.redaction", "expected object"))

    validation_values = _package_records_schema_enum(schema, "$defs", "validation_result")
    validation = manifest.get("validation")
    if isinstance(validation, Mapping):
        for field_name in _package_records_schema_required(schema, "properties", "validation"):
            if field_name not in validation:
                errors.append(_package_records_schema_error(f"$.validation.{field_name}", "required field is missing"))
        if validation.get("scope") != "workflow_evidence":
            errors.append(_package_records_schema_error("$.validation.scope", 'expected "workflow_evidence"'))
        result = validation.get("result")
        if validation_values and result not in validation_values:
            errors.append(
                _package_records_schema_error(
                    "$.validation.result",
                    "expected one of: " + ", ".join(sorted(validation_values)),
                )
            )
        finding_count = validation.get("finding_count")
        if not isinstance(finding_count, int) or finding_count < 0:
            errors.append(_package_records_schema_error("$.validation.finding_count", "expected non-negative integer"))
        findings = validation.get("findings")
        if not isinstance(findings, list):
            errors.append(_package_records_schema_error("$.validation.findings", "expected array"))
        elif isinstance(finding_count, int) and finding_count >= 0 and finding_count != len(findings):
            errors.append(_package_records_schema_error("$.validation.finding_count", "expected to match findings length"))
        for field_name in ("package_generation", "manifest_schema", "package_integrity", "privacy_security"):
            status = validation.get(field_name)
            if isinstance(status, Mapping):
                status_result = status.get("result")
                if validation_values and status_result not in validation_values:
                    errors.append(
                        _package_records_schema_error(
                            f"$.validation.{field_name}.result",
                            "expected one of: " + ", ".join(sorted(validation_values)),
                        )
                    )
            else:
                errors.append(_package_records_schema_error(f"$.validation.{field_name}", "expected object"))
        workflow_evidence = validation.get("workflow_evidence")
        if isinstance(workflow_evidence, Mapping):
            workflow_result = workflow_evidence.get("result")
            if validation_values and workflow_result not in validation_values:
                errors.append(
                    _package_records_schema_error(
                        "$.validation.workflow_evidence.result",
                        "expected one of: " + ", ".join(sorted(validation_values)),
                    )
                )
            workflow_count = workflow_evidence.get("finding_count")
            if not isinstance(workflow_count, int) or workflow_count < 0:
                errors.append(_package_records_schema_error("$.validation.workflow_evidence.finding_count", "expected non-negative integer"))
            if result != workflow_result:
                errors.append(_package_records_schema_error("$.validation.workflow_evidence.result", "expected to match validation result"))
            if finding_count != workflow_count:
                errors.append(_package_records_schema_error("$.validation.workflow_evidence.finding_count", "expected to match validation finding_count"))
        else:
            errors.append(_package_records_schema_error("$.validation.workflow_evidence", "expected object"))
    elif "validation" in manifest:
        errors.append(_package_records_schema_error("$.validation", "expected object"))

    identity = manifest.get("identity")
    if isinstance(identity, Mapping):
        expected_hash_policy = _package_records_schema_const(schema, "properties", "identity", "properties", "hash_policy")
        if expected_hash_policy is not None and identity.get("hash_policy") != expected_hash_policy:
            errors.append(_package_records_schema_error("$.identity.hash_policy", f'expected "{expected_hash_policy}"'))
        digest = identity.get("reproducible_evidence_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(_package_records_schema_error("$.identity.reproducible_evidence_sha256", "expected sha256 hex string"))
        for field_name in ("content_file_count", "content_total_bytes"):
            value = identity.get(field_name)
            if not isinstance(value, int) or value < 0:
                errors.append(_package_records_schema_error(f"$.identity.{field_name}", "expected non-negative integer"))
    elif "identity" in manifest:
        errors.append(_package_records_schema_error("$.identity", "expected object"))

    return sorted(errors, key=lambda item: (item["path"], item["message"]))


def _package_records_print_manifest_schema_errors(errors: Sequence[dict[str, str]]) -> None:
    print(f"[ERROR] {AIWF_PACKAGE_RECORDS_MANIFEST_ERROR}: package records manifest schema validation failed", file=sys.stderr)
    for error in errors:
        print(f"- {error['path']}: {error['message']}", file=sys.stderr)


def _package_records_manifest_status_result(validation: Mapping[str, Any], section: str, fallback: str = "pass") -> str:
    value = validation.get(section)
    if isinstance(value, Mapping):
        result = value.get("result")
        if isinstance(result, str):
            return result
    return fallback


def _package_records_print_status(
    manifest: Mapping[str, Any],
    *,
    stream: Any = None,
    package_generation: Optional[str] = None,
    manifest_schema: Optional[str] = None,
    package_integrity: Optional[str] = None,
    privacy_security: Optional[str] = None,
) -> None:
    if stream is None:
        stream = sys.stdout
    validation = manifest.get("validation", {})
    if not isinstance(validation, Mapping):
        validation = {}
    workflow_evidence = validation.get("workflow_evidence", {})
    if not isinstance(workflow_evidence, Mapping):
        workflow_evidence = {}
    workflow_result = workflow_evidence.get("result", validation.get("result", "pass"))
    workflow_count = workflow_evidence.get("finding_count", validation.get("finding_count", 0))
    print(
        f"Package Generation: {_package_records_result_label(package_generation or _package_records_manifest_status_result(validation, 'package_generation'))}",
        file=stream,
    )
    print(
        f"Manifest Schema: {_package_records_result_label(manifest_schema or _package_records_manifest_status_result(validation, 'manifest_schema'))}",
        file=stream,
    )
    print(
        f"Package Integrity: {_package_records_result_label(package_integrity or _package_records_manifest_status_result(validation, 'package_integrity'))}",
        file=stream,
    )
    print(
        f"Privacy/Security: {_package_records_result_label(privacy_security or _package_records_manifest_status_result(validation, 'privacy_security'))}",
        file=stream,
    )
    print(
        f"Workflow Evidence Findings: {_package_records_result_label(workflow_result)}, {workflow_count} findings packaged",
        file=stream,
    )


def _package_records_manifest(
    root: Path,
    *,
    options: argparse.Namespace,
    records_root: Path,
    from_date: Optional[str],
    to_date: Optional[str],
    dates: set[str],
    selected_tasks: list[dict[str, str]],
    excluded_tasks: list[dict[str, str]],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    findings = list(findings)
    include_global_events = not bool(options.task_local_events_only)
    event_summary, event_findings = _package_records_event_summary(
        root,
        selected_tasks,
        include_global_events=include_global_events,
    )
    findings.extend(event_findings)
    include_dataset = not bool(options.no_dataset)
    dataset_metadata, dataset_findings = _package_records_dataset_metadata(
        root,
        selected_tasks,
        include_dataset=include_dataset,
    )
    findings.extend(dataset_findings)
    findings.extend(
        [
            _package_records_finding(
                "info",
                "AIWF-PACKAGE-RECORDS-SLICE-CAPABILITY",
                "Redaction is not implemented in this slice.",
            ),
        ]
    )
    config_path = root / ".aiwf" / "config.yaml"
    config = load_aiwf_config(root)
    filters: dict[str, Any] = {
        "dates": sorted(dates),
        "tasks": list(options.task or []),
        "status": list(options.status or []),
        "workflow_phase": list(options.workflow_phase or []),
        "review_status": list(options.review_status or []),
        "project": list(options.project or []),
        "tags": list(options.tag or []),
    }
    if from_date is not None:
        filters["from_date"] = from_date
    if to_date is not None:
        filters["to_date"] = to_date
    redaction_profile = options.redaction_profile or "safe"
    included_artifacts, excluded_artifacts = _package_records_build_artifact_inventory(
        root,
        selected_tasks,
        redaction_profile=redaction_profile,
    )
    redaction_summary, redaction_findings, prohibited_artifacts = _package_records_redaction_summary(
        root,
        profile=redaction_profile,
        included_artifacts=included_artifacts,
        selected_tasks=selected_tasks,
    )
    excluded_artifacts = stable_sort(
        [*excluded_artifacts, *prohibited_artifacts],
        key=lambda item: (item.get("source_path", ""), item.get("reason", "")),
    )
    findings.extend(redaction_findings)
    identity = _package_records_identity(included_artifacts)

    manifest = {
        "schema_version": AIWF_PACKAGE_RECORDS_MANIFEST_SCHEMA_VERSION,
        "package_type": "aiwf-package-records",
        "package_version": AIWF_PACKAGE_RECORDS_PACKAGE_VERSION,
        "capabilities": {
            "canonical_events": True,
            "dataset": include_dataset,
            "redaction": True,
            "package_identity": True,
            "referential_validation": True,
        },
        "generator": {
            "tool": "aiwf",
            "tool_version": AIWF_TOOL_VERSION,
            "workflow_protocol_version": WORKFLOW_PROTOCOL_VERSION,
        },
        "options": {
            "format": options.format or "zip",
            "include_dataset": include_dataset,
            "include_global_events": include_global_events,
            "include_related": bool(options.include_related),
            "redaction_profile": redaction_profile,
            "strict": bool(options.strict),
        },
        "redaction_profile": redaction_profile,
        "redaction_count": redaction_summary["redaction_count"],
        "excluded_artifact_count": redaction_summary["excluded_artifact_count"],
        "records_root": {
            "source_path": rel(root, records_root),
            "layout_version": config.layout.aiwf_layout_version,
            "config_path": rel(root, config_path) if config_path.exists() else ".aiwf/config.yaml",
        },
        "filters": filters,
        "selected_tasks": selected_tasks,
        "excluded_tasks": excluded_tasks,
        "artifacts": {
            "included": included_artifacts,
            "excluded": excluded_artifacts,
            "prohibited_count": len(prohibited_artifacts),
        },
        "events": event_summary,
        "dataset": dataset_metadata,
        "redaction": redaction_summary,
        "repository": _package_records_repository_metadata(root),
        "identity": identity,
        "validation": _package_records_validation_status(findings),
    }
    return manifest


def _package_records_safe_output_path(
    root: Path,
    raw_output: str,
    selected_tasks: Sequence[dict[str, str]],
    *,
    force: bool = False,
) -> tuple[Optional[Path], Optional[str]]:
    target = Path(raw_output)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if target.exists() and not force:
        return None, f"refusing to overwrite existing output path: {target}"

    records_root = get_record_root(root)
    if _package_records_is_under(target, records_root):
        return None, f"refusing to write package records output inside workflow records: {rel(root, target)}"

    events_root = get_event_log_path(root).parent
    if _package_records_is_under(target, events_root):
        return None, f"refusing to write package records output inside workflow events: {rel(root, target)}"

    for task in selected_tasks:
        source_path = task.get("source_path")
        if not source_path:
            continue
        task_dir = (root / source_path).resolve()
        if _package_records_is_under(target, task_dir):
            return None, f"refusing to write package records output inside selected task directory: {rel(root, target)}"

    return target, None


def _package_records_prepare_output_path(output_path: Path, *, force: bool) -> None:
    if not output_path.exists():
        return
    if not force:
        raise SystemExit(f"ERROR: refusing to overwrite existing output path: {output_path}")
    if output_path.is_dir() and not output_path.is_symlink():
        shutil.rmtree(output_path)
    else:
        output_path.unlink()


def _package_records_parse_filters(options: argparse.Namespace) -> tuple[Optional[str], Optional[str], set[str], Optional[int]]:
    try:
        from_date = _package_records_parse_date(options.from_date, field="from-date") if options.from_date else None
        to_date = _package_records_parse_date(options.to_date, field="to-date") if options.to_date else None
        dates = {_package_records_parse_date(item, field="date") for item in (options.date or [])}
    except DateValidationError as exc:
        _print_date_validation_error(exc)
        return None, None, set(), 2
    return from_date, to_date, dates, None


def _package_records_deferred_option_error(options: argparse.Namespace) -> Optional[str]:
    deferred: dict[str, Any] = {}
    for name, value in deferred.items():
        if value:
            option = "--" + name.replace("_", "-")
            return f"{option} is not implemented in this package records slice"
    return None


def package_records_command(root: Path, options: argparse.Namespace) -> int:
    deferred_error = _package_records_deferred_option_error(options)
    if deferred_error:
        print(f"ERROR: {deferred_error}", file=sys.stderr)
        return 2
    if options.include_dataset and options.no_dataset:
        print("ERROR: --include-dataset and --no-dataset cannot be used together", file=sys.stderr)
        return 2
    if options.redaction_profile and options.redaction_profile not in AIWF_PACKAGE_RECORDS_REDACTION_PROFILES:
        print(
            "ERROR: --redaction-profile must be one of: " + ", ".join(sorted(AIWF_PACKAGE_RECORDS_REDACTION_PROFILES)),
            file=sys.stderr,
        )
        return 2
    if options.include_global_events and options.task_local_events_only:
        print("ERROR: --include-global-events and --task-local-events-only cannot be used together", file=sys.stderr)
        return 2
    if options.include_related:
        print("ERROR: --include-related is not implemented in this package records slice", file=sys.stderr)
        return 2
    if not options.output:
        print("ERROR: --output is required for package records", file=sys.stderr)
        return 2

    from_date, to_date, dates, date_error = _package_records_parse_filters(options)
    if date_error is not None:
        return date_error

    records_root = get_record_root(root)
    selected_tasks, excluded_tasks, findings, selector_error = _package_records_select_tasks(
        root,
        from_date=from_date,
        to_date=to_date,
        dates=dates,
        task_selectors=options.task or [],
        statuses=set(options.status or []),
        workflow_phases=set(options.workflow_phase or []),
        review_statuses=set(options.review_status or []),
        projects=set(options.project or []),
        tags=set(options.tag or []),
    )
    if selector_error:
        print(f"ERROR: {selector_error}", file=sys.stderr)
        return 2
    if options.strict and any(item.get("severity") in {"warn", "error"} for item in findings):
        print("ERROR: --strict rejected package records dry-run findings", file=sys.stderr)
        return 2

    output_path, output_error = _package_records_safe_output_path(root, options.output, selected_tasks, force=bool(options.force))
    if output_error:
        print(f"ERROR: {output_error}", file=sys.stderr)
        return 2
    assert output_path is not None

    manifest = _package_records_manifest(
        root,
        options=options,
        records_root=records_root,
        from_date=from_date,
        to_date=to_date,
        dates=dates,
        selected_tasks=selected_tasks,
        excluded_tasks=excluded_tasks,
        findings=findings,
    )
    manifest_errors = _package_records_validate_manifest_schema(manifest)
    if manifest_errors:
        _package_records_print_status(manifest, stream=sys.stderr, package_generation="fail", manifest_schema="fail")
        _package_records_print_manifest_schema_errors(manifest_errors)
        return 2
    if any(
        item.get("severity") == "error" and item.get("code") == "AIWF-PACKAGE-RECORDS-SECRET-DETECTED"
        for item in manifest["validation"]["findings"]
    ):
        _package_records_print_status(manifest, stream=sys.stderr, package_generation="fail", privacy_security="fail")
        print("ERROR: package records failed closed due to privacy/security validation errors", file=sys.stderr)
        return 2
    if options.strict and any(item.get("severity") in {"warn", "error"} for item in manifest["validation"]["findings"]):
        _package_records_print_status(manifest, stream=sys.stderr, package_generation="fail")
        print("ERROR: --strict rejected workflow evidence findings", file=sys.stderr)
        return 2

    if options.dry_run:
        ensure_dir(output_path.parent)
        output_path.write_text(stable_json_dump(manifest), encoding="utf-8")
        _package_records_print_status(manifest)
        print(f"WROTE  {_package_records_manifest_output_label(root, output_path)}")
        return 0

    package_files = _package_records_package_files(
        root,
        manifest,
        selected_tasks,
        redaction_profile=options.redaction_profile or "safe",
        include_global_events=not bool(options.task_local_events_only),
    )
    try:
        _package_records_prepare_output_path(output_path, force=bool(options.force))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output_format = options.format or "zip"
    if output_format == "directory":
        _package_records_write_directory(output_path, package_files)
    elif output_format == "zip":
        _package_records_write_zip(output_path, package_files)
    else:
        print(f"ERROR: unsupported package records format: {output_format}", file=sys.stderr)
        return 2
    _package_records_print_status(manifest)
    print(f"WROTE  {_package_records_manifest_output_label(root, output_path)}")
    return 0


def list_command(
    root: Path,
    *,
    status: Optional[str],
    review_status: Optional[str],
    workflow_phase: Optional[str],
    date: Optional[str],
) -> int:
    date_filter: Optional[str] = None
    if date is not None:
        try:
            selected_date = parse_aiwf_date_arg(date, field="date")
        except DateValidationError as exc:
            _print_date_validation_error(exc)
            return 2
        date_filter = f"{selected_date[0:4]}-{selected_date[4:6]}-{selected_date[6:8]}"

    payload = export_tasks_json(root, None)
    tasks = payload.get("tasks", [])
    filtered: list[dict[str, Any]] = []
    for task in tasks:
        if status and task.get("status") != status:
            continue
        if review_status and task.get("review_status") != review_status:
            continue
        if workflow_phase and task.get("workflow_phase") != workflow_phase:
            continue
        if date_filter and task.get("date") != date_filter:
            continue
        filtered.append(task)

    print("task_id | status | workflow_phase | review_status | task_name")
    for task in filtered:
        print(
            f"{task.get('task_id', '')} | {task.get('status', '')} | "
            f"{task.get('workflow_phase', '')} | {task.get('review_status', '')} | {task.get('task_name', '')}"
        )
    print(f"\nTotal: {len(filtered)}")
    return 0


def _iter_report_task_dirs(root: Path, raw_target: Optional[str]) -> list[Path]:
    if raw_target:
        target = _resolve_target_path(root, raw_target)
    else:
        target = get_record_root(root)
    if not target.exists():
        return []
    if target.is_file():
        return []
    if is_task_specific_dir(target):
        return [target]
    task_dirs: list[Path] = []
    if is_ai_date_dir(target):
        task_dirs.extend(sorted(p for p in target.iterdir() if p.is_dir() and TASK_DIR_RE.match(p.name)))
        return task_dirs
    roots = [target]
    if raw_target is None:
        config = load_aiwf_config(root)
        if config.layout.legacy_enabled:
            legacy_root = (root / "docs").resolve()
            if legacy_root != target:
                roots.append(legacy_root)
    seen: set[str] = set()
    for candidate_root in roots:
        if not candidate_root.exists():
            continue
        ai_dirs = sorted(p for p in candidate_root.iterdir() if p.is_dir() and AI_DATE_RE.match(p.name))
        for ai_dir in ai_dirs:
            for task_dir in sorted(p for p in ai_dir.iterdir() if p.is_dir() and TASK_DIR_RE.match(p.name)):
                key = str(task_dir.resolve())
                if key in seen:
                    continue
                seen.add(key)
                task_dirs.append(task_dir)
    return task_dirs


def _count_post_finalize_evidence_events(events: Sequence[dict[str, Any]]) -> int:
    finalize_success_index = _latest_event_index(events, "finalize_success")
    if finalize_success_index < 0:
        return 0
    count = 0
    for event in events[finalize_success_index + 1 :]:
        if _event_type(event) in POST_FINALIZE_EVIDENCE_EVENT_TYPES:
            count += 1
    return count


def _diagnostic_ranking(root: Path, task_dirs: Sequence[Path]) -> list[dict[str, Any]]:
    counter: dict[str, int] = {}
    for task_dir in task_dirs:
        diagnostics = _collect_task_diagnostics(
            root,
            task_dir,
            v11_missing_is_fail=True,
            include_finalize_checks=True,
        )
        for diag in diagnostics:
            if diag.severity == "info":
                continue
            counter[diag.code] = counter.get(diag.code, 0) + 1
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"code": code, "count": count} for code, count in ranked]


def build_report_payload(root: Path, raw_target: Optional[str]) -> dict[str, Any]:
    task_dirs = _iter_report_task_dirs(root, raw_target)
    tasks: list[dict[str, Any]] = []
    total_events = 0
    malformed_total = 0
    blocked_events = 0
    post_finalize_total = 0
    event_backed_task_count = 0
    finalized_count = 0
    draft_count = 0
    review_count = 0

    for task_dir in task_dirs:
        metadata_payload = load_task_metadata(task_dir)
        metadata = metadata_payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        status = str(metadata.get("status", "unknown"))
        workflow_phase = str(metadata.get("workflow_phase", "unknown"))
        review_status = str(metadata.get("review_status", "unknown"))

        events, malformed_count = _load_events_with_stats(task_dir)
        normalized_events = [_normalize_event(event) for event in events]
        event_count = len(normalized_events)
        has_event_log = _task_event_log_path(task_dir).exists()
        if event_count > 0:
            event_backed_task_count += 1
        total_events += event_count
        malformed_total += malformed_count

        blocked_events += sum(1 for event in normalized_events if str(event.get("result_status", "")) == "blocked")
        post_finalize_count = _count_post_finalize_evidence_events(events)
        post_finalize_total += post_finalize_count

        latest_event_type = normalized_events[-1]["event_type"] if normalized_events else "none"
        latest_event_status = normalized_events[-1]["result_status"] if normalized_events else "none"
        event_schema_versions = sorted(
            {
                str(event.get("schema_version", "legacy"))
                for event in events
                if isinstance(event, dict)
            }
        )
        if not event_schema_versions and has_event_log:
            event_schema_versions = ["legacy"]

        date_token = task_dir.parent.name.replace("ai_", "", 1) if AI_DATE_RE.match(task_dir.parent.name) else ""
        task_id, task_name = split_task_dir_name(task_dir)
        task_entry = {
            "date": date_token,
            "task_id": task_id or "",
            "task_name": task_name or task_dir.name,
            "path": rel(root, task_dir),
            "status": status,
            "workflow_phase": workflow_phase,
            "review_status": review_status,
            "has_event_log": has_event_log,
            "event_count": event_count,
            "malformed_event_count": malformed_count,
            "post_finalize_event_count": post_finalize_count,
            "latest_event_type": latest_event_type,
            "latest_event_status": latest_event_status,
            "legacy_task": str(metadata.get("schema_version", LEGACY_SCHEMA_VERSION)) == LEGACY_SCHEMA_VERSION,
            "event_schema_versions": event_schema_versions,
        }
        tasks.append(task_entry)

        if status == "done" or workflow_phase == "finalized":
            finalized_count += 1
        if status == "draft":
            draft_count += 1
        if status == "review":
            review_count += 1

    payload = {
        "summary": {
            "task_count": len(task_dirs),
            "event_backed_task_count": event_backed_task_count,
            "finalized_count": finalized_count,
            "draft_count": draft_count,
            "review_count": review_count,
            "total_event_count": total_events,
            "malformed_event_count": malformed_total,
            "blocked_event_count": blocked_events,
            "post_finalize_event_count": post_finalize_total,
        },
        "diagnostic_code_ranking": _diagnostic_ranking(root, task_dirs),
        "tasks": tasks,
    }
    return payload


def _render_report_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    ranking = payload.get("diagnostic_code_ranking", [])
    tasks = payload.get("tasks", [])
    lines = [
        "# AIWF Report",
        "## Summary",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key in [
        "task_count",
        "event_backed_task_count",
        "finalized_count",
        "draft_count",
        "review_count",
        "total_event_count",
        "malformed_event_count",
        "blocked_event_count",
        "post_finalize_event_count",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")

    lines.extend(
        [
            "",
            "## Diagnostic Ranking",
            "| Code | Count |",
            "|---|---:|",
        ]
    )
    if ranking:
        for row in ranking:
            lines.append(f"| {row.get('code', '')} | {row.get('count', 0)} |")
    else:
        lines.append("| (none) | 0 |")

    lines.extend(
        [
            "",
            "## Tasks",
            "| Date | Task | Status | Phase | Review | Events |",
            "|---|---|---|---|---|---:|",
        ]
    )
    for task in tasks:
        task_label = f"{task.get('task_id', '')}_{task.get('task_name', '')}".strip("_")
        lines.append(
            f"| {task.get('date', '')} | {task_label} | {task.get('status', '')} | "
            f"{task.get('workflow_phase', '')} | {task.get('review_status', '')} | {task.get('event_count', 0)} |"
        )
    if not tasks:
        lines.append("| - | - | - | - | - | 0 |")
    return "\n".join(lines) + "\n"


def report_command(root: Path, raw_target: Optional[str], output_format: str) -> int:
    payload = build_report_payload(root, raw_target)
    if output_format == "markdown":
        print(_render_report_markdown(payload), end="")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _print_metadata_block(title: str, metadata: Mapping[str, str]) -> None:
    print(f"{title}:")
    print(f"  Tool: {metadata['tool']}")
    print(f"  Provider: {metadata['provider']}")
    print(f"  Model: {metadata['model_name']}")
    print(f"  Reasoning Effort: {metadata['reasoning_effort']}")
    print(f"  Source: {metadata['source']}")
    print(f"  Confidence: {metadata['confidence']}")


def _print_runtime_options_block(title: str, options: Mapping[str, str]) -> None:
    print(f"{title}:")
    if not options:
        print("  (none)")
        return
    for name in sorted(options):
        print(f"  {name}: {options[name]}")


def metadata_show_command(root: Path) -> int:
    resolved = resolve_ai_agent_metadata_with_sources(root)
    profile_state = _current_profile_state(root)
    _print_effective_metadata_with_sources(
        resolved,
        active_profile=profile_state["name"],
        active_profile_exists=bool(profile_state.get("exists")),
        include_active_profile=True,
        include_resolution=True,
        include_values=False,
    )
    print("Effective Metadata:")
    _print_effective_metadata_with_sources(
        resolved,
        active_profile=profile_state["name"],
        active_profile_exists=bool(profile_state.get("exists")),
        include_active_profile=False,
        include_resolution=False,
        include_source=False,
    )
    warning = _dangling_profile_warning(root)
    if warning:
        print(warning)
    return 0


def metadata_allowed_values_command(root: Path, *, field: Optional[str] = None) -> int:
    del root
    return print_metadata_allowed_values(field)


def metadata_init_command(root: Path) -> int:
    defaults = _metadata_prompt_defaults()
    print("Tip: run `./aiwf metadata allowed-values` to see metadata defaults, allowed values, and descriptions.")
    values = {
        "tool": _prompt_metadata_value("AIWF_AGENT_TOOL", defaults["tool"]),
        "provider": _prompt_metadata_value("AIWF_MODEL_PROVIDER", defaults["provider"]),
        "model_name": _prompt_metadata_value("AIWF_MODEL_NAME", defaults["model_name"]),
        "reasoning_effort": _prompt_metadata_value("AIWF_REASONING_EFFORT", defaults["reasoning_effort"]),
        "source": _prompt_metadata_value("AIWF_METADATA_SOURCE", defaults["source"]),
        "confidence": _prompt_metadata_value("AIWF_METADATA_CONFIDENCE", defaults["confidence"]),
    }
    normalized = _normalize_ai_agent_metadata(values)
    path = _metadata_local_env_path(root)
    ensure_dir(path.parent)
    path.write_text("\n".join(_metadata_to_env_lines(normalized)) + "\n", encoding="utf-8")
    print(f"WROTE  {rel(root, path)}")
    return 0


def metadata_validate_command(root: Path) -> int:
    metadata = resolve_ai_agent_metadata(root)
    errors = _metadata_validation_errors(metadata)
    errors.extend(_runtime_option_validation_errors(resolve_aiwf_runtime_options_with_sources(root)))
    dangling_warning = _dangling_profile_warning(root)
    if dangling_warning:
        errors.append(("AIWF-META-PROFILE-004", dangling_warning))
    if not errors:
        print("[INFO] AIWF-META-OK")
        print("metadata is valid")
        return 0
    for code, message in errors:
        print(f"[ERROR] {code}")
        print(message)
    return 2


def metadata_profile_create_command(root: Path, name: str) -> int:
    profile_name = normalize_name(name)
    if not METADATA_PROFILE_NAME_RE.match(profile_name):
        print("[ERROR] AIWF-META-PROFILE-001")
        print("invalid profile name")
        return 2
    path = _metadata_profile_path(root, profile_name)
    if path.exists():
        print("[ERROR] AIWF-META-PROFILE-002")
        print(f"profile already exists: {profile_name}")
        return 2
    ensure_dir(path.parent)
    resolved = resolve_ai_agent_metadata(root)
    seeded = _seed_profile_metadata_defaults(resolved)
    print("Tip: run `./aiwf metadata allowed-values` to see metadata defaults, allowed values, and descriptions.")
    lines = _metadata_to_env_lines(seeded)
    lines.append("AIWF_EVENT_LOG=1")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"CREATED  {rel(root, path)}")
    return 0


def metadata_profile_list_command(root: Path) -> int:
    profiles_dir = _metadata_profiles_dir(root)
    if not profiles_dir.exists():
        print("(no profiles)")
        return 0
    names = sorted(
        p.stem
        for p in profiles_dir.iterdir()
        if p.is_file() and p.suffix == ".env" and METADATA_PROFILE_NAME_RE.match(p.stem)
    )
    if not names:
        print("(no profiles)")
        return 0
    for name in names:
        print(name)
    return 0


def metadata_profile_use_command(root: Path, name: str) -> int:
    profile_name = normalize_name(name)
    if not METADATA_PROFILE_NAME_RE.match(profile_name):
        print("[ERROR] AIWF-META-PROFILE-001")
        print("invalid profile name")
        return 2
    profile_path = _metadata_profile_path(root, profile_name)
    if not profile_path.exists():
        print("[ERROR] AIWF-META-PROFILE-003")
        print(f"profile does not exist: {profile_name}")
        return 2
    current_path = _metadata_current_profile_path(root)
    ensure_dir(current_path.parent)
    current_path.write_text(profile_name + "\n", encoding="utf-8")
    print(f"USING  {profile_name}")
    if _metadata_local_env_path(root).exists():
        print("[WARN] .aiwf/metadata.local.env exists and may override the active profile.")
        print("Run `./aiwf metadata show` to inspect effective metadata.")
    if any(env_key in os.environ for env_key in AI_AGENT_METADATA_ENV_MAP.values()):
        print("[WARN] shell AIWF_* metadata variables are present and may override the active profile.")
        print("Run `./aiwf metadata show` to inspect effective metadata.")
    return 0


def metadata_profile_current_command(root: Path) -> int:
    profile_state = _current_profile_state(root)
    if profile_state["name"] is None:
        print("unknown")
    else:
        print(profile_state["name"])
    if profile_state.get("dangling"):
        print(
            f"[WARN] AIWF-META-PROFILE-004: profile file not found: {rel(root, profile_state['path'])}",
            file=sys.stderr,
        )
    return 0


def metadata_profile_show_command(root: Path, name: Optional[str] = None) -> int:
    profile_label = "Current Profile" if name is None else "Profile"
    if name is None:
        profile_state = _current_profile_state(root)
        profile_name = profile_state["name"]
        display_name = profile_state["display_name"]
        profile_path = profile_state["path"]
        profile_exists = bool(profile_state["exists"])
        dangling = bool(profile_state["dangling"])
    else:
        profile_name = normalize_name(name)
        display_name = profile_name
        profile_path = _metadata_profile_path(root, profile_name)
        profile_exists = profile_path.exists()
        dangling = not profile_exists
    print(f"{profile_label}: {display_name}")
    if profile_path is None:
        print("Profile File: unknown")
        print("Profile File Exists: no")
        return 0
    print(f"Profile File: {rel(root, profile_path)}")
    print(f"Profile File Exists: {'yes' if profile_exists else 'no'}")
    if not profile_exists:
        print("[WARN] AIWF-META-PROFILE-004")
        print(DIAGNOSTICS["AIWF-META-PROFILE-004"]["message"])
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-META-PROFILE-004"]["suggested_fix"])
        return 0 if dangling else 2
    _print_metadata_block("Profile Metadata", _profile_metadata_values(profile_path))
    _print_runtime_options_block("Runtime Options", _profile_runtime_options(profile_path))
    return 0


def metadata_status_command(root: Path) -> int:
    profile_state = _current_profile_state(root)
    local_path = _metadata_local_env_path(root)
    local_exists = local_path.exists()
    local_metadata = _normalize_ai_agent_metadata(_extract_ai_agent_metadata_fields(_parse_simple_env_file(local_path))) if local_exists else None
    shell_metadata_raw = {env_key: str(os.environ[env_key]) for env_key in AI_AGENT_METADATA_ENV_MAP.values() if env_key in os.environ}
    shell_present = bool(shell_metadata_raw)
    effective = resolve_ai_agent_metadata_with_sources(root)
    runtime_options = resolve_aiwf_runtime_options_with_sources(root)

    print("AIWF Metadata Status")
    print("Active Profile:")
    print(f"  Name: {profile_state['display_name']}")
    if profile_state["path"] is None:
        print("  File: unknown")
    else:
        print(f"  File: {rel(root, profile_state['path'])}")
    print(f"  Exists: {'yes' if profile_state.get('exists') else 'no'}")
    if profile_state.get("dangling"):
        print("[WARN] AIWF-META-PROFILE-004")
        print(DIAGNOSTICS["AIWF-META-PROFILE-004"]["message"])
    if profile_state.get("exists") and profile_state.get("path") is not None:
        _print_metadata_block("Profile Metadata", _profile_metadata_values(profile_state["path"]))
    print("Local Override:")
    print(f"  File: {rel(root, local_path)}")
    print(f"  Exists: {'yes' if local_exists else 'no'}")
    if local_exists and local_metadata is not None:
        _print_metadata_block("Local Metadata", local_metadata)
    print("Shell Override:")
    print(f"  Present: {'yes' if shell_present else 'no'}")
    if shell_present:
        _print_metadata_block(
            "Shell Metadata",
            _normalize_ai_agent_metadata(_extract_ai_agent_metadata_fields(shell_metadata_raw)),
        )
    print("Runtime Options:")
    event_log = runtime_options["AIWF_EVENT_LOG"]
    print(f"  AIWF_EVENT_LOG: {event_log.value}")
    print(f"    from: {_metadata_source_label(event_log)}")
    print("Effective Metadata:")
    _print_effective_metadata_with_sources(
        effective,
        active_profile=profile_state["name"],
        active_profile_exists=bool(profile_state.get("exists")),
        include_active_profile=False,
        include_resolution=False,
        indent="  ",
    )
    print("Resolution:")
    if any(record.source_layer == "shell_env" for record in effective.values()):
        print("  Result: shell env overrides one or more lower metadata layers.")
    elif any(record.source_layer == "local_env" for record in effective.values()):
        print("  Result: active profile is overridden by .aiwf/metadata.local.env.")
    elif any(record.source_layer == "active_profile" for record in effective.values()):
        print("  Result: active profile provides the effective metadata baseline.")
    else:
        print("  Result: no usable profile, local override, or shell override found.")
    return 0


def metadata_report_command(root: Path) -> int:
    task_dirs = _iter_all_task_dirs(root)
    total_events = 0
    known_model = 0
    unknown_model = 0
    source_distribution: dict[str, int] = {}
    confidence_distribution: dict[str, int] = {}
    provider_distribution: dict[str, int] = {}
    tool_distribution: dict[str, int] = {}

    for task_dir in task_dirs:
        events = _load_events(task_dir)
        for event in events:
            if not isinstance(event, dict):
                continue
            total_events += 1
            ai_agent = _extract_event_ai_agent(event)
            model_name = str(ai_agent.get("model_name", "unknown")).strip() or "unknown"
            if model_name == "unknown":
                unknown_model += 1
            else:
                known_model += 1
            source = str(ai_agent.get("source", "unknown")).strip() or "unknown"
            confidence = str(ai_agent.get("confidence", "low")).strip() or "low"
            provider = str(ai_agent.get("provider", "unknown")).strip() or "unknown"
            tool = str(ai_agent.get("tool", "unknown")).strip() or "unknown"
            source_distribution[source] = source_distribution.get(source, 0) + 1
            confidence_distribution[confidence] = confidence_distribution.get(confidence, 0) + 1
            provider_distribution[provider] = provider_distribution.get(provider, 0) + 1
            tool_distribution[tool] = tool_distribution.get(tool, 0) + 1

    coverage = (known_model / total_events) if total_events else 0.0
    payload = {
        "metadata_coverage": {
            "total_events": total_events,
            "known_model": known_model,
            "unknown_model": unknown_model,
            "coverage": round(coverage, 3),
        },
        "source_distribution": source_distribution,
        "confidence_distribution": confidence_distribution,
        "provider_distribution": provider_distribution,
        "tool_distribution": tool_distribution,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def next_id_command(root: Path, date: Optional[str]) -> int:
    if date is None:
        target_date = today()
    else:
        try:
            target_date = parse_aiwf_date_arg(date, field="date")
        except DateValidationError as exc:
            _print_date_validation_error(exc)
            return 2
    ai_day_dir = resolve_ai_day_dir(root, target_date)
    print(next_task_id(ai_day_dir))
    return 0


def sync_index_command(root: Path, raw_target: str) -> int:
    target = _resolve_target_path(root, raw_target)
    if not is_task_specific_dir(target):
        print("[ERROR] AIWF-SYNC-001")
        print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-SYNC-001']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-SYNC-001"]["suggested_fix"])
        return 2
    try:
        result = _sync_index_entry_status(root, target)
    except SyncIndexError as exc:
        print(f"[ERROR] {exc.code}")
        print(f"{rel(root, target)}: {exc}")
        print("Suggested Fix:")
        print(f"Run: ./aiwf sync-index --path {rel(root, target)}")
        return 2
    except ValueError as exc:
        print("[ERROR] INDEX_STATUS_STALE")
        print(f"{rel(root, target)}: {exc}")
        print("Suggested Fix:")
        print(f"Run: ./aiwf sync-index --path {rel(root, target)}")
        return 2
    print(f"[INFO] AIWF-SYNC-OK")
    print(f"{rel(root, result.path)}: {DIAGNOSTICS['AIWF-SYNC-OK']['message']}")
    print(f"Result: {result.action.upper()}")
    return 0


def doctor_command(root: Path, raw_target: str) -> int:
    target = _resolve_target_path(root, raw_target)
    if not is_task_specific_dir(target):
        print("[ERROR] AIWF-DOCTOR-001")
        print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-DOCTOR-001']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-DOCTOR-001"]["suggested_fix"])
        return 2
    diagnostics = _collect_task_diagnostics(
        root,
        target,
        v11_missing_is_fail=True,
        include_finalize_checks=True,
    )
    err, warn = _print_diagnostics(diagnostics)
    blockers = sum(1 for item in diagnostics if item.blocker and item.severity == "error")
    print(f"\nSummary: {len(diagnostics)} findings, {err} ERROR, {warn} WARN, {blockers} finalize blockers")
    exit_code = 2 if err else 0
    _try_append_aiwf_event(root, target, command="doctor", exit_code=exit_code, diagnostics=diagnostics)
    return exit_code


def finalize_command(root: Path, raw_target: str, dry_run: bool = False) -> int:
    target = _resolve_target_path(root, raw_target)
    if not is_task_specific_dir(target):
        print("[ERROR] AIWF-FINALIZE-002")
        print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-FINALIZE-002']['message']}")
        print("Suggested Fix:")
        print(DIAGNOSTICS["AIWF-FINALIZE-002"]["suggested_fix"])
        return 2

    diagnostics = _collect_task_diagnostics(
        root,
        target,
        v11_missing_is_fail=True,
        include_finalize_checks=True,
    )
    err, warn = _print_diagnostics(diagnostics)
    blockers = [item for item in diagnostics if item.blocker and item.severity == "error"]
    if blockers:
        print(f"\nSummary: {len(diagnostics)} findings, {err} ERROR, {warn} WARN, {len(blockers)} finalize blockers")
        _try_append_aiwf_event(
            root,
            target,
            command="finalize_dry_run" if dry_run else "finalize",
            exit_code=2,
            diagnostics=diagnostics,
            extra_result={"blocked": True},
        )
        return 2

    metadata_payload = load_task_metadata(target).get("metadata", {})
    already_finalized = _is_already_finalized(metadata_payload)

    if dry_run:
        print("\nFinalize Preview")
        if already_finalized:
            print("Task already finalized.")
            print("No changes would be applied.")
        else:
            preview = _build_finalize_preview(root, target)
            print("Metadata changes:")
            for line in preview:
                print(f"- {line}")
            print("Result:")
            print("PASS")
        _try_append_aiwf_event(
            root,
            target,
            command="finalize_dry_run",
            exit_code=0,
            diagnostics=diagnostics,
            extra_result={"already_finalized": already_finalized},
        )
        return 0

    if already_finalized:
        print("[INFO] AIWF-FINALIZE-001")
        print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-FINALIZE-001']['message']}")
        _try_append_aiwf_event(
            root,
            target,
            command="finalize",
            exit_code=0,
            diagnostics=diagnostics,
            extra_result={"already_finalized": True},
        )
        return 0

    task_file = _metadata_path(root, target)
    original_task_text = task_file.read_text(encoding="utf-8", errors="replace")
    previous_phase = str(metadata_payload.get("workflow_phase", ""))
    preview = _build_finalize_preview(root, target)
    _finalize_task_metadata(root, target)
    try:
        index_sync = _sync_index_entry_status(root, target)
    except SyncIndexError as exc:
        task_file.write_text(original_task_text, encoding="utf-8")
        print(f"[ERROR] {exc.code}")
        print(f"{rel(root, target)}: {exc}")
        print("Suggested Fix:")
        print(f"Run: ./aiwf sync-index --path {rel(root, target)}")
        refreshed_fail = _collect_task_diagnostics(
            root,
            target,
            v11_missing_is_fail=True,
            include_finalize_checks=False,
        )
        _try_append_aiwf_event(root, target, command="finalize", exit_code=2, diagnostics=refreshed_fail, extra_result={"index_sync_failed": True})
        return 2
    print("[INFO] AIWF-FINALIZE-OK")
    print(f"{rel(root, target)}: {DIAGNOSTICS['AIWF-FINALIZE-OK']['message']}")
    print("Applied Metadata Changes:")
    for line in preview:
        print(f"- {line}")
    if index_sync.action == "updated":
        print("Applied Index Projection:")
        print(f"- {rel(root, index_sync.path)} status synchronized from metadata")
    _append_evidence_event(
        root,
        target,
        {
            "event_type": "phase_transition",
            "event_group": "workflow",
            "from": previous_phase,
            "to": "finalized",
            "implicit": True,
            "reason": "finalize",
            "payload": {
                "from": previous_phase,
                "to": "finalized",
                "implicit": True,
                "reason": "finalize",
            },
            "result": "ok",
        },
    )
    _append_evidence_event(
        root,
        target,
        {
            "event_type": "finalize_success",
            "event_group": "workflow",
            "artifact_manifest": _artifact_manifest(target),
            "payload": {
                "artifact_manifest": _artifact_manifest(target),
            },
            "result": "ok",
        },
    )
    refreshed = _collect_task_diagnostics(
        root,
        target,
        v11_missing_is_fail=True,
        include_finalize_checks=False,
    )
    err2, warn2 = _print_diagnostics(refreshed)
    print(f"\nSummary: {len(refreshed)} findings, {err2} ERROR, {warn2} WARN")
    exit_code = 0 if err2 == 0 else 2
    _try_append_aiwf_event(root, target, command="finalize", exit_code=exit_code, diagnostics=refreshed)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Workflow deterministic governance helper")
    parser.add_argument("--repo-root", default=None, help="repository root; defaults to upward search from cwd")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new-task", help="create a new AI work record task directory")
    p.add_argument("name")
    p.add_argument("--date", default=None)
    p.add_argument("--update-existing", action="store_true")
    p.add_argument("--title", default=None)
    p.add_argument("--priority", choices=sorted(ALLOWED_PRIORITY), default=None)
    p.add_argument("--risk", choices=sorted(ALLOWED_RISK), default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--parent-task", default=None)
    p.add_argument("--related-task", action="append", default=[])
    p.add_argument("--blocked-by", action="append", default=[])
    p.add_argument("--supersedes", action="append", default=[])
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--related-file", action="append", default=[])
    p.add_argument("--allow-non-today-date", action="store_true")
    p.set_defaults(
        func=lambda a, r: create_task(
            r,
            a.name,
            a.date,
            a.update_existing,
            title=a.title,
            priority=a.priority,
            risk=a.risk,
            project=a.project,
            parent_task=a.parent_task,
            related_tasks=a.related_task,
            blocked_by=a.blocked_by,
            supersedes=a.supersedes,
            tags=a.tag,
            related_files=a.related_file,
            allow_non_today_date=a.allow_non_today_date,
        )
    )

    p = sub.add_parser("backfill", help="backfill a historical AI record to v1.1")
    p.add_argument("path")
    p.add_argument("--date", default=None)
    p.add_argument("--update-existing", action="store_true")
    p.add_argument("--no-knowledge-decision", action="store_true")
    p.set_defaults(func=lambda a, r: backfill(r, a.path, a.date, a.update_existing, a.no_knowledge_decision))

    p = sub.add_parser("check", help="check workflow compliance")
    p.add_argument("--path", default=None, help="limit check scope to a specific path")
    p.add_argument("--strict", action="store_true", help="return non-zero on warnings")
    p.add_argument(
        "--finalize-ready",
        action="store_true",
        help="run finalize-level read-only diagnostics for a task path",
    )
    p.set_defaults(func=lambda a, r: check_command(r, a.path, a.strict, a.finalize_ready))

    p = sub.add_parser("relocate", help="relocate AIWF-owned artifacts into .aiwf/")
    relocate_mode = p.add_mutually_exclusive_group(required=True)
    relocate_mode.add_argument("--dry-run", action="store_true", help="show the relocation plan without changing files")
    relocate_mode.add_argument("--apply", action="store_true", help="apply the relocation plan and write a migration report")
    p.add_argument(
        "--legacy-docs",
        action="store_true",
        help="explicitly inspect/migrate legacy AIWF-owned root docs/ paths",
    )
    p.set_defaults(func=lambda a, r: relocate_command(r, a.dry_run, legacy_docs=a.legacy_docs))

    p = sub.add_parser("upgrade", help="upgrade a repo using a newer AIWF source package")
    p.add_argument("--source", required=True, help="path to the newer AIWF repo")
    upgrade_mode = p.add_mutually_exclusive_group(required=True)
    upgrade_mode.add_argument("--check", action="store_true", help="validate upgrade readiness without changing files")
    upgrade_mode.add_argument("--dry-run", action="store_true", help="show the upgrade plan without changing files")
    upgrade_mode.add_argument("--apply", action="store_true", help="apply the upgrade and write a migration report")
    p.add_argument("--no-relocate", action="store_true", help="deprecated compatibility flag; legacy docs migration is disabled by default")
    p.add_argument(
        "--migrate-legacy-docs",
        action="store_true",
        help="explicitly migrate reviewed legacy AIWF-owned root docs/ paths during apply",
    )
    p.set_defaults(
        func=lambda a, r: upgrade_command(
            r,
            a.source,
            a.check,
            a.dry_run,
            a.apply,
            a.no_relocate,
            a.migrate_legacy_docs,
        )
    )

    p = sub.add_parser("guard", help="run pre-edit AIWF guard checks for a task")
    p.add_argument("--pre-edit", action="store_true", help="validate a task before non-trivial repository edits")
    p.add_argument("--path", default=None, help="task-specific path")
    p.set_defaults(func=lambda a, r: guard_command(r, a.pre_edit, a.path))

    p = sub.add_parser("doctor", help="show deterministic diagnostics for a task path")
    p.add_argument("--path", required=True, help="task-specific path")
    p.set_defaults(func=lambda a, r: doctor_command(r, a.path))

    p = sub.add_parser("finalize", help="finalize a task after deterministic checks pass")
    p.add_argument("--path", required=True, help="task-specific path")
    p.add_argument("--dry-run", action="store_true", help="run finalize checks and preview metadata changes without writing files")
    p.set_defaults(func=lambda a, r: finalize_command(r, a.path, a.dry_run))

    p = sub.add_parser("transition", help="transition workflow_phase for a task")
    p.add_argument("--path", required=True, help="task-specific path")
    p.add_argument("--to", required=True, choices=sorted(ALLOWED_WORKFLOW_PHASE), help="target workflow phase (cannot be finalized)")
    p.set_defaults(func=lambda a, r: transition_command(r, a.path, a.to))

    p = sub.add_parser(
        "record",
        help="record workflow evidence; this command does not execute external commands",
    )
    p.add_argument("--path", required=True, help="task-specific path")
    p.add_argument("--kind", required=True, choices=sorted(ALLOWED_RECORD_KIND), help="evidence kind")
    p.add_argument("--result", default=None, help="result value for validation/review records")
    p.add_argument("--command", default=None, help="command string evidence only (not executed)")
    p.add_argument("--reviewer", default=None, help="reviewer name for review records")
    p.add_argument("--summary", default=None, help="summary for review/fix/safety evidence")
    p.set_defaults(
        func=lambda a, r: record_command(
            r,
            a.path,
            kind=a.kind,
            result=a.result,
            command=a.command,
            reviewer=a.reviewer,
            summary=a.summary,
        )
    )

    p = sub.add_parser("sync-index", help="synchronize parent index.md status for a task")
    p.add_argument("--path", required=True, help="task-specific path")
    p.set_defaults(func=lambda a, r: sync_index_command(r, a.path))

    p = sub.add_parser("next-id", help="print next task id for a date")
    p.add_argument("--date", default=None, help="YYYYMMDD date; defaults to today")
    p.set_defaults(func=lambda a, r: next_id_command(r, a.date))

    p = sub.add_parser("list", help="list tasks with optional filters")
    p.add_argument("--status", default=None)
    p.add_argument("--review-status", default=None)
    p.add_argument("--workflow-phase", default=None)
    p.add_argument("--date", default=None, help="YYYYMMDD")
    p.set_defaults(
        func=lambda a, r: list_command(
            r,
            status=a.status,
            review_status=a.review_status,
            workflow_phase=a.workflow_phase,
            date=a.date,
        )
    )

    p = sub.add_parser("knowledge-template", help="create knowledge template")
    p.add_argument("kind", choices=["pattern", "bug", "decision"])
    p.add_argument("name")
    p.add_argument("--update-existing", action="store_true")
    p.set_defaults(func=lambda a, r: create_knowledge(r, a.kind, a.name, a.update_existing))

    p = sub.add_parser("export-json", help="export task metadata as JSON")
    p.add_argument("--path", default=None, help="limit export scope to a specific path")
    p.set_defaults(func=lambda a, r: export_json_command(r, a.path))

    p = sub.add_parser("export-experiment", help="export AIWF event experiment summary as JSON")
    p.add_argument("--path", required=True, help="task-specific path")
    p.set_defaults(func=lambda a, r: export_experiment_command(r, a.path))

    p = sub.add_parser("report", help="summarize AIWF task/event metrics")
    p.add_argument("--path", default=None, help="target records root path, ai date path, or task path")
    p.add_argument("--format", choices=["json", "markdown"], default="json", help="report output format")
    p.set_defaults(func=lambda a, r: report_command(r, a.path, a.format))

    p = sub.add_parser("dataset", help="export AIWF evidence as a structured dataset")
    dataset_sub = p.add_subparsers(dest="dataset_command", required=True)

    p_export = dataset_sub.add_parser("export", help="write dataset export output")
    p_export.add_argument("--output", required=True, help="repo-relative or absolute output path")
    p_export.add_argument("--format", choices=["json"], default="json", help="dataset export format")
    p_export.set_defaults(func=lambda a, r: dataset_export_command(r, a.output, a.format))

    p = sub.add_parser("package", help="create AIWF packages")
    package_sub = p.add_subparsers(dest="package_command", required=True)

    p_records = package_sub.add_parser(
        "records",
        help="package AIWF workflow execution records and related workflow evidence",
        description=(
            "Package AIWF workflow execution records and related workflow evidence "
            "for analysis and engineering handoff. This command does not export the repository."
        ),
    )
    p_records.add_argument("--dry-run", action="store_true", help="write only a dry-run manifest")
    p_records.add_argument("--output", default=None, help="repo-relative or absolute package output path")
    p_records.add_argument("--from-date", default=None, help="include tasks created on or after YYYY-MM-DD")
    p_records.add_argument("--to-date", default=None, help="include tasks created on or before YYYY-MM-DD")
    p_records.add_argument("--date", action="append", default=[], help="include tasks for YYYY-MM-DD; may repeat")
    p_records.add_argument("--task", action="append", default=[], help="exact task path or unambiguous task id; may repeat")
    p_records.add_argument("--status", action="append", default=[], help="task metadata status; may repeat")
    p_records.add_argument("--workflow-phase", action="append", default=[], help="task metadata workflow_phase; may repeat")
    p_records.add_argument("--review-status", action="append", default=[], help="task metadata review_status; may repeat")
    p_records.add_argument("--project", action="append", default=[], help="task metadata project; may repeat")
    p_records.add_argument("--tag", action="append", default=[], help="task metadata tag; may repeat")
    p_records.add_argument("--include-related", action="store_true", help="not implemented in this release")
    p_records.add_argument("--strict", action="store_true", help="fail when warnings are present")
    p_records.add_argument("--format", choices=["zip", "directory"], default="zip", help="package output format; default: zip")
    p_records.add_argument("--include-dataset", action="store_true", help="include dataset export metadata; default behavior")
    p_records.add_argument("--no-dataset", action="store_true", help="omit dataset export metadata")
    p_records.add_argument("--include-global-events", action="store_true", help="include deterministically associated global events")
    p_records.add_argument("--task-local-events-only", action="store_true", help="exclude repository-global event scanning")
    p_records.add_argument("--redaction-profile", choices=sorted(AIWF_PACKAGE_RECORDS_REDACTION_PROFILES), default=None, help="redaction profile; default: safe")
    p_records.add_argument("--force", action="store_true", help="replace an existing output path after safety checks")
    p_records.set_defaults(func=lambda a, r: package_records_command(r, a))

    p = sub.add_parser("metadata", help="manage AIWF research metadata")
    metadata_sub = p.add_subparsers(dest="metadata_command", required=True)

    p_show = metadata_sub.add_parser("show", help="show effective metadata and source layers")
    p_show.set_defaults(func=lambda a, r: metadata_show_command(r))

    p_status = metadata_sub.add_parser("status", help="show full metadata resolution status")
    p_status.set_defaults(func=lambda a, r: metadata_status_command(r))

    p_init = metadata_sub.add_parser("init", help="interactive metadata initialization")
    p_init.set_defaults(func=lambda a, r: metadata_init_command(r))

    p_validate = metadata_sub.add_parser("validate", help="validate metadata values")
    p_validate.set_defaults(func=lambda a, r: metadata_validate_command(r))

    p_allowed = metadata_sub.add_parser("allowed-values", help="show allowed metadata values and defaults")
    p_allowed.add_argument(
        "--field",
        choices=sorted(METADATA_VALUE_REGISTRY.keys()),
        default=None,
        help="show values for a single metadata field",
    )
    p_allowed.set_defaults(func=lambda a, r: metadata_allowed_values_command(r, field=a.field))

    p_report = metadata_sub.add_parser("report", help="report metadata coverage from event logs")
    p_report.set_defaults(func=lambda a, r: metadata_report_command(r))

    p_profile = metadata_sub.add_parser("profile", help="manage metadata profiles")
    profile_sub = p_profile.add_subparsers(dest="profile_command", required=True)

    p_profile_create = profile_sub.add_parser("create", help="create a metadata profile from effective metadata")
    p_profile_create.add_argument("name")
    p_profile_create.set_defaults(func=lambda a, r: metadata_profile_create_command(r, a.name))

    p_profile_list = profile_sub.add_parser("list", help="list metadata profiles")
    p_profile_list.set_defaults(func=lambda a, r: metadata_profile_list_command(r))

    p_profile_use = profile_sub.add_parser("use", help="set current metadata profile")
    p_profile_use.add_argument("name")
    p_profile_use.set_defaults(func=lambda a, r: metadata_profile_use_command(r, a.name))

    p_profile_current = profile_sub.add_parser("current", help="show current metadata profile")
    p_profile_current.set_defaults(func=lambda a, r: metadata_profile_current_command(r))

    p_profile_show = profile_sub.add_parser("show", help="show stored values for the current or specified profile")
    p_profile_show.add_argument("name", nargs="?", default=None)
    p_profile_show.set_defaults(func=lambda a, r: metadata_profile_show_command(r, a.name))

    p = sub.add_parser("agents", help="manage AGENTS.md AIWF thin managed block")
    agents_sub = p.add_subparsers(dest="agents_command", required=True)

    p_print = agents_sub.add_parser("print-block", help="print AIWF managed AGENTS.md block")
    p_print.set_defaults(func=lambda a, r: agents_print_block_command(r))

    p_check = agents_sub.add_parser("check", help="check AIWF managed block in AGENTS.md")
    p_check.add_argument("--path", default="AGENTS.md", help="path to AGENTS.md")
    p_check.set_defaults(func=lambda a, r: agents_check_command(r, a.path))

    p_install = agents_sub.add_parser("install", help="install or update AIWF managed block in AGENTS.md")
    p_install.add_argument("--path", default="AGENTS.md", help="path to AGENTS.md")
    p_install.add_argument("--yes", action="store_true", help="confirm write operation")
    p_install.set_defaults(func=lambda a, r: agents_install_command(r, a.path, a.yes))

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else find_repo_root(Path.cwd())
    if not root.exists():
        raise SystemExit(f"ERROR: repo root does not exist: {root}")
    try:
        return args.func(args, root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
