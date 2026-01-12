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
    assert "--yes" in result.output or "-y" in result.output
    assert "ISSUES" in result.output


def test_issue_bulk_no_changes(runner: CliRunner):
    """Test issue bulk with no changes specified."""
    result = runner.invoke(main, ["issue", "bulk", "17", "--repo", "owner/repo"])
    assert result.exit_code == 0
    assert "No changes specified" in result.output


def test_issue_bulk_shows_preview(runner: CliRunner):
    """Test that bulk command shows preview of changes."""
    result = runner.invoke(
        main,
        [
            "issue", "bulk", "17-19",
            "--repo", "owner/repo",
            "--add-labels", "bug,feature",
        ],
        input="n\n",  # Respond 'no' to confirmation
    )
    assert result.exit_code == 0
    assert "Bulk edit 3 issues" in result.output
    assert "#17" in result.output
    assert "#18" in result.output
    assert "#19" in result.output
    assert "Add labels: bug,feature" in result.output
    assert "Aborted" in result.output


def test_issue_bulk_confirmation_abort(runner: CliRunner):
    """Test that bulk aborts when confirmation is declined."""
    result = runner.invoke(
        main,
        ["issue", "bulk", "17", "--repo", "owner/repo", "--assignees", "user1"],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "Aborted" in result.output


def test_issue_bulk_preview_shows_all_changes(runner: CliRunner):
    """Test that preview shows all types of changes."""
    result = runner.invoke(
        main,
        [
            "issue", "bulk", "17",
            "--repo", "owner/repo",
            "--set-labels", "bug",
            "--add-labels", "urgent",
            "--rm-labels", "stale",
            "--assignees", "user1,user2",
            "--milestone", "5",
        ],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "Set labels to: bug" in result.output
    assert "Add labels: urgent" in result.output
    assert "Remove labels: stale" in result.output
    assert "Set assignees: user1,user2" in result.output
    assert "Set milestone: 5" in result.output


def test_issue_bulk_preview_clear_milestone(runner: CliRunner):
    """Test that clearing milestone shows correct preview."""
    result = runner.invoke(
        main,
        ["issue", "bulk", "17", "--repo", "owner/repo", "--milestone", "none"],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "Clear milestone" in result.output


def test_issue_bulk_truncates_long_issue_list(runner: CliRunner):
    """Test that long issue lists are truncated in preview."""
    result = runner.invoke(
        main,
        ["issue", "bulk", "1-15", "--repo", "owner/repo", "--add-labels", "test"],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "and 5 more" in result.output


def test_issue_bulk_invalid_milestone_id(runner: CliRunner):
    """Test that invalid milestone ID is rejected with clear error."""
    result = runner.invoke(
        main,
        ["issue", "bulk", "17", "--repo", "owner/repo", "--milestone", "abc", "-y"],
    )
    assert result.exit_code != 0
    assert "Invalid milestone ID" in result.output


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


# --- Epic Command Tests ---


def test_epic_help(runner: CliRunner):
    """Test epic subcommand help."""
    result = runner.invoke(main, ["epic", "--help"])
    assert result.exit_code == 0
    assert "create" in result.output
    assert "Manage epic issues" in result.output


def test_epic_create_help(runner: CliRunner):
    """Test epic create help."""
    result = runner.invoke(main, ["epic", "create", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--title" in result.output
    assert "--child" in result.output
    assert "--color" in result.output
    assert "NAME" in result.output


def test_epic_status_help(runner: CliRunner):
    """Test epic status help."""
    result = runner.invoke(main, ["epic", "status", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "ISSUE" in result.output


# --- Epic Helper Function Tests ---


def test_parse_epic_children():
    """Test parsing child issues from epic body."""
    from teax.cli import _parse_epic_children

    body = """# Epic: Feature
## Child Issues

- [ ] #17
- [x] #18
- [ ] #19 Some title text
"""
    children = _parse_epic_children(body)
    assert children == [17, 18, 19]


def test_parse_epic_children_empty():
    """Test parsing epic body with no children."""
    from teax.cli import _parse_epic_children

    body = """# Epic: Feature
## Child Issues

_No child issues yet._
"""
    children = _parse_epic_children(body)
    assert children == []


def test_parse_epic_children_mixed_format():
    """Test parsing epic body with various checklist formats."""
    from teax.cli import _parse_epic_children

    body = """## Child Issues

- [ ] #100
- [x] #101
- [ ] #102
Some other text #999 not a checklist
- not a checklist #888
"""
    children = _parse_epic_children(body)
    # Only the properly formatted checklist items should be captured
    assert children == [100, 101, 102]


def test_epic_add_help(runner: CliRunner):
    """Test epic add help."""
    result = runner.invoke(main, ["epic", "add", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "EPIC_ISSUE" in result.output
    assert "CHILDREN" in result.output


def test_append_children_to_body_existing_section():
    """Test appending children to body with existing section."""
    from teax.cli import _append_children_to_body

    body = """# Epic: Feature
## Child Issues

- [ ] #17
- [ ] #18

---
_Tracked by label: `epic/feature`_
"""
    result = _append_children_to_body(body, [19, 20])
    assert "- [ ] #17" in result
    assert "- [ ] #18" in result
    assert "- [ ] #19" in result
    assert "- [ ] #20" in result
    assert result.index("#19") > result.index("#18")


def test_append_children_to_body_with_placeholder():
    """Test appending children replaces placeholder text."""
    from teax.cli import _append_children_to_body

    body = """# Epic: Feature
## Child Issues

_No child issues yet. Use `teax epic add` to add issues._

---
_Tracked by label: `epic/feature`_
"""
    result = _append_children_to_body(body, [17])
    assert "- [ ] #17" in result
    assert "_No child issues yet." not in result


def test_append_children_to_body_no_section():
    """Test appending children creates section if missing."""
    from teax.cli import _append_children_to_body

    body = """# Epic: Feature

Some description here.
"""
    result = _append_children_to_body(body, [17, 18])
    assert "## Child Issues" in result
    assert "- [ ] #17" in result
    assert "- [ ] #18" in result
