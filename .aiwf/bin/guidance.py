#!/usr/bin/env python3
"""Check and display project-owned Evidence-linked Guidance Notes."""

from __future__ import annotations

import argparse
import re
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Invoking the helper directly should also leave the repository byte-for-byte intact.
sys.dont_write_bytecode = True

import ai_workflow
from lib import workflow_lock
from lib.package_core import compute_sha256
from safe_paths import reject_symlink_components

try:
    import yaml
except ImportError:
    yaml = None


GUIDANCE_DIR = Path(ai_workflow.GUIDANCE_NOTES_PATH)
GUIDANCE_QUERY_CONTRACT_VERSION = 1
GUIDANCE_SCOPE_METADATA_VERSION = 1
LEGACY_CORRECTION = "POST_FINALIZATION_CORRECTION.md"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
SHA256 = re.compile(r"[a-f0-9]{64}")
SECTIONS = (
    ("Recommended Checks", "建議檢查"),
    ("Applicability", "適用條件"),
    ("Inapplicable Cases", "不適用／不得據此推斷"),
    ("Evidence and Limitations", "證據與限制"),
    ("Recheck Triggers", "重新檢查觸發條件"),
)


if yaml is not None:
    class GuidanceLoader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.AliasEvent):
                raise ValueError("YAML aliases are unsupported in guidance metadata")
            return super().compose_node(parent, index)

        def construct_mapping(self, node, deep=False):
            mapping = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in mapping:
                    raise ValueError("metadata keys must be unique strings")
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping


@dataclass
class Source:
    task: Path
    artifact: Path
    locator: str
    sha256: str
    corrections: dict[Path, str] | None


@dataclass
class Note:
    id: str
    title: str
    status: str
    scope: list[str]
    sources: list[Source]
    review_ref: str | None
    body: str


def fields(value, expected: str, label: str) -> None:
    if not isinstance(value, dict) or value.keys() != set(expected.split()):
        raise ValueError(f"{label} must contain these fields: {expected}")


def plain_text(value, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or not value.isprintable()
        or value.strip().startswith("<") and value.strip().endswith(">")
    ):
        raise ValueError(f"{label} must be nonempty text without placeholders")
    return value.strip()


def identifier(value, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def relative_path(value, label: str) -> Path:
    raw = plain_text(value, label)
    if "\\" in raw or ":" in raw or any(part in {"", ".", ".."} for part in raw.split("/")):
        raise ValueError(f"{label} must be a canonical relative path: {raw}")
    return Path(raw)


def sha256(value) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("sha256 must be a lowercase 64-digit hexadecimal digest")
    return value


def require_regular_file(root: Path, path: Path) -> Path:
    reject_symlink_components(path, root)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"expected a regular file: {path.relative_to(root).as_posix()}")
    return path


def directory_entries(root: Path, path: Path) -> list[Path]:
    reject_symlink_components(path, root)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return []
    if not stat.S_ISDIR(mode):
        raise ValueError(f"expected a directory: {path.relative_to(root).as_posix()}")
    return sorted(path.iterdir())


def read_front_matter(text: str) -> tuple[dict, str]:
    start, boundary, remainder = text.partition("\n")
    if start != "---" or not boundary:
        raise ValueError("missing YAML front matter")
    closing = re.search(r"^---[ \t]*$", remainder, re.MULTILINE)
    if closing is None:
        raise ValueError("unclosed YAML front matter")
    metadata = yaml.load(remainder[:closing.start()], Loader=GuidanceLoader)
    if not isinstance(metadata, dict):
        raise ValueError("YAML front matter must be a mapping")
    return metadata, remainder[closing.end():].lstrip("\n")


