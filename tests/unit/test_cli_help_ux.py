import json
import shlex

import pytest

from test_ai_workflow import ai_workflow, _snapshot_tree
from test_workflow_lock import project, run


def help_text(args, capsys):
    with pytest.raises(SystemExit) as displayed:
        ai_workflow.build_parser().parse_args([*args, "--help"])
    assert displayed.value.code == 0
    return capsys.readouterr().out


def test_help_names_the_launcher_and_groups_commands(capsys):
    help_output = help_text([], capsys)
    assert help_output.startswith("usage: ./aiwf ")
    assert "Start or resume work" in help_output
    assert "Use JSON from scripts" in help_output
    assert "./aiwf new-task fix_login" in help_output
    assert "--version" in help_output


@pytest.mark.parametrize(("operation", "present", "absent"), [
    ("context", "--full-workflow", "--path"),
    ("inspect", "--path", "--preview"),
    ("check", "--preview", "--limit"),
    ("diagnostics", "--path", "--finalize-ready"),
    ("list", "--limit", "--path"),
])
def test_query_operation_help_matches_its_options(operation, present, absent, capsys):
    output = help_text(["query", operation], capsys)
    assert output.startswith(f"usage: ./aiwf query {operation} ")
    assert present in output
    assert absent not in output


def test_hidden_options_keep_their_existing_failure_contracts(project, capsys):
    assert "--update-existing" not in help_text(["new-task"], capsys)
    structured_help = help_text(["mutate", "new-task"], capsys)
    assert "--allow-non-today-date" not in structured_help
    assert "--update-existing" not in structured_help
    assert "--dry-run" not in help_text(["mutate", "finalize"], capsys)
    assert "--dry-run" in help_text(["finalize"], capsys)
    before = _snapshot_tree(project)
    native = run(project, "new-task", "task", "--update-existing")
    assert native.returncode == 2
    assert "AIWF-NEW-TASK-001" in native.stdout
    for args, hint in [
        (["new-task", "task", "--allow-non-today-date"], "uses the current date"),
        (["finalize", "--dry-run", "--path", "task"], "query check --preview"),
    ]:
        rejected = run(project, "mutate", *args)
        assert rejected.returncode == 2
        result = json.loads(rejected.stdout)
        assert result["mutation_state"] == "not_applied"
        assert hint in result["diagnostics"][0]["message"]
    assert _snapshot_tree(project) == before


def test_new_task_prints_a_working_guard_command_and_path_recovery(project):
    created = run(project, "new-task", "help_example")
    assert created.returncode == 0
    command = next(line.split("run: ", 1)[1] for line in created.stdout.splitlines() if line.startswith("Before editing,"))
    launcher, *args = shlex.split(command)
    assert launcher == "./aiwf"
    assert args[:3] == ["guard", "--pre-edit", "--path"]
    before = _snapshot_tree(project)
    success = run(project, *args)
    assert success.returncode == 0
    invalid = run(project, "guard", "--path", args[-1])
    assert invalid.returncode == 1
    assert "./aiwf guard --pre-edit --path" in invalid.stdout
    missing = run(project, "inspect", "--path", "001")
    assert missing.returncode == 2
    assert "./aiwf list" in missing.stdout
    assert _snapshot_tree(project) == before


def test_query_argument_order_and_error_envelope_still_work(project):
    assert run(project, "query", "--limit", "1", "list").stdout == run(project, "query", "list", "--limit", "1").stdout
    invalid = run(project, "query", "check", "--limit", "1")
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["error"]["code"] == "AIWF-QUERY-001"


@pytest.mark.parametrize(("args", "operation"), [
    (["list", "--limit", "abc"], "list"),
    (["--limit", "abc", "list"], "list"),
    (["check", "--finalize-ready", "--preview"], "check"),
    (["--finalize-ready", "--preview", "check"], "check"),
    (["--path", "list", "--status", "inspect", "--limit=bad", "diagnostics"], "diagnostics"),
    (["context", "--unknown-option"], "context"),
])
def test_identifiable_query_syntax_failure_returns_json_and_stderr(project, args, operation):
    before = _snapshot_tree(project)
    failure = run(project, "query", *args)
    assert failure.returncode == 2
    assert "error:" in failure.stderr
    envelope = json.loads(failure.stdout)
    assert (envelope["contract_version"], envelope["operation"], envelope["exit_code"]) == (1, operation, 2)
    assert envelope["execution"] == "error" and envelope["result"] is None
    assert envelope["error"]["code"] == "AIWF-QUERY-001"
    assert f"./aiwf query {operation} --help" in envelope["error"]["message"]
    assert _snapshot_tree(project) == before


@pytest.mark.parametrize("args", [
    ["query", "--limit", "abc", "--path", "check"],
    ["query", "--status=list", "--limit", "abc"],
    ["query", "invalid", "--path", "inspect"],
    ["new-task", "query", "--tag", "list", "--unknown-option"],
])
def test_query_syntax_probe_does_not_treat_option_values_as_operations(project, args):
    failure = run(project, *args)
    assert failure.returncode == 2 and failure.stdout == ""
    assert "error:" in failure.stderr


def test_review_discovery_uses_exact_phase_then_authority(capsys):
    output = help_text(["list"], capsys)
    assert "--workflow-phase review" in output
    assert "./aiwf inspect" in output
    assert "awaiting review" not in output
    assert "--workflow-phase review" in help_text(["query", "list"], capsys)


def test_missing_structured_task_path_returns_recovery_in_json(project):
    before = _snapshot_tree(project)
    read = run(project, "query", "check")
    assert read.returncode == 2
    assert "./aiwf query list" in json.loads(read.stdout)["error"]["message"]
    guard = run(project, "mutate", "guard", "--pre-edit")
    assert guard.returncode == 2 and guard.stderr == ""
    receipt = json.loads(guard.stdout)
    assert receipt["mutation_state"] == "not_applied"
    assert "--path" in receipt["diagnostics"][0]["message"]
    assert _snapshot_tree(project) == before


def test_mutation_record_retains_error_code_and_explains_missing_result(project):
    created = json.loads(run(project, "mutate", "new-task", "help_record").stdout)
    result = run(project, "mutate", "record", "--path", created["target"], "--kind", "validation")
    assert result.returncode == 2
    decision = json.loads(result.stdout)
    assert decision["mutation_state"] == "not_applied"
    diagnostic, = decision["diagnostics"]
    assert diagnostic["code"] == "AIWF-MUTATION-INPUT"
    assert "--result" in diagnostic["message"] and "not_run" in diagnostic["message"]
