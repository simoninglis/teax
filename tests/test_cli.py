"""Tests for CLI commands."""

import csv
import io
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from teax.cli import OutputFormat, main, parse_issue_spec, parse_repo


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI test runner."""
    return CliRunner()


def test_parse_repo_valid():
    """Test parsing valid owner/repo format."""
    owner, repo = parse_repo("homelab/myproject")
    assert owner == "homelab"
    assert repo == "myproject"


def test_parse_repo_with_slashes():
    """Test parsing repo with extra slashes in name."""
    owner, repo = parse_repo("homelab/my/nested/project")
    assert owner == "homelab"
    assert repo == "my/nested/project"


def test_parse_repo_invalid():
    """Test parsing invalid repo format."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="owner/repo"):
        parse_repo("invalid-format")


def test_main_version(runner: CliRunner):
    """Test --version flag."""
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "teax" in result.output
    assert "0.1.0" in result.output


def test_main_help(runner: CliRunner):
    """Test --help output."""
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "teax - Gitea CLI companion" in result.output
    assert "deps" in result.output
    assert "issue" in result.output


def test_deps_help(runner: CliRunner):
    """Test deps subcommand help."""
    result = runner.invoke(main, ["deps", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "add" in result.output
    assert "rm" in result.output


def test_issue_help(runner: CliRunner):
    """Test issue subcommand help."""
    result = runner.invoke(main, ["issue", "--help"])
    assert result.exit_code == 0
    assert "edit" in result.output
    assert "labels" in result.output
    assert "bulk" in result.output


def test_issue_bulk_help(runner: CliRunner):
    """Test issue bulk help."""
    result = runner.invoke(main, ["issue", "bulk", "--help"])
    assert result.exit_code == 0
    assert "--add-labels" in result.output
    assert "--rm-labels" in result.output
    assert "--set-labels" in result.output
    assert "--assignees" in result.output
    assert "--milestone" in result.output
    assert "ISSUES" in result.output


def test_issue_bulk_no_changes(runner: CliRunner):
    """Test issue bulk with no changes specified."""
    result = runner.invoke(main, ["issue", "bulk", "17", "--repo", "owner/repo"])
    assert result.exit_code == 0
    assert "No changes specified" in result.output


def test_deps_add_requires_on_or_blocks(runner: CliRunner):
    """Test that deps add requires --on or --blocks."""
    result = runner.invoke(main, ["deps", "add", "25", "--repo", "owner/repo"])
    assert result.exit_code != 0
    assert "Must specify either --on or --blocks" in result.output


def test_deps_add_rejects_both_on_and_blocks(runner: CliRunner):
    """Test that deps add rejects both --on and --blocks."""
    args = [
        "deps",
        "add",
        "25",
        "--repo",
        "owner/repo",
        "--on",
        "17",
        "--blocks",
        "30",
    ]
    result = runner.invoke(main, args)
    assert result.exit_code != 0
    assert "Cannot specify both" in result.output


def test_deps_rm_rejects_both_on_and_blocks(runner: CliRunner):
    """Test that deps rm rejects both --on and --blocks."""
    args = [
        "deps",
        "rm",
        "25",
        "--repo",
        "owner/repo",
        "--on",
        "17",
        "--blocks",
        "30",
    ]
    result = runner.invoke(main, args)
    assert result.exit_code != 0
    assert "Cannot specify both" in result.output


def test_csv_output_escapes_commas_in_deps(capsys):
    """Test that CSV output properly escapes titles with commas."""
    formatter = OutputFormat("csv")
    # Create mock dep with comma in title
    mock_dep = SimpleNamespace(
        number=25,
        title="Fix bug, improve performance",
        state="open",
        repository=SimpleNamespace(full_name="owner/repo"),
    )
    formatter.print_deps([mock_dep], 17, "dependencies")
    captured = capsys.readouterr()

    # Parse the CSV output to verify it's valid
    reader = csv.reader(io.StringIO(captured.out))
    rows = list(reader)
    assert len(rows) == 2  # header + 1 data row
    assert rows[0] == ["number", "title", "state", "repository"]
    assert rows[1] == ["25", "Fix bug, improve performance", "open", "owner/repo"]


def test_csv_output_escapes_quotes_in_labels(capsys):
    """Test that CSV output properly escapes labels with quotes."""
    formatter = OutputFormat("csv")
    # Create mock label with quote in description
    mock_label = SimpleNamespace(
        name="bug",
        color="ff0000",
        description='Issues with "critical" bugs',
    )
    formatter.print_labels([mock_label])
    captured = capsys.readouterr()

    # Parse the CSV output to verify it's valid
    reader = csv.reader(io.StringIO(captured.out))
    rows = list(reader)
    assert len(rows) == 2  # header + 1 data row
    assert rows[0] == ["name", "color", "description"]
    assert rows[1] == ["bug", "ff0000", 'Issues with "critical" bugs']


# --- Issue Spec Parsing Tests ---


def test_parse_issue_spec_single():
    """Test parsing a single issue number."""
    assert parse_issue_spec("17") == [17]


def test_parse_issue_spec_range():
    """Test parsing an issue range."""
    assert parse_issue_spec("17-20") == [17, 18, 19, 20]


def test_parse_issue_spec_comma_list():
    """Test parsing comma-separated issues."""
    assert parse_issue_spec("17,18,19") == [17, 18, 19]


def test_parse_issue_spec_mixed():
    """Test parsing mixed ranges and singles."""
    assert parse_issue_spec("17-19,25,30-32") == [17, 18, 19, 25, 30, 31, 32]


def test_parse_issue_spec_deduplicates():
    """Test that duplicate issues are removed."""
    assert parse_issue_spec("17,17,18,18") == [17, 18]


def test_parse_issue_spec_sorted():
    """Test that results are sorted."""
    assert parse_issue_spec("30,17,25") == [17, 25, 30]


def test_parse_issue_spec_with_spaces():
    """Test that whitespace is handled."""
    assert parse_issue_spec("17, 18, 19") == [17, 18, 19]
    assert parse_issue_spec("17 - 19") == [17, 18, 19]


def test_parse_issue_spec_invalid_number():
    """Test error on invalid number."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="Invalid issue number"):
        parse_issue_spec("abc")


def test_parse_issue_spec_invalid_range():
    """Test error on invalid range."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="Invalid range format"):
        parse_issue_spec("17-18-19")


def test_parse_issue_spec_reversed_range():
    """Test error on reversed range."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="Range start must be <= end"):
        parse_issue_spec("20-17")


def test_parse_issue_spec_empty():
    """Test error on empty spec."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="No valid issue numbers"):
        parse_issue_spec("")
