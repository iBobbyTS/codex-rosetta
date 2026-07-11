"""Static security contracts for repository GitHub Actions workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from codex_rosetta._vendor.yaml import load as load_yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SDK_COMPATIBILITY_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "sdk-compatibility.yml"
)


def _load_sdk_compatibility_workflow() -> dict[str, Any]:
    workflow = load_yaml(SDK_COMPATIBILITY_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return cast(dict[str, Any], workflow)


def _workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # The repository's zero-dependency YAML parser follows YAML 1.1, where the
    # unquoted GitHub Actions key `on` is parsed as boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return cast(dict[str, Any], triggers)


def test_sdk_compatibility_issue_alert_has_narrow_safe_permissions() -> None:
    """The alert job must not rely on the repository's read-only token default."""
    workflow = _load_sdk_compatibility_workflow()
    triggers = _workflow_triggers(workflow)

    # A write-capable token must never be exposed to fork or untrusted PR code.
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert "permissions" not in workflow

    job = workflow["jobs"]["sdk-compatibility"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}


def test_sdk_compatibility_issue_alert_runs_only_after_a_real_test_failure() -> None:
    """The issue command and failure condition stay coupled to the type tests."""
    workflow = _load_sdk_compatibility_workflow()
    steps = workflow["jobs"]["sdk-compatibility"]["steps"]

    test_step = next(step for step in steps if step.get("id") == "tests")
    assert test_step["continue-on-error"] is True
    assert "python -m pytest tests/test_types/" in test_step["run"]
    assert "exit ${PIPESTATUS[0]}" in test_step["run"]

    issue_step = next(
        step for step in steps if step.get("name") == "Create issue on failure"
    )
    assert issue_step["if"] == "steps.tests.outcome == 'failure'"
    assert issue_step["uses"] == "actions/github-script@v9"
    assert "run" not in issue_step

    script = issue_step["with"]["script"]
    assert "github.rest.issues.listForRepo" in script
    assert "github.rest.issues.create" in script
    assert "owner: context.repo.owner" in script
    assert "repo: context.repo.repo" in script
    # The live repository does not define these labels; alert delivery must not
    # depend on a separate mutable repository-label setup step.
    assert "labels:" not in script