def correction_baseline(value) -> dict[Path, str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("reviewed_corrections must be null or a list of path/sha256 mappings")
    baseline = {}
    for item in value:
        fields(item, "path sha256", "correction")
        path = relative_path(item["path"], "correction path")
        if path != Path(LEGACY_CORRECTION) and (
            path.parent != Path(ai_workflow.CORRECTION_DIRNAME)
            or not ai_workflow.CORRECTION_FILENAME_RE.fullmatch(path.name)
        ):
            raise ValueError(f"unrecognized correction path: {path.as_posix()}")
        if path in baseline:
            raise ValueError(f"duplicate correction path: {path.as_posix()}")
        baseline[path] = sha256(item["sha256"])
    return baseline


def read_source(value, records_root: Path) -> Source:
    fields(value, "task artifact locator sha256 reviewed_corrections", "source")
    task = relative_path(value["task"], "task")
    if (
        task.parent.parent != records_root
        or not ai_workflow.AI_DATE_RE.fullmatch(task.parent.name)
        or not ai_workflow.TASK_DIR_RE.fullmatch(task.name)
    ):
        raise ValueError(f"task must be a full canonical path under {records_root.as_posix()}: {task.as_posix()}")
    return Source(
        task=task,
        artifact=relative_path(value["artifact"], "artifact"),
        locator=plain_text(value["locator"], "locator"),
        sha256=sha256(value["sha256"]),
        corrections=correction_baseline(value["reviewed_corrections"]),
    )


def validate_body(body: str) -> None:
    sections = {}
    heading = None
    fence = None
    for line in body.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            if heading is not None:
                sections[heading] = True
            continue
        match = re.match(r"^ {0,3}##[ \t]+(.+?)\s*#*\s*$", line)
        if match:
            heading = match[1]
            if heading in sections:
                raise ValueError(f"duplicate Markdown section: {heading}")
            sections[heading] = False
        elif heading is not None and line.strip():
            sections[heading] = True
    if fence is not None:
        raise ValueError("unclosed Markdown code fence")
    for aliases in SECTIONS:
        if not any(sections.get(heading) for heading in aliases):
            raise ValueError(f"missing or empty Markdown section: {aliases[0]}")


def read_note(metadata: dict, body: str, records_root: Path) -> Note:
    fields(metadata, "id title status scope sources review_ref", "guidance")
    note_id = identifier(metadata["id"], "id")
    title = plain_text(metadata["title"], "title")
    status = metadata["status"]
    if status not in ("draft", "active", "withdrawn"):
        raise ValueError("status must be draft, active, or withdrawn")
    raw_scope = metadata["scope"]
    if not isinstance(raw_scope, list) or not raw_scope:
        raise ValueError("scope must be a nonempty list of tags")
    scope = [identifier(tag, "scope tag") for tag in raw_scope]
    if len(set(scope)) != len(scope):
        raise ValueError("scope tags must be unique")
    review_ref = metadata["review_ref"]
    if status == "active" or review_ref is not None:
        review_ref = plain_text(review_ref, "review_ref")
    if not isinstance(metadata["sources"], list) or not metadata["sources"]:
        raise ValueError("sources must be a nonempty list")
    sources = [read_source(value, records_root) for value in metadata["sources"]]
    baselines = {}
    for source in sources:
        if baselines.setdefault(source.task, source.corrections) != source.corrections:
            raise ValueError(f"inconsistent correction baselines for {source.task.as_posix()}")
    validate_body(body)
    return Note(note_id, title, status, scope, sources, review_ref, body)


def current_corrections(root: Path, task: Path) -> dict[Path, str]:
    """Adapt AIWF's formal correction reader and the supported historical addendum."""
    task_dir = root / task
    if not require_regular_file(root, task_dir / "task.md").stat().st_size:
        raise ValueError("task.md is empty")
    formal_dir = task_dir / ai_workflow.CORRECTION_DIRNAME
    formal_entries = directory_entries(root, formal_dir)
    legacy_entries = task_local_addenda(root, task_dir, formal_dir)
    if any(path.name != LEGACY_CORRECTION for path in legacy_entries):
        unknown = ", ".join(path.name for path in legacy_entries if path.name != LEGACY_CORRECTION)
        raise ValueError(f"unrecognized task-local correction entries: {unknown}")

    # Check and hash the actual file bytes before the runtime reads formal metadata.
    snapshot = {}
    for path in formal_entries + legacy_entries:
        content = require_regular_file(root, path).read_bytes()
        text = content.decode("utf-8")
        if path.parent == task_dir:
            for heading in ("reason", "semantic_impact", "corrected_statement"):
                section = ai_workflow._extract_markdown_section_block(text, heading)
                if section is None or not section.strip():
                    raise ValueError(f"invalid {LEGACY_CORRECTION}: missing {heading}")
        else:
            try:
                read_front_matter(text)
            except (ValueError, yaml.YAMLError, RecursionError) as error:
                raise ValueError(f"invalid correction metadata in {path.name}: {error}") from error
        snapshot[path.relative_to(task_dir)] = ai_workflow.sha256_bytes(content)

    records, diagnostics = ai_workflow._correction_artifact_records(root, task_dir)
    if diagnostics:
        codes = ", ".join(sorted({diagnostic.code for diagnostic in diagnostics}))
        raise ValueError(f"formal correction artifacts could not be validated ({codes})")
    if (
        {record["path"] for record in records} != set(formal_entries)
        or directory_entries(root, formal_dir) != formal_entries
        or task_local_addenda(root, task_dir, formal_dir) != legacy_entries
    ):
        raise ValueError("formal correction inventory changed while reading")
    if any(compute_sha256(require_regular_file(root, task_dir / path)) != digest for path, digest in snapshot.items()):
        raise ValueError("correction contents changed while reading")
    return snapshot


def task_local_addenda(root: Path, task_dir: Path, formal_dir: Path) -> list[Path]:
    return [
        path for path in directory_entries(root, task_dir)
        if path != formal_dir and re.search(r"correction|errata|addendum", path.name, re.IGNORECASE)
    ]


def correction_issues(task: Path, baseline: dict[Path, str] | None, current: dict[Path, str] | str) -> list[str]:
    if isinstance(current, str):
        return [f"{task.as_posix()}: current corrections unknown ({current})"]
    if baseline is None:
        return [f"{task.as_posix()}: reviewed correction baseline unknown"]
    reasons = []
    for label, paths in (
        ("added", current.keys() - baseline.keys()),
        ("removed", baseline.keys() - current.keys()),
        ("changed", {path for path in current.keys() & baseline.keys() if current[path] != baseline[path]}),
    ):
        if paths:
            names = ", ".join(path.as_posix() for path in sorted(paths))
            reasons.append(f"{task.as_posix()}: corrections {label} ({names})")
    return reasons


def check_sources(root: Path, note: Note, snapshots: dict) -> list[str]:
    issues = []
    seen_tasks = set()
    for source in note.sources:
        artifact = source.task / source.artifact
        try:
            digest = compute_sha256(require_regular_file(root, root / artifact))
            if digest != source.sha256:
                issues.append(f"{artifact.as_posix()}: source SHA-256 changed")
        except (OSError, ValueError) as error:
            issues.append(f"{artifact.as_posix()}: source unavailable ({error})")
        if source.task not in seen_tasks:
            seen_tasks.add(source.task)
            if source.task not in snapshots:
                try:
                    snapshots[source.task] = current_corrections(root, source.task)
                except (OSError, ValueError) as error:
                    snapshots[source.task] = str(error)
            issues.extend(correction_issues(source.task, source.corrections, snapshots[source.task]))
    return issues


def show_note(note: Note) -> None:
    print(f"Scope: {', '.join(note.scope)}")
    print(f"Declared review reference: {note.review_ref or 'none'}")
    print("Sources:")
    for source in note.sources:
        print(f"  {source.task.as_posix()}/{source.artifact.as_posix()} | {source.locator}")
        print(f"    SHA-256: {source.sha256}")
        if source.corrections:
            for path, digest in sorted(source.corrections.items()):
                print(f"    Reviewed correction: {path.as_posix()} | {digest}")
        else:
            print(f"    Reviewed corrections: {'unknown' if source.corrections is None else 'none'}")
    print("\n" + note.body.rstrip())


def evaluate(root: Path, args: argparse.Namespace) -> tuple[list, list[str]]:
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    config = root / ".aiwf/config.yaml"
    reject_symlink_components(config, root)
    if config.exists():
        require_regular_file(root, config)
    layout = (ai_workflow._query_layout(root) if getattr(args, "format", None) == "json"
              else ai_workflow.load_aiwf_config(root).layout)
    records_root = relative_path(layout.record_root, "records root")
    entries = directory_entries(root, root / GUIDANCE_DIR)
    notes = []
    ids = Counter()
    errors = []
    for path in entries:
        if path.suffix != ".md":
            continue
        try:
            metadata, body = read_front_matter(require_regular_file(root, path).read_text(encoding="utf-8"))
            note_id = identifier(metadata.get("id"), "id")
            ids[note_id] += 1
            notes.append(read_note(metadata, body, records_root))
        except (OSError, ValueError, yaml.YAMLError, RecursionError) as error:
            errors.append(f"INVALID {path.relative_to(root).as_posix()}: {error}")

    for note_id, count in sorted(ids.items()):
        if count > 1:
            errors.append(f"INVALID {note_id}: duplicate guidance id")

    matched = []
    snapshots = {}
    for note in sorted(notes, key=lambda item: item.id):
        if ids[note.id] > 1 or (args.id and note.id != args.id) or (args.scope and args.scope not in note.scope):
            continue
        if args.command == "show" and not args.id and note.status != "active":
            continue
        matched.append((note, check_sources(root, note, snapshots)))
    return matched, errors


def structured_note(note: Note, issues: list[str], *, explicit_id: bool, metadata_only: bool, root: Path) -> dict:
    eligible = note.status == "active" and not issues
    visible = eligible or explicit_id
    sources = []
    if visible:
        for source in note.sources:
            corrections = None
            if source.corrections is not None:
                corrections = [
                    {"path": path.as_posix(), "sha256": digest}
                    for path, digest in sorted(source.corrections.items())
                ]
            sources.append({
                "task": source.task.as_posix(), "artifact": source.artifact.as_posix(),
                "locator": source.locator, "sha256": source.sha256, "reviewed_corrections": corrections,
            })
    return {
        "id": note.id, "title": note.title, "status": note.status,
        "source_state": "review_needed" if issues else "current", "eligible": eligible,
        "issues": [message.replace(str(root) + "/", "") for message in issues],
        "scope": note.scope if visible else [], "review_ref": note.review_ref if visible else None,
        "sources": sources, "body": note.body if visible and not metadata_only else None,
    }


def run(root: Path, args: argparse.Namespace) -> int:
    structured = getattr(args, "format", None) == "json"
    if structured and not (args.id or args.scope):
        return ai_workflow.emit_query_result("guidance", 2, None, code="AIWF-GUIDANCE-SELECTOR", message="Supply one scope or ID.")
    matched, errors = evaluate(root, args)
    rc = int(any(issues for _, issues in matched))
    if structured:
        if errors or (args.id and not matched):
            return ai_workflow.emit_query_result("guidance", 2, None, code="AIWF-GUIDANCE-QUERY",
                                                 message="Invalid guidance collection or unknown note ID.")
        result = {"selector": {"id": args.id} if args.id else {"scope": args.scope},
                  "notes": [structured_note(note, issues, explicit_id=bool(args.id),
                                            metadata_only=args.metadata_only, root=root)
                            for note, issues in matched]}
        return ai_workflow.emit_query_result("guidance", rc, result)

    print(f"Source root: {root}")
    print(f"Guidance directory: {GUIDANCE_DIR.as_posix()}")
    for message in errors:
        print(message)
    for note, issues in matched:
        summary = "REVIEW NEEDED" if issues else "sources match"
        print(f"\n{note.id} | {note.title} | {note.status} | {summary}")
        for issue in issues:
            print(f"  - {issue}")
        if args.command == "show" and (args.id or not issues):
            if issues or note.status != "active":
                print("Explicit view for review. Excluded from current references.")
            else:
                print("Current reference. Check applicability and authorization for this task.")
            show_note(note)

    if not matched:
        if args.id:
            print(f"No usable guidance entry found for ID {args.id}.")
            return 2
        print("No matching guidance entries.")
    return 2 if errors else rc


def nonblank_selector(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("selector must not be empty or whitespace")
    return value


class _StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def main(argv: list[str] | None = None) -> int:
    tokens = sys.argv[1:] if argv is None else argv
    json_requested = "--format=json" in tokens or any(
        first == "--format" and second == "json" for first, second in zip(tokens, tokens[1:])
    )
    parser_type = _StructuredArgumentParser if json_requested else argparse.ArgumentParser
    parser = parser_type(description=__doc__)
    parser.add_argument("--repo-root", type=Path, help="local project root, defaults to AIWF root discovery")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("check", "check structure, source hashes, and correction snapshots"),
        ("show", "show current references or explicitly inspect an entry by ID"),
    ):
        command = commands.add_parser(name, help=help_text)
        if name == "show":
            command.add_argument("--format", choices=["text", "json"], default="text")
            command.add_argument("--metadata-only", action="store_true",
                                 help="omit note bodies from a structured scope lookup")
        selector = command.add_mutually_exclusive_group()
        selector.add_argument("--id", type=nonblank_selector, help="exact guidance ID")
        selector.add_argument("--scope", type=nonblank_selector, help="exact scope tag")
    try:
        args = parser.parse_args(tokens)
        if getattr(args, "metadata_only", False) and (args.format != "json" or not args.scope):
            parser.error("--metadata-only requires --format json and --scope")
    except ValueError:
        return ai_workflow.emit_query_result("guidance", 2, None, code="AIWF-GUIDANCE-SELECTOR",
                                             message="Invalid structured guidance arguments.")
    structured = getattr(args, "format", None) == "json"
    if yaml is None:
        if structured:
            return ai_workflow.emit_query_result("guidance", 2, None, code="AIWF-GUIDANCE-UNAVAILABLE",
                                                 message="Guidance requires PyYAML.")
        print("ERROR: Guidance requires PyYAML. Install it in the Python environment used for this helper.", file=sys.stderr)
        return 2
    try:
        root = args.repo_root.resolve(strict=True) if args.repo_root else ai_workflow.find_repo_root(Path.cwd())
        with workflow_lock.workflow_lock(root, writer=False, operation="guidance",
                                         allow_unlocked_observation=not structured):
            return run(root, args)
    except workflow_lock.WorkflowLockError as error:
        if structured:
            return ai_workflow.emit_query_result("guidance", 2, None, code=error.code, message=error.message)
        print(f"ERROR: {error.code}: {error.message}", file=sys.stderr)
        return 2
    except (OSError, ValueError, SystemExit) as error:
        if structured:
            return ai_workflow.emit_query_result("guidance", 2, None, code="AIWF-GUIDANCE-QUERY",
                                                 message="Could not read the bound guidance collection.")
        if isinstance(error, SystemExit):
            print(error, file=sys.stderr)
            return 2
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
