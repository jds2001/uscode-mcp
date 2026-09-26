"""Repository-level assertions for the offline quality workflow (WO-11 part G)."""

from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def test_quality_workflow_runs_tests_and_lint_from_the_lockfile():
    workflow = WORKFLOW.read_text()
    assert "uv sync --locked --dev" in workflow
    assert "uv run pytest -q" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run ruff format --check ." in workflow  # WO-15 F (R26 b): the formatter is enforced


def test_quality_workflow_targets_main_without_secrets():
    workflow = WORKFLOW.read_text()
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert workflow.count("branches: [main]") == 2
    assert 'python-version: "3.11"' in workflow
    assert "secret" not in workflow.casefold()
    assert "GOVINFO_API_KEY" not in workflow
