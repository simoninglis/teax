"""Tests for CLI commands."""

import csv
import io
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from teax.cli import (
    OutputFormat,
    csv_safe,
    main,
    parse_issue_spec,
    parse_repo,
    safe_rich,
    terminal_safe,
)

# --- Security Tests ---


def test_terminal_safe_strips_csi_sequences():
    """Test terminal_safe strips CSI (ANSI) escape sequences."""
    # ANSI color codes should be removed
    assert terminal_safe("\x1b[31mRed Text\x1b[0m") == "Red Text"
    # ANSI cursor movement should be removed
    assert terminal_safe("\x1b[2J\x1b[HEvil") == "Evil"


def test_terminal_safe_strips_osc_sequences():
    """Test terminal_safe strips OSC escape sequences (e.g., hyperlinks)."""
    # OSC-8 hyperlink (terminated by BEL)
    osc_link = "\x1b]8;;https://phish.example.com\x07click\x1b]8;;\x07"
    assert terminal_safe(osc_link) == "click"
    # OSC terminated by ST (\x1b\\)
    osc_st = "\x1b]0;Evil Title\x1b\\"
    assert terminal_safe(osc_st) == ""


def test_terminal_safe_strips_dcs_sequences():
    """Test terminal_safe strips DCS escape sequences."""
    dcs = "\x1bPq#0;2;0;0;0#1;2;255;255;255\x1b\\"
    assert terminal_safe(dcs) == ""


def test_terminal_safe_strips_c1_control_codes():
    """Test terminal_safe strips C1 control codes (0x80-0x9F)."""
    # C1 CSI (0x9B) is equivalent to ESC [
    assert terminal_safe("Hello\x9bWorld") == "HelloWorld"
    # C1 OSC (0x9D) is equivalent to ESC ]
    assert terminal_safe("Test\x9dEvil\x9c") == "TestEvil"


def test_terminal_safe_strips_standalone_cr():
    """Test terminal_safe strips standalone CR (line-rewrite spoofing)."""
    # Standalone CR allows overwriting output - must be stripped
    assert terminal_safe("Real text\rFake") == "Real textFake"
    # CRLF is valid Windows line ending - CR is preserved (not spoofing risk)
    assert terminal_safe("Line1\r\nLine2") == "Line1\r\nLine2"


def test_terminal_safe_strips_control_characters():
    """Test terminal_safe strips C0 control characters."""
    # Null bytes
    assert terminal_safe("Hello\x00World") == "HelloWorld"
    # Bell character
    assert terminal_safe("Alert\x07!") == "Alert!"
    # Backspace
    assert terminal_safe("Back\x08space") == "Backspace"


def test_terminal_safe_preserves_normal_text():
    """Test terminal_safe preserves normal text."""
    assert terminal_safe("Normal text with spaces") == "Normal text with spaces"
    assert terminal_safe("Unicode: café résumé") == "Unicode: café résumé"
    # Tabs and newlines should be preserved
    assert terminal_safe("Line1\nLine2\tTabbed") == "Line1\nLine2\tTabbed"


def test_safe_rich_strips_escapes_and_markup():
    """Test safe_rich combines terminal_safe with Rich markup escaping."""
    # Should strip escape sequences
    assert safe_rich("\x1b[31mRed\x1b[0m") == "Red"
    # Should escape Rich markup
    result = safe_rich("[bold]Not bold[/bold]")
    assert "bold" in result
    # Combined: strip escapes then escape markup
    result = safe_rich("\x1b[31m[red]Fake[/red]\x1b[0m")
    assert "red" in result
    assert "\x1b" not in result


def test_csv_safe_neutralizes_formula_prefix():
    """Test csv_safe neutralizes Excel/Sheets formula prefixes."""
    assert csv_safe("=SUM(A1:A10)") == "'=SUM(A1:A10)"
    assert csv_safe("+1234567890") == "'+1234567890"
    assert csv_safe("-1234567890") == "'-1234567890"
    assert csv_safe("@SUM(A1)") == "'@SUM(A1)"


def test_csv_safe_neutralizes_formula_after_whitespace():
    """Test csv_safe neutralizes formulas even after leading whitespace."""
    assert csv_safe("  =SUM(A1)") == "'  =SUM(A1)"
    assert csv_safe(" +123") == "' +123"
    assert csv_safe("\t-456") == "'\t-456"


def test_csv_safe_strips_terminal_escapes():
    """Test csv_safe strips terminal escape sequences."""
    assert csv_safe("\x1b[31mRed\x1b[0m") == "Red"
    assert csv_safe("\x1b]8;;https://evil.com\x07click\x1b]8;;\x07") == "click"


def test_csv_safe_preserves_normal_text():
    """Test csv_safe preserves normal text without prefix."""
    assert csv_safe("Normal text") == "Normal text"
    assert csv_safe("123-456-7890") == "123-456-7890"
    assert csv_safe("email@example.com") == "email@example.com"


def test_csv_safe_handles_empty_string():
    """Test csv_safe handles empty string."""
    assert csv_safe("") == ""


# --- Fixture ---


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI test runner."""
    return CliRunner()


def test_parse_repo_valid():
    """Test parsing valid owner/repo format."""
    owner, repo = parse_repo("homelab/myproject")
    assert owner == "homelab"
    assert repo == "myproject"


def test_parse_repo_with_extra_slashes():
    """Test parsing repo with extra slashes is rejected."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="owner/repo"):
        parse_repo("homelab/my/nested/project")


def test_parse_repo_invalid():
    """Test parsing invalid repo format."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="owner/repo"):
        parse_repo("invalid-format")


def test_parse_repo_empty_repo():
    """Test parsing repo with empty repo name."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="owner/repo"):
        parse_repo("owner/")


def test_parse_repo_empty_owner():
    """Test parsing repo with empty owner."""
    from click import BadParameter

    with pytest.raises(BadParameter, match="owner/repo"):
        parse_repo("/repo")


def test_main_version(runner: CliRunner):
    """Test --version flag outputs valid SemVer."""
    import re

    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert re.search(r"teax, version \d+\.\d+\.\d+", result.output)


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
            "issue",
            "bulk",
            "17-19",
            "--repo",
            "owner/repo",
            "--add-labels",
            "bug,feature",
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
            "issue",
            "bulk",
            "17",
            "--repo",
            "owner/repo",
            "--set-labels",
            "bug",
            "--add-labels",
            "urgent",
            "--rm-labels",
            "stale",
            "--assignees",
            "user1,user2",
            "--milestone",
            "5",
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


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_invalid_milestone_name(runner: CliRunner):
    """Test that invalid milestone name is rejected with clear error."""
    import httpx
    import respx

    with respx.mock:
        # Mock empty milestones list (name not found)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
            return_value=httpx.Response(200, json=[])
        )

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "-r", "owner/repo", "--milestone", "abc", "-y"],
        )
        assert result.exit_code != 0
        assert "Milestone 'abc' not found" in result.output


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


# --- parse_show_spec Tests ---


def test_parse_show_spec_basic():
    """Test basic parsing of --show specification."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("C:ci.yml,B:build.yml")
    assert result == [("C", "ci.yml"), ("B", "build.yml")]


def test_parse_show_spec_single_workflow():
    """Test parsing single workflow."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("C:ci.yml")
    assert result == [("C", "ci.yml")]


def test_parse_show_spec_lowercase_abbreviation():
    """Test that lowercase abbreviations are uppercased."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("c:ci.yml,b:build.yml")
    assert result == [("C", "ci.yml"), ("B", "build.yml")]


def test_parse_show_spec_numeric_abbreviation():
    """Test numeric abbreviation."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("1:ci.yml,2:build.yml")
    assert result == [("1", "ci.yml"), ("2", "build.yml")]


def test_parse_show_spec_yaml_extension():
    """Test .yaml extension is accepted."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("C:ci.yaml")
    assert result == [("C", "ci.yaml")]


def test_parse_show_spec_with_spaces():
    """Test whitespace is handled."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("C: ci.yml , B: build.yml")
    assert result == [("C", "ci.yml"), ("B", "build.yml")]


def test_parse_show_spec_colon_in_workflow():
    """Test colon in workflow name (split on first colon only)."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("C:path:to:workflow.yml")
    assert result == [("C", "path:to:workflow.yml")]


def test_parse_show_spec_preserves_order():
    """Test that order is preserved."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("D:deploy.yml,C:ci.yml,B:build.yml")
    assert result == [("D", "deploy.yml"), ("C", "ci.yml"), ("B", "build.yml")]


def test_parse_show_spec_empty():
    """Test error on empty spec."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="Empty --show specification"):
        parse_show_spec("")


def test_parse_show_spec_trailing_comma():
    """Test trailing comma is handled."""
    from teax.cli import parse_show_spec

    result = parse_show_spec("C:ci.yml,")
    assert result == [("C", "ci.yml")]


def test_parse_show_spec_multi_char_abbreviation():
    """Test error on multi-character abbreviation."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="single ASCII alphanumeric"):
        parse_show_spec("CI:ci.yml")


def test_parse_show_spec_missing_colon():
    """Test error on missing colon."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="expected 'A:workflow.yml'"):
        parse_show_spec("ci.yml")


def test_parse_show_spec_wrong_extension():
    """Test error on wrong file extension."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="must end in .yml or .yaml"):
        parse_show_spec("C:ci.txt")


def test_parse_show_spec_duplicate_abbreviation():
    """Test error on duplicate abbreviation."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="Duplicate abbreviation"):
        parse_show_spec("C:ci.yml,C:build.yml")


def test_parse_show_spec_duplicate_workflow():
    """Test error on duplicate workflow."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="Duplicate workflow"):
        parse_show_spec("C:ci.yml,B:ci.yml")


def test_parse_show_spec_special_char_abbreviation():
    """Test error on non-alphanumeric abbreviation."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="single ASCII alphanumeric"):
        parse_show_spec("!:ci.yml")


def test_parse_show_spec_unicode_abbreviation():
    """Test error on Unicode abbreviation (would expand on uppercase)."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    # ß uppercases to "SS" which would break single-char invariant
    with pytest.raises(BadParameter, match="single ASCII alphanumeric"):
        parse_show_spec("ß:ci.yml")


def test_parse_show_spec_case_insensitive_duplicate():
    """Test error on case-insensitive duplicate abbreviation."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    # c and C should be treated as duplicates
    with pytest.raises(BadParameter, match="Duplicate abbreviation"):
        parse_show_spec("c:ci.yml,C:build.yml")


def test_parse_show_spec_whitespace_only():
    """Test error on whitespace-only spec."""
    from click import BadParameter

    from teax.cli import parse_show_spec

    with pytest.raises(BadParameter, match="Empty --show specification"):
        parse_show_spec("   ")


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


# --- OutputFormat Tests ---


def test_output_format_simple_deps(capsys):
    """Test simple output format for dependencies."""
    formatter = OutputFormat("simple")
    mock_dep1 = SimpleNamespace(
        number=17,
        title="First dep",
        state="open",
        repository=SimpleNamespace(full_name="owner/repo"),
    )
    mock_dep2 = SimpleNamespace(
        number=18,
        title="Second dep",
        state="closed",
        repository=SimpleNamespace(full_name="owner/repo"),
    )
    formatter.print_deps([mock_dep1, mock_dep2], 25, "depends on")
    captured = capsys.readouterr()
    assert "#17" in captured.out
    assert "#18" in captured.out


def test_output_format_table_deps_empty(capsys, monkeypatch):
    """Test table output format for empty dependencies."""
    # Capture Rich console output
    from io import StringIO

    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    formatter = OutputFormat("table")
    formatter.print_deps([], 25, "depends on")
    output = buffer.getvalue()
    assert "no depends on" in output.lower()


def test_output_format_table_deps_with_data(capsys, monkeypatch):
    """Test table output format for dependencies with data."""
    from io import StringIO

    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    formatter = OutputFormat("table")
    mock_dep = SimpleNamespace(
        number=17,
        title="Test dep",
        state="open",
        repository=SimpleNamespace(full_name="owner/repo"),
    )
    formatter.print_deps([mock_dep], 25, "depends on")
    output = buffer.getvalue()
    assert "17" in output
    assert "Test dep" in output


def test_output_format_simple_labels(capsys):
    """Test simple output format for labels."""
    formatter = OutputFormat("simple")
    mock_label = SimpleNamespace(name="bug", color="ff0000", description="Bug report")
    formatter.print_labels([mock_label])
    captured = capsys.readouterr()
    assert "bug" in captured.out


def test_output_format_table_labels_empty(capsys, monkeypatch):
    """Test table output format for empty labels."""
    from io import StringIO

    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    formatter = OutputFormat("table")
    formatter.print_labels([])
    output = buffer.getvalue()
    assert "no labels" in output.lower()


def test_output_format_table_labels_with_data(capsys, monkeypatch):
    """Test table output format for labels with data."""
    from io import StringIO

    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    formatter = OutputFormat("table")
    mock_label = SimpleNamespace(name="bug", color="ff0000", description="Bug report")
    formatter.print_labels([mock_label])
    output = buffer.getvalue()
    assert "bug" in output
    assert "ff0000" in output


# --- CLI Command Integration Tests with Mocked API ---


@pytest.fixture
def mock_login():
    """Create a mock tea login for CLI tests."""
    from teax.models import TeaLogin

    return TeaLogin(
        name="test.example.com",
        url="https://test.example.com",
        token="test-token-123",
        default=True,
        user="testuser",
    )


@pytest.fixture
def mock_client(mock_login, monkeypatch):
    """Patch GiteaClient to use mock login and avoid config loading."""

    from teax.api import GiteaClient

    original_init = GiteaClient.__init__

    def patched_init(self, login=None, login_name=None):
        original_init(self, login=mock_login, login_name=None)

    monkeypatch.setattr(GiteaClient, "__init__", patched_init)
    return mock_login


# --- deps list tests ---


@pytest.mark.usefixtures("mock_client")
def test_deps_list_command(runner: CliRunner):
    """Test deps list command execution."""
    import httpx
    import respx

    with respx.mock:
        # Mock dependencies endpoint
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 17,
                        "number": 17,
                        "title": "Dependency Issue",
                        "state": "open",
                        "repository": {
                            "id": 1,
                            "name": "repo",
                            "full_name": "owner/repo",
                            "owner": "owner",
                        },
                    },
                ],
            )
        )
        # Mock blocks endpoint
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/blocks"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(main, ["deps", "list", "25", "--repo", "owner/repo"])

        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_deps_list_with_blocks(runner: CliRunner):
    """Test deps list command with blocking issues."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/blocks"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 30,
                        "number": 30,
                        "title": "Blocked Issue",
                        "state": "open",
                        "repository": {
                            "id": 1,
                            "name": "repo",
                            "full_name": "owner/repo",
                            "owner": "owner",
                        },
                    },
                ],
            )
        )

        result = runner.invoke(main, ["deps", "list", "25", "--repo", "owner/repo"])

        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_deps_list_error_handling(runner: CliRunner):
    """Test deps list error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/999/dependencies"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(main, ["deps", "list", "999", "--repo", "owner/repo"])

        assert result.exit_code == 1
        assert "Error" in result.output


# --- deps add tests ---


@pytest.mark.usefixtures("mock_client")
def test_deps_add_depends_on(runner: CliRunner):
    """Test deps add with --on flag."""
    import httpx
    import respx

    with respx.mock:
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
        ).mock(return_value=httpx.Response(201))

        result = runner.invoke(
            main, ["deps", "add", "25", "--repo", "owner/repo", "--on", "17"]
        )

        assert result.exit_code == 0
        assert "depends on" in result.output


@pytest.mark.usefixtures("mock_client")
def test_deps_add_blocks(runner: CliRunner):
    """Test deps add with --blocks flag."""
    import httpx
    import respx

    with respx.mock:
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/30/dependencies"
        ).mock(return_value=httpx.Response(201))

        result = runner.invoke(
            main, ["deps", "add", "25", "--repo", "owner/repo", "--blocks", "30"]
        )

        assert result.exit_code == 0
        assert "blocks" in result.output


@pytest.mark.usefixtures("mock_client")
def test_deps_add_error_handling(runner: CliRunner):
    """Test deps add error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(
            main, ["deps", "add", "25", "--repo", "owner/repo", "--on", "999"]
        )

        assert result.exit_code == 1


# --- deps rm tests ---


@pytest.mark.usefixtures("mock_client")
def test_deps_rm_depends_on(runner: CliRunner):
    """Test deps rm with --on flag."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
        ).mock(return_value=httpx.Response(200))

        result = runner.invoke(
            main, ["deps", "rm", "25", "--repo", "owner/repo", "--on", "17"]
        )

        assert result.exit_code == 0
        assert "no longer depends on" in result.output


@pytest.mark.usefixtures("mock_client")
def test_deps_rm_blocks(runner: CliRunner):
    """Test deps rm with --blocks flag."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/issues/30/dependencies"
        ).mock(return_value=httpx.Response(200))

        result = runner.invoke(
            main, ["deps", "rm", "25", "--repo", "owner/repo", "--blocks", "30"]
        )

        assert result.exit_code == 0
        assert "no longer blocks" in result.output


@pytest.mark.usefixtures("mock_client")
def test_deps_rm_error_handling(runner: CliRunner):
    """Test deps rm error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(
            main, ["deps", "rm", "25", "--repo", "owner/repo", "--on", "17"]
        )

        assert result.exit_code == 1


# --- issue edit tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_add_labels(runner: CliRunner):
    """Test issue edit with add-labels."""
    import httpx
    import respx

    with respx.mock:
        # Mock label lookup
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock add labels
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1, "name": "bug", "color": "ff0000"}],
            )
        )

        result = runner.invoke(
            main, ["issue", "edit", "25", "--repo", "owner/repo", "--add-labels", "bug"]
        )

        assert result.exit_code == 0
        assert "Updated issue #25" in result.output
        assert "labels added" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_rm_labels(runner: CliRunner):
    """Test issue edit with rm-labels."""
    import httpx
    import respx

    with respx.mock:
        # Mock label lookup
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {"id": 1, "name": "bug", "color": "ff0000", "description": ""},
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock remove label
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels/1"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main, ["issue", "edit", "25", "--repo", "owner/repo", "--rm-labels", "bug"]
        )

        assert result.exit_code == 0
        assert "labels removed" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_set_labels(runner: CliRunner):
    """Test issue edit with set-labels."""
    import httpx
    import respx

    with respx.mock:
        # Mock label lookup
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {"id": 1, "name": "bug", "color": "ff0000"},
                        {"id": 2, "name": "feature", "color": "00ff00"},
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock set labels
        respx.put(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000"},
                    {"id": 2, "name": "feature", "color": "00ff00"},
                ],
            )
        )

        result = runner.invoke(
            main,
            ["issue", "edit", "25", "-r", "owner/repo", "--set-labels", "bug,feature"],
        )

        assert result.exit_code == 0
        assert "labels set to" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_with_title_and_assignees(runner: CliRunner):
    """Test issue edit with title and assignees."""
    import httpx
    import respx

    with respx.mock:
        # Mock edit issue
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 25,
                    "title": "New Title",
                    "state": "open",
                    "labels": [],
                    "assignees": [{"id": 1, "login": "user1", "full_name": "User One"}],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "issue",
                "edit",
                "25",
                "--repo",
                "owner/repo",
                "--title",
                "New Title",
                "--assignees",
                "user1,user2",
            ],
        )

        assert result.exit_code == 0
        assert "title: New Title" in result.output
        assert "assignees:" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_with_body(runner: CliRunner):
    """Test issue edit with body."""
    import httpx
    import respx

    with respx.mock:
        # Mock edit issue
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 25,
                    "title": "Test",
                    "body": "New body text",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["issue", "edit", "25", "--repo", "owner/repo", "--body", "New body text"],
        )

        assert result.exit_code == 0
        assert "body: New body text" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_with_milestone(runner: CliRunner):
    """Test issue edit with milestone ID."""
    import httpx
    import respx

    with respx.mock:
        # Mock milestone validation (get_milestone call)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/5").mock(
            return_value=httpx.Response(
                200, json={"id": 5, "title": "Sprint 1", "state": "open"}
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 25,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": {"id": 5, "title": "Sprint 1", "state": "open"},
                },
            )
        )

        result = runner.invoke(
            main, ["issue", "edit", "25", "--repo", "owner/repo", "--milestone", "5"]
        )

        assert result.exit_code == 0
        assert "milestone: 5" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_clear_milestone(runner: CliRunner):
    """Test issue edit clearing milestone."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 25,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main, ["issue", "edit", "25", "--repo", "owner/repo", "--milestone", "none"]
        )

        assert result.exit_code == 0
        assert "milestone: cleared" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_with_milestone_name(runner: CliRunner):
    """Test issue edit with milestone name resolution."""
    import httpx
    import respx

    with respx.mock:
        # Mock milestone list (for name lookup)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 3, "title": "v1.0", "state": "open"},
                    {"id": 5, "title": "Sprint 1", "state": "open"},
                ],
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/25").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 25,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": {"id": 5, "title": "Sprint 1", "state": "open"},
                },
            )
        )

        result = runner.invoke(
            main,
            ["issue", "edit", "25", "-r", "owner/repo", "--milestone", "Sprint 1"],
        )

        assert result.exit_code == 0
        assert "milestone: Sprint 1" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_no_changes(runner: CliRunner):
    """Test issue edit with no changes."""
    result = runner.invoke(main, ["issue", "edit", "25", "--repo", "owner/repo"])

    assert result.exit_code == 0
    assert "No changes specified" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_edit_error_handling(runner: CliRunner):
    """Test issue edit error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(
            main, ["issue", "edit", "999", "--repo", "owner/repo", "--title", "New"]
        )

        assert result.exit_code == 1
        assert "Error" in result.output


# --- issue view tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_view_markup_not_interpreted(runner: CliRunner):
    """Test that Rich markup in issue body is not interpreted (security)."""
    import httpx
    import respx

    # Issue body contains Rich markup that could be a phishing vector
    malicious_body = "[link=https://evil.com]Click here[/link] [red]Alert![/red]"

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "open",
                    "body": malicious_body,
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["issue", "view", "42", "--repo", "owner/repo"])

        assert result.exit_code == 0
        # The markup should be printed literally, not interpreted
        assert "[link=" in result.output or "link=" in result.output
        assert "[red]" in result.output or "red]" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_view_comment_markup_not_interpreted(runner: CliRunner):
    """Test that Rich markup in comments is not interpreted (security)."""
    import httpx
    import respx

    malicious_comment = "[link=https://phishing.com]Login here[/link]"

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "number": 42,
                    "title": "Test",
                    "state": "open",
                    "body": "",
                    "labels": None,
                    "assignees": None,
                    "milestone": None,
                },
            )
        )
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/42/comments"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "body": malicious_comment,
                        "user": {"id": 1, "login": "attacker", "full_name": ""},
                        "created_at": "2026-01-14T10:00:00Z",
                        "updated_at": "",
                    }
                ],
            )
        )

        result = runner.invoke(
            main, ["issue", "view", "42", "--repo", "owner/repo", "--comments"]
        )

        assert result.exit_code == 0
        # The markup should be printed literally
        assert "[link=" in result.output or "link=" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_view_basic(runner: CliRunner):
    """Test issue view command."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "open",
                    "body": "Issue body content",
                    "labels": [{"id": 1, "name": "bug", "color": "ff0000"}],
                    "assignees": [{"id": 1, "login": "user1", "full_name": "User One"}],
                    "milestone": {"id": 1, "title": "v1.0", "state": "open"},
                },
            )
        )

        result = runner.invoke(main, ["issue", "view", "42", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "#42" in result.output
        assert "Test Issue" in result.output
        assert "open" in result.output
        assert "bug" in result.output
        assert "user1" in result.output
        assert "v1.0" in result.output
        assert "Issue body content" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_view_with_comments(runner: CliRunner):
    """Test issue view command with --comments flag."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "open",
                    "body": "Issue body",
                    "labels": None,
                    "assignees": None,
                    "milestone": None,
                },
            )
        )
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/42/comments"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "body": "First comment",
                        "user": {"id": 1, "login": "commenter", "full_name": ""},
                        "created_at": "2026-01-14T10:00:00Z",
                        "updated_at": "",
                    }
                ],
            )
        )

        result = runner.invoke(
            main, ["issue", "view", "42", "--repo", "owner/repo", "--comments"]
        )

        assert result.exit_code == 0
        assert "Comments (1)" in result.output
        assert "commenter" in result.output
        assert "First comment" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_view_no_comments(runner: CliRunner):
    """Test issue view shows 'No comments' when none exist."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "closed",
                    "body": "",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/42/comments"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(
            main, ["issue", "view", "42", "--repo", "owner/repo", "--comments"]
        )

        assert result.exit_code == 0
        assert "No comments" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_view_error_handling(runner: CliRunner):
    """Test issue view error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(main, ["issue", "view", "999", "--repo", "owner/repo"])

        assert result.exit_code == 1


# --- issue batch tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_basic(runner: CliRunner):
    """Test issue batch command with multiple issues."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "First Issue",
                    "state": "open",
                    "body": "Body of first issue",
                    "labels": [{"id": 1, "name": "bug", "color": "ff0000"}],
                    "assignees": [{"id": 1, "login": "user1", "full_name": ""}],
                    "milestone": {"id": 1, "title": "v1.0", "state": "open"},
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/2").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 2,
                    "number": 2,
                    "title": "Second Issue",
                    "state": "closed",
                    "body": "",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["issue", "batch", "1,2", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "First Issue" in result.output
        assert "Second Issue" in result.output
        assert "bug" in result.output
        assert "v1.0" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_json_output(runner: CliRunner):
    """Test issue batch with JSON output format."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Test Issue",
                    "state": "open",
                    "body": "Full body text that should not be truncated in JSON",
                    "labels": [{"id": 1, "name": "enhancement", "color": "00ff00"}],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "issue", "batch", "1", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["issues"]) == 1
        assert data["issues"][0]["number"] == 1
        assert data["issues"][0]["title"] == "Test Issue"
        assert data["issues"][0]["state"] == "open"
        assert data["issues"][0]["labels"] == ["enhancement"]
        assert "Full body text" in data["issues"][0]["body"]
        assert data["errors"] == {}


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_csv_output(runner: CliRunner):
    """Test issue batch with CSV output format."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "CSV Test",
                    "state": "open",
                    "body": "Short body",
                    "labels": [{"id": 1, "name": "bug", "color": "ff0000"}],
                    "assignees": [{"id": 1, "login": "dev", "full_name": ""}],
                    "milestone": {"id": 1, "title": "Sprint", "state": "open"},
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "csv", "issue", "batch", "1", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "number,title,state,labels,assignees,milestone,body" in result.output
        assert "1,CSV Test,open,bug,dev,Sprint" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_simple_output(runner: CliRunner):
    """Test issue batch with simple output format."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Simple Test",
                    "state": "open",
                    "body": "",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "simple", "issue", "batch", "1", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "#1 Simple Test" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_with_range(runner: CliRunner):
    """Test issue batch with range specification."""
    import httpx
    import respx

    with respx.mock:
        for i in range(1, 4):
            respx.get(
                f"https://test.example.com/api/v1/repos/owner/repo/issues/{i}"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": i,
                        "number": i,
                        "title": f"Issue {i}",
                        "state": "open",
                        "body": "",
                        "labels": [],
                        "assignees": [],
                        "milestone": None,
                    },
                )
            )

        result = runner.invoke(main, ["issue", "batch", "1-3", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "Issue 1" in result.output
        assert "Issue 2" in result.output
        assert "Issue 3" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_partial_failure(runner: CliRunner):
    """Test issue batch continues on individual failures."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Existing Issue",
                    "state": "open",
                    "body": "",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(
            main, ["issue", "batch", "1,999", "--repo", "owner/repo"]
        )

        # Exit code 1 because there were errors
        assert result.exit_code == 1
        assert "Existing Issue" in result.output
        # Should show error for missing issue
        assert "999" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_json_with_errors(runner: CliRunner):
    """Test issue batch JSON output includes errors."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Valid Issue",
                    "state": "open",
                    "body": "",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/404").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(
            main, ["-o", "json", "issue", "batch", "1,404", "--repo", "owner/repo"]
        )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert len(data["issues"]) == 1
        assert data["issues"][0]["number"] == 1
        assert "404" in data["errors"]
        assert "not found" in data["errors"]["404"].lower()


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_empty_result(runner: CliRunner):
    """Test issue batch when all issues fail."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(main, ["issue", "batch", "999", "--repo", "owner/repo"])

        assert result.exit_code == 1
        assert "999" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_body_truncation_table(runner: CliRunner):
    """Test issue batch truncates body in table output."""
    import httpx
    import respx

    long_body = "A" * 300  # Longer than 200 chars

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Long Body",
                    "state": "open",
                    "body": long_body,
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["issue", "batch", "1", "--repo", "owner/repo"])

        assert result.exit_code == 0
        # Should be truncated - Rich uses ellipsis character (…) or ...
        assert "…" in result.output or "..." in result.output
        # Full body should not appear
        assert long_body not in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_batch_body_full_in_json(runner: CliRunner):
    """Test issue batch includes full body in JSON output."""
    import json

    import httpx
    import respx

    long_body = "B" * 300  # Longer than 200 chars

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "number": 1,
                    "title": "Long Body",
                    "state": "open",
                    "body": long_body,
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "issue", "batch", "1", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        # JSON should have full body
        assert data["issues"][0]["body"] == long_body


# --- issue labels tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_labels_command(runner: CliRunner):
    """Test issue labels command."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/25/labels"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1, "name": "bug", "color": "ff0000"}],
            )
        )

        result = runner.invoke(main, ["issue", "labels", "25", "--repo", "owner/repo"])

        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_issue_labels_error_handling(runner: CliRunner):
    """Test issue labels error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/999/labels"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(main, ["issue", "labels", "999", "--repo", "owner/repo"])

        assert result.exit_code == 1


# --- issue bulk execution tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_execute_with_yes_flag(runner: CliRunner):
    """Test issue bulk command with -y flag executes changes."""
    import httpx
    import respx

    with respx.mock:
        # Mock label lookup
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 1, "name": "bug", "color": "ff0000"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock add labels for each issue
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels"
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/18/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(
            main,
            ["issue", "bulk", "17,18", "-r", "owner/repo", "--add-labels", "bug", "-y"],
        )

        assert result.exit_code == 0
        assert "✓" in result.output
        assert "2 succeeded" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_with_assignees(runner: CliRunner):
    """Test issue bulk command with assignees."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 17,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "-r", "owner/repo", "--assignees", "user1", "-y"],
        )

        assert result.exit_code == 0
        assert "1 succeeded" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_with_milestone_validation(runner: CliRunner):
    """Test issue bulk command validates milestone exists."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/5").mock(
            return_value=httpx.Response(
                200, json={"id": 5, "title": "Sprint 1", "state": "open"}
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 17,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": {"id": 5, "title": "Sprint 1", "state": "open"},
                },
            )
        )

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "--repo", "owner/repo", "--milestone", "5", "-y"],
        )

        assert result.exit_code == 0
        assert "1 succeeded" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_milestone_not_found(runner: CliRunner):
    """Test issue bulk command fails fast when milestone doesn't exist."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/milestones/999"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "--repo", "owner/repo", "--milestone", "999", "-y"],
        )

        assert result.exit_code == 1
        assert "Milestone '999' not found" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_with_partial_failure(runner: CliRunner):
    """Test issue bulk command handles partial failures."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 17,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/18").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(
            main,
            ["issue", "bulk", "17,18", "-r", "owner/repo", "--assignees", "u1", "-y"],
        )

        assert result.exit_code == 1
        assert "1 succeeded" in result.output
        assert "1 failed" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_rm_labels(runner: CliRunner):
    """Test issue bulk command with rm-labels."""
    import httpx
    import respx

    with respx.mock:
        # Mock label lookup
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 1, "name": "bug", "color": "ff0000"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock remove label
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels/1"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "--repo", "owner/repo", "--rm-labels", "bug", "-y"],
        )

        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_set_labels(runner: CliRunner):
    """Test issue bulk command with set-labels."""
    import httpx
    import respx

    with respx.mock:
        # Mock label lookup
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 1, "name": "bug", "color": "ff0000"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock set labels
        respx.put(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "-r", "owner/repo", "--set-labels", "bug", "-y"],
        )

        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_issue_bulk_clear_milestone(runner: CliRunner):
    """Test issue bulk command clearing milestone."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 17,
                    "title": "Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["issue", "bulk", "17", "--repo", "owner/repo", "--milestone", "", "-y"],
        )

        assert result.exit_code == 0


# --- issue close/reopen tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_close_single(runner: CliRunner):
    """Test closing a single issue."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 200,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "closed",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "simple", "issue", "close", "42", "-r", "owner/repo"],
        )

        assert result.exit_code == 0
        assert "Closed #42" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_close_multiple_with_yes(runner: CliRunner):
    """Test closing multiple issues with -y flag."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 200,
                    "number": 42,
                    "title": "Test Issue 1",
                    "state": "closed",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/43").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 201,
                    "number": 43,
                    "title": "Test Issue 2",
                    "state": "closed",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "simple", "issue", "close", "42,43", "-r", "owner/repo", "-y"],
        )

        assert result.exit_code == 0
        assert "Closed #42" in result.output
        assert "Closed #43" in result.output
        assert "2 closed" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_close_range(runner: CliRunner):
    """Test closing a range of issues."""
    import httpx
    import respx

    with respx.mock:
        for num in [10, 11, 12]:
            respx.patch(
                f"https://test.example.com/api/v1/repos/owner/repo/issues/{num}"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": 100 + num,
                        "number": num,
                        "title": f"Test Issue {num}",
                        "state": "closed",
                        "labels": [],
                        "assignees": [],
                        "milestone": None,
                    },
                )
            )

        result = runner.invoke(
            main,
            ["-o", "simple", "issue", "close", "10-12", "-r", "owner/repo", "-y"],
        )

        assert result.exit_code == 0
        assert "3 closed" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_reopen_single(runner: CliRunner):
    """Test reopening a single issue."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 200,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "simple", "issue", "reopen", "42", "-r", "owner/repo"],
        )

        assert result.exit_code == 0
        assert "Reopened #42" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_reopen_multiple_with_yes(runner: CliRunner):
    """Test reopening multiple issues with -y flag."""
    import httpx
    import respx

    with respx.mock:
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 200,
                    "number": 42,
                    "title": "Test Issue 1",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/43").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 201,
                    "number": 43,
                    "title": "Test Issue 2",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "simple", "issue", "reopen", "42,43", "-r", "owner/repo", "-y"],
        )

        assert result.exit_code == 0
        assert "Reopened #42" in result.output
        assert "Reopened #43" in result.output
        assert "2 reopened" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_close_confirmation_abort(runner: CliRunner):
    """Test closing multiple issues aborts on confirmation decline."""
    result = runner.invoke(
        main,
        ["issue", "close", "42,43", "-r", "owner/repo"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert "Cancelled" in result.output


# --- issue create tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_create_basic(runner: CliRunner):
    """Test creating an issue with just title."""
    import httpx
    import respx

    with respx.mock:
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 300,
                    "number": 50,
                    "title": "New Issue",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                    "body": "",
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "simple", "issue", "create", "-r", "owner/repo", "-t", "New Issue"],
        )

        assert result.exit_code == 0
        assert "Created #50" in result.output
        assert "New Issue" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_create_with_labels(runner: CliRunner):
    """Test creating an issue with labels."""
    import httpx
    import respx

    with respx.mock:
        # Mock list labels
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "bug", "color": "ff0000"},
                    {"id": 2, "name": "urgent", "color": "ff0000"},
                ],
            )
        )
        # Mock create issue
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 301,
                    "number": 51,
                    "title": "Bug",
                    "state": "open",
                    "labels": [{"id": 1, "name": "bug", "color": "ff0000"}],
                    "assignees": [],
                    "milestone": None,
                    "body": "",
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "simple",
                "issue",
                "create",
                "-r",
                "owner/repo",
                "-t",
                "Bug",
                "-l",
                "bug",
            ],
        )

        assert result.exit_code == 0
        assert "Created #51" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_create_json_output(runner: CliRunner):
    """Test creating an issue with JSON output."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 302,
                    "number": 52,
                    "title": "JSON Test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                    "body": "",
                    "html_url": "https://example.com/issues/52",
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "json", "issue", "create", "-r", "owner/repo", "-t", "JSON Test"],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["number"] == 52
        assert data["title"] == "JSON Test"


@pytest.mark.usefixtures("mock_client")
def test_issue_create_label_not_found(runner: CliRunner):
    """Test creating an issue with non-existent label fails."""
    import httpx
    import respx

    with respx.mock:
        # Mock list labels (no matching label)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1, "name": "bug", "color": "ff0000"}],
            )
        )

        result = runner.invoke(
            main,
            [
                "issue",
                "create",
                "-r",
                "owner/repo",
                "-t",
                "Test",
                "-l",
                "nonexistent",
            ],
        )

        assert result.exit_code == 1
        assert "Label not found" in result.output


# --- issue comment tests ---


@pytest.mark.usefixtures("mock_client")
def test_issue_comment_create(runner: CliRunner):
    """Test creating a comment on an issue."""
    import httpx
    import respx

    with respx.mock:
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/42/comments"
        ).mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 12345,
                    "body": "Test comment",
                    "user": {"id": 1, "login": "testuser", "full_name": "Test User"},
                    "created_at": "2024-01-15T10:00:00Z",
                    "updated_at": "2024-01-15T10:00:00Z",
                },
            )
        )

        result = runner.invoke(
            main,
            ["issue", "comment", "42", "-r", "owner/repo", "-m", "Test comment"],
        )

        assert result.exit_code == 0
        assert "Added comment #12345" in result.output
        assert "issue #42" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_comment_edit(runner: CliRunner):
    """Test editing a comment."""
    import httpx
    import respx

    with respx.mock:
        respx.patch(
            "https://test.example.com/api/v1/repos/owner/repo/issues/comments/12345"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 12345,
                    "body": "Updated comment",
                    "user": {"id": 1, "login": "testuser", "full_name": "Test User"},
                    "created_at": "2024-01-15T10:00:00Z",
                    "updated_at": "2024-01-15T11:00:00Z",
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "issue",
                "comment-edit",
                "12345",
                "-r",
                "owner/repo",
                "-m",
                "Updated comment",
            ],
        )

        assert result.exit_code == 0
        assert "Updated comment #12345" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_comment_delete(runner: CliRunner):
    """Test deleting a comment."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/issues/comments/12345"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            ["issue", "comment-delete", "12345", "-r", "owner/repo", "-y"],
        )

        assert result.exit_code == 0
        assert "Deleted comment #12345" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_comment_delete_cancelled(runner: CliRunner):
    """Test deleting a comment with cancelled confirmation."""
    result = runner.invoke(
        main,
        ["issue", "comment-delete", "12345", "-r", "owner/repo"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert "Cancelled" in result.output


@pytest.mark.usefixtures("mock_client")
def test_issue_view_shows_comment_id(runner: CliRunner):
    """Test issue view shows comment IDs."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "number": 42,
                    "title": "Test Issue",
                    "state": "open",
                    "body": "Test body",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/issues/42/comments"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 99999,
                        "body": "A comment",
                        "user": {"id": 1, "login": "user1", "full_name": "User One"},
                        "created_at": "2024-01-15T10:00:00Z",
                    }
                ],
            )
        )

        result = runner.invoke(
            main, ["issue", "view", "42", "--repo", "owner/repo", "--comments"]
        )

        assert result.exit_code == 0
        assert "#99999" in result.output  # Comment ID shown


# --- epic create tests ---


@pytest.mark.usefixtures("mock_client")
def test_epic_create_basic(runner: CliRunner):
    """Test epic create basic flow."""
    import httpx
    import respx

    with respx.mock:
        # Mock list repo labels (label doesn't exist)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(200, json=[]),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock create label
        respx.post("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 10,
                    "name": "epic/test",
                    "color": "9b59b6",
                    "description": "Epic: test",
                },
            )
        )
        # Mock create issue
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["epic", "create", "test", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "Epic created successfully" in result.output
        assert "#50" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_create_with_children(runner: CliRunner):
    """Test epic create with child issues."""
    import httpx
    import respx

    with respx.mock:
        # Mock list repo labels (label doesn't exist)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(200, json=[]),
                httpx.Response(200, json=[]),
                # For add_issue_labels to children
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock create label
        respx.post("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 10,
                    "name": "epic/test",
                    "color": "9b59b6",
                    "description": "Epic: test",
                },
            )
        )
        # Mock create issue
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        # Mock add labels to children
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels"
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/18/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(
            main,
            ["epic", "create", "test", "--repo", "owner/repo", "-c", "17", "-c", "18"],
        )

        assert result.exit_code == 0
        assert "Epic created successfully" in result.output
        assert "2 issues labeled" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_create_deduplicates_children(runner: CliRunner, monkeypatch):
    """Test epic create deduplicates child issues."""
    from io import StringIO

    import httpx
    import respx
    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    with respx.mock:
        # Mock label responses for:
        # 1. list_repo_labels() check in epic_create
        # 2. _resolve_label_ids() in add_issue_labels for children (uses cache)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                # list_repo_labels - label exists
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                # _resolve_label_ids for child labeling (not cached separately)
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
            ]
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels"
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/18/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        # Pass duplicate children: 17, 18, 17 (will be deduplicated to 17, 18)
        result = runner.invoke(
            main,
            [
                "epic",
                "create",
                "test",
                "-r",
                "owner/repo",
                "-c",
                "17",
                "-c",
                "18",
                "-c",
                "17",
            ],
        )

        output = buffer.getvalue()
        assert result.exit_code == 0
        assert "Duplicate child issues removed" in output
        assert "3 → 2" in output  # 3 inputs, 2 unique
        assert "2 issues labeled" in output


@pytest.mark.usefixtures("mock_client")
def test_epic_create_label_exists(runner: CliRunner):
    """Test epic create when label already exists."""
    import httpx
    import respx

    with respx.mock:
        # Mock list repo labels (label exists)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {"id": 10, "name": "epic/test", "color": "9b59b6"},
                        {"id": 20, "name": "type/epic", "color": "000000"},
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock create issue
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["epic", "create", "test", "--repo", "owner/repo"])

        assert result.exit_code == 0
        # Should not create a new label
        assert "Creating label" not in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_create_child_label_error(runner: CliRunner):
    """Test epic create handles child labeling errors gracefully."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                httpx.Response(200, json=[]),
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        # Child labeling fails
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/999/labels"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(
            main,
            ["epic", "create", "test", "--repo", "owner/repo", "-c", "999"],
        )

        assert result.exit_code == 0
        assert "✗" in result.output  # Shows error for child


@pytest.mark.usefixtures("mock_client")
def test_epic_create_error_handling(runner: CliRunner):
    """Test epic create main error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )

        result = runner.invoke(main, ["epic", "create", "test", "--repo", "owner/repo"])

        assert result.exit_code == 1
        assert "Error" in result.output


def test_epic_create_invalid_color(runner: CliRunner):
    """Test epic create rejects invalid color format."""
    # Invalid: too short
    result = runner.invoke(
        main, ["epic", "create", "test", "--repo", "owner/repo", "--color", "ff00"]
    )
    assert result.exit_code == 2  # Click parameter error
    assert "6-character hex code" in result.output

    # Invalid: contains non-hex character
    result = runner.invoke(
        main, ["epic", "create", "test", "--repo", "owner/repo", "--color", "gggggg"]
    )
    assert result.exit_code == 2
    assert "6-character hex code" in result.output

    # Invalid: includes # prefix
    result = runner.invoke(
        main, ["epic", "create", "test", "--repo", "owner/repo", "--color", "#ff0000"]
    )
    assert result.exit_code == 2
    assert "6-character hex code" in result.output


def test_epic_create_valid_colors(runner: CliRunner):
    """Test epic create accepts valid color formats."""
    # These should fail later (API call) not at validation, so we just check
    # they don't fail with "6-character hex code" error
    valid_colors = ["ff0000", "FF0000", "aAbBcC", "123456", "000000", "ffffff"]
    for color in valid_colors:
        result = runner.invoke(
            main, ["epic", "create", "test", "--repo", "owner/repo", "--color", color]
        )
        # Should fail at API call (no mock), not at color validation
        assert "6-character hex code" not in result.output


# --- epic status tests ---


@pytest.mark.usefixtures("mock_client")
def test_epic_status_basic(runner: CliRunner):
    """Test epic status with children."""
    import httpx
    import respx

    with respx.mock:
        # Mock get epic issue
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n- [ ] #17\n- [x] #18\n",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        # Mock get child issues
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 101,
                    "number": 17,
                    "title": "Child One",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/18").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 102,
                    "number": 18,
                    "title": "Child Two",
                    "state": "closed",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["epic", "status", "50", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "Epic #50" in result.output
        assert "1/2" in result.output  # 1 of 2 complete
        assert "50%" in result.output
        assert "Completed" in result.output
        assert "Open" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_status_no_children(runner: CliRunner):
    """Test epic status with no children."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n_No child issues yet._\n",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(main, ["epic", "status", "50", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "No child issues found" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_status_child_fetch_error(runner: CliRunner):
    """Test epic status handles child fetch errors gracefully."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n- [ ] #17\n- [ ] #999\n",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/17").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 101,
                    "number": 17,
                    "title": "Child One",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(main, ["epic", "status", "50", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "unable to fetch" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_status_error_handling(runner: CliRunner):
    """Test epic status main error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(main, ["epic", "status", "999", "--repo", "owner/repo"])

        assert result.exit_code == 1
        assert "Error" in result.output


# --- epic add tests ---


@pytest.mark.usefixtures("mock_client")
def test_epic_add_basic(runner: CliRunner):
    """Test epic add basic flow."""
    import httpx
    import respx

    with respx.mock:
        # Mock get epic issue
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n- [ ] #17\n",
                    "state": "open",
                    "labels": [{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        # Mock edit epic issue (update body)
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n- [ ] #17\n- [ ] #18\n",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        # Mock label lookup and add
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/18/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(
            main, ["epic", "add", "50", "18", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "Updated epic #50" in result.output
        assert "Added 1 issues" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_add_multiple_children(runner: CliRunner):
    """Test epic add with multiple children."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n_No child issues yet._\n",
                    "state": "open",
                    "labels": [{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels"
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/18/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(
            main, ["epic", "add", "50", "17", "18", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "Added 2 issues" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_add_deduplicates_children(runner: CliRunner, monkeypatch):
    """Test epic add deduplicates child issues."""
    from io import StringIO

    import httpx
    import respx
    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n_No child issues yet._\n",
                    "state": "open",
                    "labels": [{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
            ]
        )
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/17/labels"
        ).mock(return_value=httpx.Response(200, json=[]))
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/18/labels"
        ).mock(return_value=httpx.Response(200, json=[]))

        # Pass duplicate children: 17, 18, 17
        result = runner.invoke(
            main, ["epic", "add", "50", "17", "18", "17", "--repo", "owner/repo"]
        )

        output = buffer.getvalue()
        assert result.exit_code == 0
        assert "Duplicate child issues removed" in output
        assert "3 → 2" in output  # 3 inputs, 2 unique
        assert "Added 2 issues" in output


@pytest.mark.usefixtures("mock_client")
def test_epic_add_no_epic_label_warning(runner: CliRunner, monkeypatch):
    """Test epic add warns when epic has no epic/* label."""
    from io import StringIO

    import httpx
    import respx
    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n",
                    "state": "open",
                    "labels": [],  # No epic/* label
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )

        result = runner.invoke(
            main, ["epic", "add", "50", "17", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        output = buffer.getvalue()
        assert "Warning" in output
        assert "No epic/* label found" in output


@pytest.mark.usefixtures("mock_client")
def test_epic_add_child_label_error(runner: CliRunner):
    """Test epic add handles child labeling errors gracefully."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "body": "## Child Issues\n\n",
                    "state": "open",
                    "labels": [{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.patch("https://test.example.com/api/v1/repos/owner/repo/issues/50").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100,
                    "number": 50,
                    "title": "Epic: test",
                    "state": "open",
                    "labels": [],
                    "assignees": [],
                    "milestone": None,
                },
            )
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/labels").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[{"id": 10, "name": "epic/test", "color": "9b59b6"}],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/issues/999/labels"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(
            main, ["epic", "add", "50", "999", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "✗" in result.output


@pytest.mark.usefixtures("mock_client")
def test_epic_add_error_handling(runner: CliRunner):
    """Test epic add main error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(
            main, ["epic", "add", "999", "17", "--repo", "owner/repo"]
        )

        assert result.exit_code == 1
        assert "Error" in result.output


# --- Runners Tests ---


def test_runners_help(runner: CliRunner):
    """Test runners group help shows commands."""
    result = runner.invoke(main, ["runners", "--help"])

    assert result.exit_code == 0
    assert "list" in result.output
    assert "get" in result.output
    assert "delete" in result.output
    assert "token" in result.output


def test_runners_list_help(runner: CliRunner):
    """Test runners list command help."""
    result = runner.invoke(main, ["runners", "list", "--help"])

    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--org" in result.output
    assert "--global" in result.output


def test_runners_list_requires_scope(runner: CliRunner):
    """Test runners list requires scope option."""
    result = runner.invoke(main, ["runners", "list"])

    assert result.exit_code != 0
    assert "Must specify --repo, --org, or --global" in result.output


def test_runners_list_rejects_multiple_scopes(runner: CliRunner):
    """Test runners list rejects multiple scope options."""
    result = runner.invoke(
        main, ["runners", "list", "--repo", "owner/repo", "--org", "myorg"]
    )

    assert result.exit_code != 0
    assert "Specify only one of" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_list_repo_scope(runner: CliRunner):
    """Test runners list with repo scope."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "runner-1",
                        "status": "online",
                        "busy": False,
                        "labels": ["ubuntu-latest"],
                        "version": "v0.2.6",
                    },
                ],
            )
        )

        result = runner.invoke(main, ["runners", "list", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "runner-1" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_list_org_scope(runner: CliRunner):
    """Test runners list with org scope."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/orgs/myorg/actions/runners").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 10,
                        "name": "org-runner",
                        "status": "online",
                        "busy": True,
                        "labels": [],
                        "version": "",
                    },
                ],
            )
        )

        result = runner.invoke(main, ["runners", "list", "--org", "myorg"])

        assert result.exit_code == 0
        assert "org-runner" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_list_global_scope(runner: CliRunner):
    """Test runners list with global scope."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/admin/actions/runners").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 100,
                        "name": "global-runner",
                        "status": "idle",
                        "busy": False,
                        "labels": [],
                        "version": "",
                    },
                ],
            )
        )

        result = runner.invoke(main, ["runners", "list", "--global"])

        assert result.exit_code == 0
        assert "global-runner" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_list_simple_output(runner: CliRunner):
    """Test runners list with simple output format."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "runner-1",
                        "status": "online",
                        "busy": False,
                        "labels": [],
                        "version": "",
                    },
                ],
            )
        )

        result = runner.invoke(
            main, ["-o", "simple", "runners", "list", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "1 runner-1" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_list_json_output(runner: CliRunner):
    """Test runners list with JSON output format."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "runner-1",
                        "status": "online",
                        "busy": False,
                        "labels": ["ubuntu-latest"],
                        "version": "v0.2.6",
                    },
                ],
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "runners", "list", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == 1
        assert data[0]["name"] == "runner-1"


@pytest.mark.usefixtures("mock_client")
def test_runners_get_basic(runner: CliRunner):
    """Test runners get command."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/42"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 42,
                    "name": "my-runner",
                    "status": "online",
                    "busy": True,
                    "labels": ["ubuntu-latest"],
                    "version": "v0.2.6",
                },
            )
        )

        result = runner.invoke(main, ["runners", "get", "42", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "my-runner" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_get_error(runner: CliRunner):
    """Test runners get error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/999"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(main, ["runners", "get", "999", "--repo", "owner/repo"])

        assert result.exit_code == 1
        assert "Error" in result.output


def test_runners_delete_requires_scope(runner: CliRunner):
    """Test runners delete requires scope option."""
    result = runner.invoke(main, ["runners", "delete", "42"])

    assert result.exit_code != 0
    assert "Must specify --repo, --org, or --global" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_delete_confirmation(runner: CliRunner):
    """Test runners delete prompts for confirmation."""
    result = runner.invoke(
        main, ["runners", "delete", "42", "--repo", "owner/repo"], input="n\n"
    )

    assert result.exit_code == 0
    assert "Aborted" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_delete_with_yes_flag(runner: CliRunner):
    """Test runners delete with -y flag skips confirmation."""
    import httpx
    import respx

    with respx.mock:
        route = respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/42"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main, ["runners", "delete", "42", "--repo", "owner/repo", "-y"]
        )

        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runners_delete_error(runner: CliRunner):
    """Test runners delete error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/999"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(
            main, ["runners", "delete", "999", "--repo", "owner/repo", "-y"]
        )

        assert result.exit_code == 1
        assert "Error" in result.output


def test_runners_token_requires_scope(runner: CliRunner):
    """Test runners token requires scope option."""
    result = runner.invoke(main, ["runners", "token"])

    assert result.exit_code != 0
    assert "Must specify --repo, --org, or --global" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_token_table_shows_warning(runner: CliRunner):
    """Test runners token shows warning in table mode."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/registration-token"
        ).mock(return_value=httpx.Response(200, json={"token": "AAABBBCCCDDD123456"}))

        result = runner.invoke(main, ["runners", "token", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "Warning" in result.output
        assert "secret" in result.output
        assert "AAABBBCCCDDD123456" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runners_token_simple_no_warning(runner: CliRunner):
    """Test runners token simple output has no warning."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/registration-token"
        ).mock(return_value=httpx.Response(200, json={"token": "AAABBBCCCDDD123456"}))

        result = runner.invoke(
            main, ["-o", "simple", "runners", "token", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "Warning" not in result.output
        assert result.output.strip() == "AAABBBCCCDDD123456"


@pytest.mark.usefixtures("mock_client")
def test_runners_token_json_output(runner: CliRunner):
    """Test runners token JSON output."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/registration-token"
        ).mock(return_value=httpx.Response(200, json={"token": "JSON_TOKEN_123"}))

        result = runner.invoke(
            main, ["-o", "json", "runners", "token", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["token"] == "JSON_TOKEN_123"


@pytest.mark.usefixtures("mock_client")
def test_runners_token_error(runner: CliRunner):
    """Test runners token error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runners/registration-token"
        ).mock(return_value=httpx.Response(403, json={"message": "Forbidden"}))

        result = runner.invoke(main, ["runners", "token", "--repo", "owner/repo"])

        assert result.exit_code == 1
        assert "Error" in result.output


def test_output_format_print_runners_simple(capsys):
    """Test OutputFormat.print_runners simple format."""
    runner = SimpleNamespace(
        id=1, name="runner-1", status="online", busy=False, labels=[], version=""
    )
    output = OutputFormat("simple")
    output.print_runners([runner])

    captured = capsys.readouterr()
    assert "1 runner-1" in captured.out


def test_output_format_print_runners_empty(capsys):
    """Test OutputFormat.print_runners with empty list."""
    output = OutputFormat("table")
    output.print_runners([])

    captured = capsys.readouterr()
    assert "No runners found" in captured.out


def test_output_format_print_runners_csv(capsys):
    """Test OutputFormat.print_runners CSV format."""
    runner = SimpleNamespace(
        id=1,
        name="runner-1",
        status="online",
        busy=False,
        labels=["ubuntu-latest", "self-hosted"],
        version="v0.2.6",
    )
    output = OutputFormat("csv")
    output.print_runners([runner])

    captured = capsys.readouterr()
    reader = csv.reader(io.StringIO(captured.out))
    rows = list(reader)
    assert rows[0] == ["id", "name", "status", "busy", "labels", "version"]
    assert rows[1][0] == "1"
    assert rows[1][1] == "runner-1"
    assert "ubuntu-latest" in rows[1][4]


# --- pkg list tests ---


@pytest.mark.usefixtures("mock_client")
def test_pkg_list(runner: CliRunner):
    """Test pkg list command."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/packages/myorg").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1,
                            "owner": {"id": 1, "login": "myorg", "full_name": "My Org"},
                            "name": "mypackage",
                            "type": "generic",
                            "version": "1.0.0",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "https://test.example.com/myorg/-/packages/generic/mypackage/1.0.0",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),  # Empty page signals end
            ]
        )

        result = runner.invoke(main, ["pkg", "list", "--owner", "myorg"])

        assert result.exit_code == 0
        assert "mypackage" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_list_with_type_filter(runner: CliRunner):
    """Test pkg list command with --type filter."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get("https://test.example.com/api/packages/myorg").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1,
                            "owner": {"id": 1, "login": "myorg", "full_name": "My Org"},
                            "name": "myimage",
                            "type": "container",
                            "version": "latest",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        result = runner.invoke(
            main, ["pkg", "list", "--owner", "myorg", "--type", "container"]
        )

        assert result.exit_code == 0
        assert "myimage" in result.output
        # Verify type filter was passed as query param
        assert route.calls[0].request.url.params.get("type") == "container"


@pytest.mark.usefixtures("mock_client")
def test_pkg_list_empty(runner: CliRunner):
    """Test pkg list command with no packages."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/packages/myorg").mock(
            return_value=httpx.Response(200, json=[])
        )

        result = runner.invoke(main, ["pkg", "list", "--owner", "myorg"])

        assert result.exit_code == 0
        assert "No packages found" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_list_json_output(runner: CliRunner):
    """Test pkg list command with JSON output."""
    import json as json_mod

    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/packages/myorg").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1,
                            "owner": {"id": 1, "login": "myorg", "full_name": "My Org"},
                            "name": "mypackage",
                            "type": "pypi",
                            "version": "0.1.0",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        # --output is a global option, so it comes before the subcommand
        result = runner.invoke(
            main, ["--output", "json", "pkg", "list", "--owner", "myorg"]
        )

        assert result.exit_code == 0
        data = json_mod.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "mypackage"
        assert data[0]["type"] == "pypi"


# --- pkg info tests ---


@pytest.mark.usefixtures("mock_client")
def test_pkg_info(runner: CliRunner):
    """Test pkg info command."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/packages/myorg/generic/mypackage").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1,
                            "version": "1.0.0",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "",
                        },
                        {
                            "id": 2,
                            "version": "1.1.0",
                            "created_at": "2024-01-15T00:00:00Z",
                            "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        result = runner.invoke(
            main,
            ["pkg", "info", "mypackage", "--owner", "myorg", "--type", "generic"],
        )

        assert result.exit_code == 0
        assert "1.0.0" in result.output
        assert "1.1.0" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_info_not_found(runner: CliRunner):
    """Test pkg info command with non-existent package."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/packages/myorg/generic/nonexistent"
        ).mock(return_value=httpx.Response(404, json={"message": "package not found"}))

        result = runner.invoke(
            main,
            ["pkg", "info", "nonexistent", "--owner", "myorg", "--type", "generic"],
        )

        assert result.exit_code == 1
        assert "Error" in result.output


# --- pkg delete tests ---


@pytest.mark.usefixtures("mock_client")
def test_pkg_delete(runner: CliRunner):
    """Test pkg delete command."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/packages/myorg/generic/mypackage/1.0.0"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "pkg",
                "delete",
                "mypackage",
                "--owner",
                "myorg",
                "--type",
                "generic",
                "--version",
                "1.0.0",
                "--yes",
            ],
        )

        assert result.exit_code == 0
        assert "Deleted" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_delete_pypi_blocked(runner: CliRunner):
    """Test pkg delete command blocks PyPI packages."""
    import respx

    with respx.mock:
        # No HTTP mock needed - should fail before API call
        result = runner.invoke(
            main,
            [
                "pkg",
                "delete",
                "mypackage",
                "--owner",
                "myorg",
                "--type",
                "pypi",
                "--version",
                "0.1.0",
                "--yes",
            ],
        )

        assert result.exit_code == 1
        assert "PyPI packages cannot be deleted" in result.output
        assert "web UI" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_delete_requires_confirmation(runner: CliRunner):
    """Test pkg delete command requires confirmation."""
    result = runner.invoke(
        main,
        [
            "pkg",
            "delete",
            "mypackage",
            "--owner",
            "myorg",
            "--type",
            "generic",
            "--version",
            "1.0.0",
        ],
        input="n\n",  # Say no to confirmation
    )

    # Returns 0 (not error) when user aborts gracefully
    assert result.exit_code == 0
    assert "Aborted" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_delete_rich_injection_escaped(runner: CliRunner):
    """Test pkg delete escapes Rich markup in user input to prevent injection."""
    import httpx
    import respx

    with respx.mock:
        respx.delete(
            "https://test.example.com/api/packages/myorg/generic/%5Bred%5DX%5B%2Fred%5D/1.0.0"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "pkg",
                "delete",
                "[red]X[/red]",  # Malicious Rich markup
                "--owner",
                "myorg",
                "--type",
                "generic",
                "--version",
                "1.0.0",
                "-y",  # Skip confirmation
            ],
        )

        assert result.exit_code == 0
        # The literal markup should appear escaped, not rendered as red text
        # Rich escapes [] as \\[ in output, so check for the escaped form
        assert "[red]" in result.output or "\\[red\\]" in result.output


# --- pkg prune tests ---


@pytest.mark.usefixtures("mock_client")
def test_pkg_prune_dry_run(runner: CliRunner):
    """Test pkg prune command in dry-run mode (default)."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/packages/myorg/container/myimage").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1,
                            "version": "v1.0.0",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "",
                        },
                        {
                            "id": 2,
                            "version": "v1.1.0",
                            "created_at": "2024-01-15T00:00:00Z",
                            "html_url": "",
                        },
                        {
                            "id": 3,
                            "version": "v1.2.0",
                            "created_at": "2024-02-01T00:00:00Z",
                            "html_url": "",
                        },
                        {
                            "id": 4,
                            "version": "v1.3.0",
                            "created_at": "2024-02-15T00:00:00Z",
                            "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        result = runner.invoke(
            main,
            [
                "pkg",
                "prune",
                "myimage",
                "--owner",
                "myorg",
                "--type",
                "container",
                "--keep",
                "2",
            ],
        )

        assert result.exit_code == 0
        # Check for dry run indication (case varies by format)
        assert "dry" in result.output.lower() or "would" in result.output.lower()
        # Oldest versions should be listed for deletion
        assert "v1.0.0" in result.output
        assert "v1.1.0" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_prune_execute(runner: CliRunner):
    """Test pkg prune command with --execute flag."""
    import httpx
    import respx

    with respx.mock:
        # Versions returned in descending order (newest first)
        respx.get("https://test.example.com/api/packages/myorg/container/myimage").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 3,
                            "version": "v1.2.0",
                            "created_at": "2024-02-01T00:00:00Z",
                            "html_url": "",
                        },
                        {
                            "id": 2,
                            "version": "v1.1.0",
                            "created_at": "2024-01-15T00:00:00Z",
                            "html_url": "",
                        },
                        {
                            "id": 1,
                            "version": "v1.0.0",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )
        # Mock deletion of oldest version (v1.0.0, index 2 after keep 2)
        respx.delete(
            "https://test.example.com/api/packages/myorg/container/myimage/v1.0.0"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "pkg",
                "prune",
                "myimage",
                "--owner",
                "myorg",
                "--type",
                "container",
                "--keep",
                "2",
                "--execute",
            ],
        )

        assert result.exit_code == 0
        assert "Deleted" in result.output or "deleted" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_prune_pypi_blocked(runner: CliRunner):
    """Test pkg prune command blocks PyPI packages."""
    result = runner.invoke(
        main,
        [
            "pkg",
            "prune",
            "mypackage",
            "--owner",
            "myorg",
            "--type",
            "pypi",
            "--keep",
            "3",
            "--execute",
        ],
    )

    assert result.exit_code == 1
    assert "PyPI packages cannot be deleted" in result.output


@pytest.mark.usefixtures("mock_client")
def test_pkg_prune_nothing_to_delete(runner: CliRunner):
    """Test pkg prune command when no versions to delete."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/packages/myorg/container/myimage").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1,
                            "version": "v1.0.0",
                            "created_at": "2024-01-01T00:00:00Z",
                            "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        result = runner.invoke(
            main,
            [
                "pkg",
                "prune",
                "myimage",
                "--owner",
                "myorg",
                "--type",
                "container",
                "--keep",
                "5",  # Keep more than exist
            ],
        )

        assert result.exit_code == 0
        assert "Nothing to prune" in result.output or "nothing" in result.output.lower()


# --- OutputFormat package tests ---


def test_output_format_print_packages_table(capsys):
    """Test OutputFormat.print_packages table format."""
    pkg = SimpleNamespace(
        id=1,
        owner=SimpleNamespace(login="myorg"),
        name="mypackage",
        type="generic",
        version="1.0.0",
        created_at="2024-01-01T00:00:00Z",
    )
    output = OutputFormat("table")
    output.print_packages([pkg])

    captured = capsys.readouterr()
    assert "mypackage" in captured.out
    assert "generic" in captured.out
    assert "1.0.0" in captured.out


def test_output_format_print_packages_simple(capsys):
    """Test OutputFormat.print_packages simple format."""
    pkg = SimpleNamespace(
        id=1,
        owner=SimpleNamespace(login="myorg"),
        name="mypackage",
        type="pypi",
        version="0.1.0",
        created_at="2024-01-01T00:00:00Z",
    )
    output = OutputFormat("simple")
    output.print_packages([pkg])

    captured = capsys.readouterr()
    assert "mypackage" in captured.out


def test_output_format_print_packages_empty(capsys):
    """Test OutputFormat.print_packages with empty list."""
    output = OutputFormat("table")
    output.print_packages([])

    captured = capsys.readouterr()
    assert "No packages found" in captured.out


def test_output_format_print_packages_csv(capsys):
    """Test OutputFormat.print_packages CSV format."""
    pkg = SimpleNamespace(
        id=1,
        owner=SimpleNamespace(login="myorg"),
        name="mypackage",
        type="generic",
        version="1.0.0",
        created_at="2024-01-01T00:00:00Z",
    )
    output = OutputFormat("csv")
    output.print_packages([pkg])

    captured = capsys.readouterr()
    reader = csv.reader(io.StringIO(captured.out))
    rows = list(reader)
    assert rows[0] == ["name", "type", "version", "owner", "created_at"]
    assert rows[1][0] == "mypackage"
    assert rows[1][1] == "generic"


def test_output_format_print_package_versions_table(capsys):
    """Test OutputFormat.print_package_versions table format."""
    version = SimpleNamespace(
        id=1,
        version="1.0.0",
        created_at="2024-01-01T00:00:00Z",
        html_url="https://example.com/pkg/1.0.0",
    )
    output = OutputFormat("table")
    output.print_package_versions("mypackage", "generic", [version])

    captured = capsys.readouterr()
    assert "1.0.0" in captured.out
    assert "mypackage" in captured.out


def test_output_format_print_package_versions_empty(capsys):
    """Test OutputFormat.print_package_versions with empty list."""
    output = OutputFormat("table")
    output.print_package_versions("mypackage", "generic", [])

    captured = capsys.readouterr()
    assert "No versions found" in captured.out


def test_output_format_print_prune_preview(capsys):
    """Test OutputFormat.print_prune_preview."""
    to_delete = [
        SimpleNamespace(
            id=1, version="v1.0.0", created_at="2024-01-01T00:00:00Z", html_url=""
        ),
    ]
    to_keep = [
        SimpleNamespace(
            id=2, version="v1.1.0", created_at="2024-01-15T00:00:00Z", html_url=""
        ),
        SimpleNamespace(
            id=3, version="v1.2.0", created_at="2024-02-01T00:00:00Z", html_url=""
        ),
    ]
    output = OutputFormat("table")
    output.print_prune_preview(
        "myimage", "container", to_delete, to_keep, execute=False
    )

    captured = capsys.readouterr()
    # Version to delete should be shown
    assert "v1.0.0" in captured.out
    # Indicates dry run mode
    assert "dry" in captured.out.lower() or "Dry" in captured.out


# --- Workflow Command Tests ---


def test_workflow_help(runner: CliRunner):
    """Test workflow subcommand help."""
    result = runner.invoke(main, ["workflow", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "get" in result.output
    assert "dispatch" in result.output
    assert "enable" in result.output
    assert "disable" in result.output


def test_workflow_list_help(runner: CliRunner):
    """Test workflow list help."""
    result = runner.invoke(main, ["workflow", "list", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output


def test_workflow_get_help(runner: CliRunner):
    """Test workflow get help."""
    result = runner.invoke(main, ["workflow", "get", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "WORKFLOW_ID" in result.output


def test_workflow_dispatch_help(runner: CliRunner):
    """Test workflow dispatch help."""
    result = runner.invoke(main, ["workflow", "dispatch", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--ref" in result.output
    assert "--input" in result.output
    assert "WORKFLOW_ID" in result.output


def test_workflow_enable_help(runner: CliRunner):
    """Test workflow enable help."""
    result = runner.invoke(main, ["workflow", "enable", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "WORKFLOW_ID" in result.output


def test_workflow_disable_help(runner: CliRunner):
    """Test workflow disable help."""
    result = runner.invoke(main, ["workflow", "disable", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "WORKFLOW_ID" in result.output


# --- parse_workflow_inputs Tests ---


def test_parse_workflow_inputs_valid():
    """Test parsing valid workflow inputs."""
    from teax.cli import parse_workflow_inputs

    result = parse_workflow_inputs(("version=1.0.0", "env=production"))
    assert result == {"version": "1.0.0", "env": "production"}


def test_parse_workflow_inputs_empty():
    """Test parsing empty workflow inputs."""
    from teax.cli import parse_workflow_inputs

    result = parse_workflow_inputs(())
    assert result == {}


def test_parse_workflow_inputs_equals_in_value():
    """Test parsing inputs where value contains equals sign."""
    from teax.cli import parse_workflow_inputs

    result = parse_workflow_inputs(("config=key=value",))
    assert result == {"config": "key=value"}


def test_parse_workflow_inputs_empty_value():
    """Test parsing inputs with empty value."""
    from teax.cli import parse_workflow_inputs

    result = parse_workflow_inputs(("empty=",))
    assert result == {"empty": ""}


def test_parse_workflow_inputs_invalid_format():
    """Test error on invalid input format (no equals)."""
    from click import BadParameter

    from teax.cli import parse_workflow_inputs

    with pytest.raises(BadParameter, match="Invalid input format"):
        parse_workflow_inputs(("invalid",))


def test_parse_workflow_inputs_empty_key():
    """Test error on empty key."""
    from click import BadParameter

    from teax.cli import parse_workflow_inputs

    with pytest.raises(BadParameter, match="Input key cannot be empty"):
        parse_workflow_inputs(("=value",))


def test_parse_workflow_inputs_key_whitespace_stripped():
    """Test that key whitespace is stripped."""
    from teax.cli import parse_workflow_inputs

    result = parse_workflow_inputs(("  key  =value",))
    assert result == {"key": "value"}


# --- validate_workflow_id Tests ---


def test_validate_workflow_id_valid():
    """Test validation of valid workflow IDs."""
    from teax.cli import validate_workflow_id

    assert validate_workflow_id("ci.yml") == "ci.yml"
    assert validate_workflow_id("  ci.yml  ") == "ci.yml"  # Strips whitespace
    assert validate_workflow_id("123") == "123"


def test_validate_workflow_id_empty():
    """Test error on empty workflow_id."""
    from click import BadParameter

    from teax.cli import validate_workflow_id

    with pytest.raises(BadParameter, match="Workflow ID cannot be empty"):
        validate_workflow_id("")


def test_validate_workflow_id_whitespace_only():
    """Test error on whitespace-only workflow_id."""
    from click import BadParameter

    from teax.cli import validate_workflow_id

    with pytest.raises(BadParameter, match="Workflow ID cannot be empty"):
        validate_workflow_id("   ")


# --- Workflow OutputFormat Tests ---


def test_output_format_workflows_simple(capsys):
    """Test simple output format for workflows."""
    formatter = OutputFormat("simple")
    mock_workflow = SimpleNamespace(
        id="ci.yml",
        name="CI Pipeline",
        path=".gitea/workflows/ci.yml",
        state="active",
        created_at="2024-01-15T10:00:00Z",
        updated_at="2024-01-16T10:00:00Z",
    )
    formatter.print_workflows([mock_workflow])
    captured = capsys.readouterr()
    assert "ci.yml" in captured.out
    assert "CI Pipeline" in captured.out


def test_output_format_workflows_json(capsys):
    """Test JSON output format for workflows."""
    import json

    formatter = OutputFormat("json")
    mock_workflow = SimpleNamespace(
        id="ci.yml",
        name="CI Pipeline",
        path=".gitea/workflows/ci.yml",
        state="active",
        created_at="2024-01-15T10:00:00Z",
        updated_at="2024-01-16T10:00:00Z",
    )
    formatter.print_workflows([mock_workflow])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert len(parsed) == 1
    assert parsed[0]["id"] == "ci.yml"
    assert parsed[0]["name"] == "CI Pipeline"
    assert parsed[0]["state"] == "active"


def test_output_format_workflows_json_null_timestamps(capsys):
    """Test JSON output format emits null for missing timestamps."""
    import json

    formatter = OutputFormat("json")
    mock_workflow = SimpleNamespace(
        id="ci.yml",
        name="CI Pipeline",
        path=".gitea/workflows/ci.yml",
        state="active",
        created_at=None,  # Missing timestamp
        updated_at=None,  # Missing timestamp
    )
    formatter.print_workflows([mock_workflow])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert len(parsed) == 1
    assert parsed[0]["created_at"] is None
    assert parsed[0]["updated_at"] is None


def test_output_format_workflows_csv(capsys):
    """Test CSV output format for workflows."""
    formatter = OutputFormat("csv")
    mock_workflow = SimpleNamespace(
        id="ci.yml",
        name="CI Pipeline",
        path=".gitea/workflows/ci.yml",
        state="active",
        created_at="2024-01-15T10:00:00Z",
        updated_at="2024-01-16T10:00:00Z",
    )
    formatter.print_workflows([mock_workflow])
    captured = capsys.readouterr()
    reader = csv.reader(io.StringIO(captured.out))
    rows = list(reader)
    assert rows[0] == ["id", "name", "path", "state"]
    assert rows[1] == ["ci.yml", "CI Pipeline", ".gitea/workflows/ci.yml", "active"]


def test_output_format_workflows_table_empty(capsys, monkeypatch):
    """Test table output format for empty workflows."""
    from io import StringIO

    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    formatter = OutputFormat("table")
    formatter.print_workflows([])
    output = buffer.getvalue()
    assert "no workflows found" in output.lower()


def test_output_format_workflows_table_with_data(capsys, monkeypatch):
    """Test table output format for workflows with data."""
    from io import StringIO

    from rich.console import Console

    from teax import cli

    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False))

    formatter = OutputFormat("table")
    mock_workflow = SimpleNamespace(
        id="ci.yml",
        name="CI Pipeline",
        path=".gitea/workflows/ci.yml",
        state="active",
        created_at="2024-01-15T10:00:00Z",
        updated_at="2024-01-16T10:00:00Z",
    )
    formatter.print_workflows([mock_workflow])
    output = buffer.getvalue()
    assert "ci.yml" in output
    assert "CI Pipeline" in output
    assert "active" in output


# --- Workflow CLI Integration Tests ---


@pytest.mark.usefixtures("mock_client")
def test_workflow_list_command(runner: CliRunner):
    """Test workflow list command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflows": [
                        {
                            "id": "ci.yml",
                            "name": "CI Pipeline",
                            "path": ".gitea/workflows/ci.yml",
                            "state": "active",
                            "created_at": "2024-01-15T10:00:00Z",
                            "updated_at": "2024-01-16T10:00:00Z",
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["workflow", "list", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "ci.yml" in result.output
        assert "CI Pipeline" in result.output
        assert route.called
        # Verify pagination params were sent
        assert route.calls.last.request.url.params["page"] == "1"
        assert route.calls.last.request.url.params["limit"] == "50"


@pytest.mark.usefixtures("mock_client")
def test_workflow_get_command(runner: CliRunner):
    """Test workflow get command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "ci.yml",
                    "name": "CI Pipeline",
                    "path": ".gitea/workflows/ci.yml",
                    "state": "active",
                    "created_at": "2024-01-15T10:00:00Z",
                    "updated_at": "2024-01-16T10:00:00Z",
                },
            )
        )

        result = runner.invoke(
            main, ["workflow", "get", "ci.yml", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "ci.yml" in result.output
        assert "CI Pipeline" in result.output
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_workflow_dispatch_command(runner: CliRunner):
    """Test workflow dispatch command."""
    import json

    import httpx
    import respx

    with respx.mock:
        route = respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/dispatches"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "workflow",
                "dispatch",
                "ci.yml",
                "--repo",
                "owner/repo",
                "--ref",
                "main",
            ],
        )

        assert result.exit_code == 0
        assert "Dispatched" in result.output or "dispatched" in result.output
        assert route.called
        # Verify request body
        request_body = json.loads(route.calls.last.request.content)
        assert request_body["ref"] == "main"


@pytest.mark.usefixtures("mock_client")
def test_workflow_dispatch_with_inputs(runner: CliRunner):
    """Test workflow dispatch command with inputs."""
    import json

    import httpx
    import respx

    with respx.mock:
        route = respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/deploy.yml/dispatches"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "workflow",
                "dispatch",
                "deploy.yml",
                "--repo",
                "owner/repo",
                "--ref",
                "v1.0.0",
                "-i",
                "version=1.0.0",
                "-i",
                "env=production",
            ],
        )

        assert result.exit_code == 0
        assert route.called
        # Verify request body includes inputs
        request_body = json.loads(route.calls.last.request.content)
        assert request_body["ref"] == "v1.0.0"
        assert request_body["inputs"]["version"] == "1.0.0"
        assert request_body["inputs"]["env"] == "production"


@pytest.mark.usefixtures("mock_client")
def test_workflow_dispatch_empty_ref_rejected(runner: CliRunner):
    """Test workflow dispatch rejects empty ref."""
    result = runner.invoke(
        main,
        [
            "workflow",
            "dispatch",
            "ci.yml",
            "--repo",
            "owner/repo",
            "--ref",
            "   ",  # Whitespace-only ref
        ],
    )

    assert result.exit_code != 0
    assert "empty" in result.output.lower() or "whitespace" in result.output.lower()


@pytest.mark.usefixtures("mock_client")
def test_workflow_enable_command(runner: CliRunner):
    """Test workflow enable command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.put(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/enable"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main, ["workflow", "enable", "ci.yml", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "enabled" in result.output.lower()
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_workflow_disable_command(runner: CliRunner):
    """Test workflow disable command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.put(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/disable"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main, ["workflow", "disable", "ci.yml", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_workflow_list_error_handling(runner: CliRunner):
    """Test workflow list error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows"
        ).mock(return_value=httpx.Response(404, json={"message": "Not found"}))

        result = runner.invoke(main, ["workflow", "list", "--repo", "owner/repo"])

        assert result.exit_code != 0
        assert "Error" in result.output


@pytest.mark.usefixtures("mock_client")
def test_workflow_get_empty_workflow_id_rejected(runner: CliRunner):
    """Test workflow get rejects whitespace-only workflow_id."""
    result = runner.invoke(
        main,
        ["workflow", "get", "   ", "--repo", "owner/repo"],
    )

    assert result.exit_code != 0
    assert "empty" in result.output.lower() or "whitespace" in result.output.lower()


@pytest.mark.usefixtures("mock_client")
def test_workflow_dispatch_json_output(runner: CliRunner):
    """Test workflow dispatch with JSON output format."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/dispatches"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "-o",
                "json",
                "workflow",
                "dispatch",
                "ci.yml",
                "--repo",
                "owner/repo",
                "--ref",
                "main",
                "-i",
                "key=value",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["action"] == "dispatched"
        assert output["workflow"] == "ci.yml"
        assert output["ref"] == "main"
        assert output["inputs"]["key"] == "value"


@pytest.mark.usefixtures("mock_client")
def test_workflow_dispatch_json_sanitizes_escape_sequences(runner: CliRunner):
    """Test that workflow dispatch JSON output sanitizes terminal escape sequences."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/dispatches"
        ).mock(return_value=httpx.Response(204))

        # Input with escape sequences that could be terminal injection
        result = runner.invoke(
            main,
            [
                "-o",
                "json",
                "workflow",
                "dispatch",
                "ci.yml",
                "--repo",
                "owner/repo",
                "--ref",
                "main",
                "-i",
                "evil\x1b[31mkey=malicious\x1b[0mvalue",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.output)
        # Verify escape sequences are stripped from both key and value
        assert "\x1b" not in result.output
        for key, value in output["inputs"].items():
            assert "\x1b" not in key
            assert "\x1b" not in value


# --- Runs Command Help Tests ---


def test_runs_help(runner: CliRunner):
    """Test runs subcommand help."""
    result = runner.invoke(main, ["runs", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output
    assert "list" in result.output
    assert "get" in result.output
    assert "jobs" in result.output
    assert "logs" in result.output
    assert "rerun" in result.output
    assert "delete" in result.output


def test_runs_status_help(runner: CliRunner):
    """Test runs status help."""
    result = runner.invoke(main, ["runs", "status", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output


def test_runs_list_help(runner: CliRunner):
    """Test runs list help."""
    result = runner.invoke(main, ["runs", "list", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--workflow" in result.output
    assert "--branch" in result.output
    assert "--status" in result.output
    assert "--limit" in result.output


def test_runs_get_help(runner: CliRunner):
    """Test runs get help."""
    result = runner.invoke(main, ["runs", "get", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--errors-only" in result.output
    assert "RUN_REF" in result.output


def test_runs_jobs_help(runner: CliRunner):
    """Test runs jobs help."""
    result = runner.invoke(main, ["runs", "jobs", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--errors-only" in result.output
    assert "RUN_REF" in result.output


def test_runs_logs_help(runner: CliRunner):
    """Test runs logs help."""
    result = runner.invoke(main, ["runs", "logs", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--tail" in result.output
    assert "--head" in result.output
    assert "--grep" in result.output
    assert "--context" in result.output
    assert "--strip-ansi" in result.output
    assert "--raw" in result.output
    assert "JOB_ID" in result.output


def test_runs_rerun_help(runner: CliRunner):
    """Test runs rerun help."""
    result = runner.invoke(main, ["runs", "rerun", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "RUN_REF" in result.output


def test_runs_delete_help(runner: CliRunner):
    """Test runs delete help."""
    result = runner.invoke(main, ["runs", "delete", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--yes" in result.output
    assert "RUN_REF" in result.output


# --- Package Linking Help Tests ---


def test_pkg_link_help(runner: CliRunner):
    """Test pkg link help."""
    result = runner.invoke(main, ["pkg", "link", "--help"])
    assert result.exit_code == 0
    assert "--owner" in result.output
    assert "--type" in result.output
    assert "--repo" in result.output
    assert "NAME" in result.output


def test_pkg_unlink_help(runner: CliRunner):
    """Test pkg unlink help."""
    result = runner.invoke(main, ["pkg", "unlink", "--help"])
    assert result.exit_code == 0
    assert "--owner" in result.output
    assert "--type" in result.output
    assert "NAME" in result.output


def test_pkg_latest_help(runner: CliRunner):
    """Test pkg latest help."""
    result = runner.invoke(main, ["pkg", "latest", "--help"])
    assert result.exit_code == 0
    assert "--owner" in result.output
    assert "--type" in result.output
    assert "NAME" in result.output


# --- filter_logs Tests ---


def test_filter_logs_no_filters():
    """Test filter_logs with no filters returns original content."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nLine 3"
    result = filter_logs(logs)
    assert result == logs


def test_filter_logs_tail():
    """Test filter_logs tail option."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    result = filter_logs(logs, tail=2)
    assert result == "Line 4\nLine 5"


def test_filter_logs_head():
    """Test filter_logs head option."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    result = filter_logs(logs, head=2)
    assert result == "Line 1\nLine 2"


def test_filter_logs_grep():
    """Test filter_logs grep option."""
    from teax.cli import filter_logs

    logs = "Info: Starting\nError: Failed\nInfo: Done\nError: Retry"
    result = filter_logs(logs, grep="Error")
    assert "Error: Failed" in result
    assert "Error: Retry" in result
    assert "Info: Starting" not in result


def test_filter_logs_grep_with_context():
    """Test filter_logs grep with context lines."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nError: Failed\nLine 4\nLine 5"
    result = filter_logs(logs, grep="Error", context=1)
    assert "Line 2" in result
    assert "Error: Failed" in result
    assert "Line 4" in result
    assert "Line 1" not in result
    assert "Line 5" not in result


def test_filter_logs_strip_ansi():
    """Test filter_logs strip_ansi option."""
    from teax.cli import filter_logs

    logs = "\x1b[31mRed Text\x1b[0m\n\x1b[32mGreen Text\x1b[0m"
    result = filter_logs(logs, strip_ansi=True)
    assert "\x1b" not in result
    assert "Red Text" in result
    assert "Green Text" in result


def test_filter_logs_combined():
    """Test filter_logs with combined options."""
    from teax.cli import filter_logs

    logs = "\x1b[31mError 1\x1b[0m\nInfo\n\x1b[31mError 2\x1b[0m\nDebug"
    result = filter_logs(logs, grep="Error", strip_ansi=True)
    assert result == "Error 1\nError 2"


def test_filter_logs_invalid_regex():
    """Test filter_logs raises BadParameter on invalid regex."""
    from click import BadParameter

    from teax.cli import filter_logs

    with pytest.raises(BadParameter, match="Invalid regex"):
        filter_logs("some logs", grep="[invalid(regex")


def test_filter_logs_negative_context_normalized():
    """Test filter_logs treats negative context as 0."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nError\nLine 4\nLine 5"
    # Negative context should be normalized to 0
    result = filter_logs(logs, grep="Error", context=-5)
    assert result == "Error"


def test_filter_logs_head_zero():
    """Test filter_logs with head=0 is treated as no limit."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nLine 3"
    result = filter_logs(logs, head=0)
    # head=0 is treated as "no head limit" (not applied)
    assert result == logs


def test_filter_logs_tail_zero():
    """Test filter_logs with tail=0 is treated as no limit."""
    from teax.cli import filter_logs

    logs = "Line 1\nLine 2\nLine 3"
    result = filter_logs(logs, tail=0)
    # tail=0 is treated as "no tail limit" (not applied)
    assert result == logs


def test_filter_logs_strip_ansi_removes_osc():
    """Test strip_ansi removes OSC escape sequences (hyperlinks, etc.)."""
    from teax.cli import filter_logs

    # OSC-8 hyperlink
    logs = "\x1b]8;;https://evil.com\x07click here\x1b]8;;\x07"
    result = filter_logs(logs, strip_ansi=True)
    assert "\x1b" not in result
    assert "click here" in result


def test_filter_logs_strip_ansi_removes_control_chars():
    """Test strip_ansi removes dangerous control characters."""
    from teax.cli import filter_logs

    # Standalone CR (line rewrite attack), null bytes, backspaces
    logs = "Real output\rFake\x00Null\x08Back"
    result = filter_logs(logs, strip_ansi=True)
    assert "\r" not in result or "\r\n" in result  # CRLF allowed
    assert "\x00" not in result
    assert "\x08" not in result


# --- Runs OutputFormat Tests ---


def test_output_format_runs_simple(capsys):
    """Test simple output format for runs."""
    formatter = OutputFormat("simple")
    mock_run = SimpleNamespace(
        id=42,
        run_number=15,
        status="completed",
        conclusion="success",
        head_sha="abc12345def67890",
        head_branch="main",
        event="push",
        display_title="CI Run",
        path=".gitea/workflows/ci.yml",
        started_at="2024-01-15T10:00:00Z",
        html_url="https://example.com/runs/42",
    )
    formatter.print_runs([mock_run])
    captured = capsys.readouterr()
    assert "42" in captured.out  # ID, not run_number
    assert "success" in captured.out
    assert "abc12345" in captured.out
    assert "main" in captured.out


def test_output_format_runs_json(capsys):
    """Test JSON output format for runs."""
    import json

    formatter = OutputFormat("json")
    mock_run = SimpleNamespace(
        id=42,
        run_number=15,
        status="completed",
        conclusion="success",
        head_sha="abc12345def67890",
        head_branch="main",
        event="push",
        display_title="CI Run",
        path=".gitea/workflows/ci.yml",
        started_at="2024-01-15T10:00:00Z",
        html_url="https://example.com/runs/42",
    )
    formatter.print_runs([mock_run])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert len(parsed) == 1
    assert parsed[0]["id"] == 42
    assert parsed[0]["run_number"] == 15
    assert parsed[0]["conclusion"] == "success"


def test_output_format_run_status_simple(capsys):
    """Test simple output format for run status."""
    formatter = OutputFormat("simple")
    mock_run = SimpleNamespace(
        id=42,
        run_number=15,
        status="completed",
        conclusion="success",
        head_sha="abc12345def67890",
        head_branch="main",
        event="push",
        path=".gitea/workflows/ci.yml",
        started_at="2024-01-15T10:00:00Z",
    )
    formatter.print_run_status([mock_run])
    captured = capsys.readouterr()
    assert "ci.yml" in captured.out
    assert "✓" in captured.out
    assert "success" in captured.out
    assert "#15" in captured.out


def test_output_format_jobs_simple(capsys):
    """Test simple output format for jobs."""
    formatter = OutputFormat("simple")
    mock_step = SimpleNamespace(
        number=1,
        name="Setup",
        status="completed",
        conclusion="success",
        started_at="2024-01-15T10:00:00Z",
        completed_at="2024-01-15T10:00:30Z",
    )
    mock_job = SimpleNamespace(
        id=123,
        run_id=42,
        name="build",
        status="completed",
        conclusion="success",
        started_at="2024-01-15T10:00:00Z",
        completed_at="2024-01-15T10:01:00Z",
        runner_name="runner-1",
        steps=[mock_step],
    )
    formatter.print_jobs([mock_job])
    captured = capsys.readouterr()
    assert "build" in captured.out
    assert "✓" in captured.out


def test_output_format_jobs_json(capsys):
    """Test JSON output format for jobs."""
    import json

    formatter = OutputFormat("json")
    mock_step = SimpleNamespace(
        number=1,
        name="Setup",
        status="completed",
        conclusion="success",
    )
    mock_job = SimpleNamespace(
        id=123,
        run_id=42,
        name="build",
        status="completed",
        conclusion="success",
        started_at="2024-01-15T10:00:00Z",
        completed_at="2024-01-15T10:01:00Z",
        runner_name="runner-1",
        steps=[mock_step],
    )
    formatter.print_jobs([mock_job])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert len(parsed) == 1
    assert parsed[0]["id"] == 123
    assert parsed[0]["name"] == "build"
    assert len(parsed[0]["steps"]) == 1
    assert parsed[0]["steps"][0]["name"] == "Setup"


def test_output_format_jobs_errors_only(capsys):
    """Test jobs output with errors_only filter."""
    formatter = OutputFormat("simple")
    mock_step = SimpleNamespace(
        number=1,
        name="Setup",
        status="completed",
        conclusion="failure",
    )
    success_job = SimpleNamespace(
        id=123,
        name="build",
        status="completed",
        conclusion="success",
        steps=[],
    )
    failed_job = SimpleNamespace(
        id=124,
        name="test",
        status="completed",
        conclusion="failure",
        steps=[mock_step],
    )
    formatter.print_jobs([success_job, failed_job], errors_only=True)
    captured = capsys.readouterr()
    assert "test" in captured.out
    assert "build" not in captured.out


# --- Runs CLI Integration Tests ---


@pytest.mark.usefixtures("mock_client")
def test_runs_status_command(runner: CliRunner):
    """Test runs status command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345def67890",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI Run",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "2024-01-15T10:00:00Z",
                            "completed_at": "2024-01-15T10:05:00Z",
                            "html_url": "https://example.com/runs/42",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "status", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "ci.yml" in result.output
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_status_with_sha_filter(runner: CliRunner):
    """Test runs status command with --sha filter."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345def67890",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI Run",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "2024-01-15T10:00:00Z",
                            "completed_at": "2024-01-15T10:05:00Z",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                        {
                            "id": 41,
                            "run_number": 14,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "different123sha",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "Deploy Run",
                            "path": ".gitea/workflows/deploy.yml",
                            "started_at": "2024-01-14T10:00:00Z",
                            "completed_at": "2024-01-14T10:05:00Z",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Filter by SHA should only return matching runs
        result = runner.invoke(
            main, ["runs", "status", "--repo", "owner/repo", "--sha", "abc123"]
        )

        # Should succeed (only matching SHA has success status)
        assert result.exit_code == 0
        # Should show matching SHA
        assert "abc12345" in result.output
        # Should NOT show the non-matching run's SHA
        assert "different123" not in result.output
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_status_tmux_format(runner: CliRunner):
    """Test runs status command with tmux output format."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                        {
                            "id": 43,
                            "run_number": 16,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "Build",
                            "path": ".gitea/workflows/build.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "tmux", "runs", "status", "--repo", "owner/repo"]
        )

        # Exit code 1 because one workflow failed
        assert result.exit_code == 1
        # tmux format uses abbreviations like C:✓ B:✗
        assert "✓" in result.output or "✗" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_tmux_spinner_for_running(runner: CliRunner):
    """Test runs status tmux shows animated spinner for in-progress workflows."""
    import httpx
    import respx

    from teax.cli import SPINNER_FRAMES

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "in_progress",  # Running workflow
                            "conclusion": None,
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "tmux", "runs", "status", "--repo", "owner/repo"]
        )

        # Exit code 2 for running
        assert result.exit_code == 2
        # Should contain one of the spinner frames
        assert any(frame in result.output for frame in SPINNER_FRAMES)


@pytest.mark.usefixtures("mock_client")
def test_runs_status_exit_code_failure(runner: CliRunner):
    """Test runs status returns exit code 1 on failure."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "status", "--repo", "owner/repo"])

        assert result.exit_code == 1


@pytest.mark.usefixtures("mock_client")
def test_runs_status_exit_code_running(runner: CliRunner):
    """Test runs status returns exit code 2 when running."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "in_progress",
                            "conclusion": None,
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "status", "--repo", "owner/repo"])

        assert result.exit_code == 2


@pytest.mark.usefixtures("mock_client")
def test_runs_status_exit_code_no_runs(runner: CliRunner):
    """Test runs status returns exit code 3 when no runs found."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={"workflow_runs": []},
            )
        )

        result = runner.invoke(main, ["runs", "status", "--repo", "owner/repo"])

        assert result.exit_code == 3


@pytest.mark.usefixtures("mock_client")
def test_runs_status_json_includes_overall(runner: CliRunner):
    """Test runs status JSON output includes overall_status."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "runs", "status", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert "overall_status" in data
        assert data["overall_status"] == "success"
        assert "workflows" in data


@pytest.mark.usefixtures("mock_client")
def test_runs_status_tmux_sanitization(runner: CliRunner):
    """Test runs status tmux format sanitizes workflow names with control chars."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            # Workflow name with ANSI escape sequence (malicious)
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "Evil",
                            "path": ".gitea/workflows/\x1b[31mevil.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                        {
                            "id": 43,
                            "run_number": 16,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            # Workflow name starting with non-alphanumeric char
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "Test",
                            "path": ".gitea/workflows/_private-test.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "tmux", "runs", "status", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        # Should NOT contain escape sequences
        assert "\x1b" not in result.output
        # First workflow: ANSI stripped, 'E' from 'evil' used (fallback first char)
        assert "E:✓" in result.output
        # Second workflow: contains 'test' pattern, so use 'T'
        assert "T:✓" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_sha_head_resolution(runner: CliRunner, monkeypatch):
    """Test runs status with --sha HEAD resolves git HEAD."""
    import subprocess

    import httpx
    import respx

    # Mock subprocess.run to return a fake SHA
    original_run = subprocess.run

    def mock_subprocess_run(args, **kwargs):
        if args == ["git", "rev-parse", "HEAD"]:
            # Return a mock CompletedProcess
            result = subprocess.CompletedProcess(
                args=args, returncode=0, stdout="abc12345def67890abcd\n", stderr=""
            )
            return result
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345def6",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["runs", "status", "--repo", "owner/repo", "--sha", "HEAD"]
        )

        assert result.exit_code == 0
        # Should show the SHA (truncated to 8 chars in display)
        assert "abc12345" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_list_command(runner: CliRunner):
    """Test runs list command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345def67890",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI Run",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "2024-01-15T10:00:00Z",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "list", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_list_with_filters(runner: CliRunner):
    """Test runs list command with filters."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={"workflow_runs": []},
            )
        )

        result = runner.invoke(
            main,
            [
                "runs",
                "list",
                "--repo",
                "owner/repo",
                "--workflow",
                "ci.yml",
                "--branch",
                "main",
                "--status",
                "failure",
                "--limit",
                "5",
            ],
        )

        assert result.exit_code == 0
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_get_command(runner: CliRunner):
    """Test runs get command (shows jobs for a run)."""
    import httpx
    import respx

    with respx.mock:
        # Use run_id >= 10000 to skip run_number resolution
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42000/jobs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 123,
                            "run_id": 42000,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "2024-01-15T10:00:00Z",
                            "completed_at": "2024-01-15T10:05:00Z",
                            "created_at": "",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "runner_id": 1,
                            "runner_name": "runner-1",
                            "labels": [],
                            "steps": [],
                            "html_url": "",
                            "run_url": "",
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "get", "42000", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_jobs_command(runner: CliRunner):
    """Test runs jobs command."""
    import httpx
    import respx

    with respx.mock:
        # Use run_id >= 10000 to skip run_number resolution
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42000/jobs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 123,
                            "run_id": 42000,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "",
                            "completed_at": "",
                            "created_at": "",
                            "head_sha": "",
                            "head_branch": "",
                            "runner_id": None,
                            "runner_name": None,
                            "labels": [],
                            "steps": [],
                            "html_url": "",
                            "run_url": "",
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "jobs", "42000", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_command(runner: CliRunner):
    """Test runs logs command."""
    import httpx
    import respx

    with respx.mock:
        route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                text="Step 1: Starting\nStep 2: Building\nStep 3: Done\n",
            )
        )

        result = runner.invoke(main, ["runs", "logs", "123", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "Step 1" in result.output
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_with_tail(runner: CliRunner):
    """Test runs logs command with tail option."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(
            return_value=httpx.Response(
                200,
                text="Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n",
            )
        )

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--tail", "2"],
        )

        assert result.exit_code == 0
        assert "Line 4" in result.output
        assert "Line 5" in result.output
        assert "Line 1" not in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_with_grep(runner: CliRunner):
    """Test runs logs command with grep option."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(
            return_value=httpx.Response(
                200,
                text="Info: Starting\nError: Failed\nInfo: Retry\nError: Again\n",
            )
        )

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--grep", "Error"],
        )

        assert result.exit_code == 0
        assert "Error: Failed" in result.output
        assert "Error: Again" in result.output
        assert "Info: Starting" not in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_with_head(runner: CliRunner):
    """Test runs logs command with head option."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(
            return_value=httpx.Response(
                200,
                text="Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n",
            )
        )

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--head", "2"],
        )

        assert result.exit_code == 0
        assert "Line 1" in result.output
        assert "Line 2" in result.output
        assert "Line 3" not in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_sanitizes_escape_sequences(runner: CliRunner):
    """Test runs logs sanitizes dangerous escape sequences by default."""
    import httpx
    import respx

    with respx.mock:
        # Mock response with dangerous escape sequences (OSC hyperlink)
        evil_logs = "\x1b]8;;https://evil.com\x07click\x1b]8;;\x07 plain text"
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(return_value=httpx.Response(200, text=evil_logs))

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo"],
        )

        assert result.exit_code == 0
        # Dangerous sequences should be stripped
        assert "\x1b" not in result.output
        assert "plain text" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_flag_accepted(runner: CliRunner):
    """Test runs logs --raw flag outputs exact server content."""
    import httpx
    import respx

    with respx.mock:
        # Include trailing newline to verify it's preserved
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(return_value=httpx.Response(200, text="plain log output\n"))

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--raw"],
        )

        assert result.exit_code == 0
        assert "plain log output" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_mutually_exclusive_with_filters(runner: CliRunner):
    """Test runs logs --raw cannot be used with filtering options."""
    result = runner.invoke(
        main,
        ["runs", "logs", "123", "--repo", "owner/repo", "--raw", "--tail", "10"],
    )

    assert result.exit_code != 0
    assert "cannot be used with" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_mutually_exclusive_with_strip_ansi(runner: CliRunner):
    """Test runs logs --raw cannot be used with --strip-ansi."""
    result = runner.invoke(
        main,
        ["runs", "logs", "123", "--repo", "owner/repo", "--raw", "--strip-ansi"],
    )

    assert result.exit_code != 0
    assert "cannot be used with" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_mutually_exclusive_with_context(runner: CliRunner):
    """Test runs logs --raw cannot be used with --context."""
    result = runner.invoke(
        main,
        ["runs", "logs", "123", "--repo", "owner/repo", "--raw", "--context", "5"],
    )

    assert result.exit_code != 0
    assert "cannot be used with" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_mutually_exclusive_with_head_zero(runner: CliRunner):
    """Test runs logs --raw rejects --head 0 (explicit None check)."""
    result = runner.invoke(
        main,
        ["runs", "logs", "123", "--repo", "owner/repo", "--raw", "--head", "0"],
    )

    assert result.exit_code != 0
    assert "cannot be used with" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_mutually_exclusive_with_tail_zero(runner: CliRunner):
    """Test runs logs --raw rejects --tail 0 (explicit None check)."""
    result = runner.invoke(
        main,
        ["runs", "logs", "123", "--repo", "owner/repo", "--raw", "--tail", "0"],
    )

    assert result.exit_code != 0
    assert "cannot be used with" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_raw_preserves_escape_sequences(runner: CliRunner):
    """Test runs logs --raw preserves ANSI escape sequences."""
    import httpx
    import respx

    with respx.mock:
        # Logs with escape sequences that would be stripped without --raw
        logs_with_escapes = "\x1b[31mRed\x1b[0m \x1b]8;;url\x07link\x1b]8;;\x07 done"
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(return_value=httpx.Response(200, text=logs_with_escapes))

        # Use color=True to prevent CliRunner from stripping SGR codes
        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--raw"],
            color=True,
        )

        assert result.exit_code == 0
        # --raw should preserve escape sequences (not sanitize them)
        assert "\x1b[31m" in result.output
        assert "\x1b]8;;" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_strip_ansi(runner: CliRunner):
    """Test runs logs --strip-ansi removes all escape sequences."""
    import httpx
    import respx

    with respx.mock:
        colored_logs = "\x1b[31mRed\x1b[0m text\x1b]8;;url\x07link\x1b]8;;\x07"
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(return_value=httpx.Response(200, text=colored_logs))

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--strip-ansi"],
        )

        assert result.exit_code == 0
        assert "\x1b" not in result.output
        assert "Red" in result.output
        assert "text" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_logs_invalid_grep_pattern(runner: CliRunner):
    """Test runs logs with invalid grep pattern shows error."""
    import httpx
    import respx

    with respx.mock:
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/jobs/123/logs"
        ).mock(return_value=httpx.Response(200, text="some logs"))

        result = runner.invoke(
            main,
            ["runs", "logs", "123", "--repo", "owner/repo", "--grep", "[invalid("],
        )

        assert result.exit_code != 0
        assert "Invalid regex" in result.output or "Error" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_rerun_command(runner: CliRunner):
    """Test runs rerun command."""
    import httpx
    import respx

    with respx.mock:
        # Use run_id >= 10000 to skip run_number resolution
        # Mock jobs endpoint (get_run uses this first to verify run exists)
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42000/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 123,
                            "run_id": 42000,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "failure",
                            "started_at": "",
                            "completed_at": "",
                            "created_at": "",
                            "head_sha": "",
                            "head_branch": "",
                            "runner_id": None,
                            "runner_name": None,
                            "labels": [],
                            "steps": [],
                            "html_url": "",
                            "run_url": "",
                        },
                    ]
                },
            )
        )

        # Mock list_runs (get_run fetches from here after jobs endpoint)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42000,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock dispatch
        dispatch_route = respx.post(
            "https://test.example.com/api/v1/repos/owner/repo/actions/workflows/ci.yml/dispatches"
        ).mock(return_value=httpx.Response(204))

        result = runner.invoke(main, ["runs", "rerun", "42000", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert dispatch_route.called
        assert "dispatched" in result.output.lower()


@pytest.mark.usefixtures("mock_client")
def test_runs_delete_command(runner: CliRunner):
    """Test runs delete command with -y flag."""
    import httpx
    import respx

    with respx.mock:
        # Use run_id >= 10000 to skip run_number resolution
        # Mock jobs endpoint (get_run uses this first to verify run exists)
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42000/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 123,
                            "run_id": 42000,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "",
                            "completed_at": "",
                            "created_at": "",
                            "head_sha": "",
                            "head_branch": "",
                            "runner_id": None,
                            "runner_name": None,
                            "labels": [],
                            "steps": [],
                            "html_url": "",
                            "run_url": "",
                        },
                    ]
                },
            )
        )

        # Mock list_runs (get_run fetches from here after jobs endpoint)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42000,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock delete endpoint
        route = respx.delete(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42000"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main, ["runs", "delete", "42000", "--repo", "owner/repo", "-y"]
        )

        assert result.exit_code == 0
        assert route.called
        assert "deleted" in result.output.lower()


@pytest.mark.usefixtures("mock_client")
def test_runs_delete_cancelled_without_confirm(runner: CliRunner):
    """Test runs delete command cancelled without confirmation."""
    import httpx
    import respx

    with respx.mock:
        # Mock jobs endpoint (get_run uses this first)
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42000/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 123,
                            "run_id": 42000,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "",
                            "completed_at": "",
                            "created_at": "",
                            "head_sha": "",
                            "head_branch": "",
                            "runner_id": None,
                            "runner_name": None,
                            "labels": [],
                            "steps": [],
                            "html_url": "",
                            "run_url": "",
                        },
                    ]
                },
            )
        )

        # Mock list_runs (get_run fetches from here after jobs endpoint)
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42000,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            ["runs", "delete", "42000", "--repo", "owner/repo"],
            input="n\n",
        )

        assert result.exit_code == 0
        assert "Cancelled" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_list_error_handling(runner: CliRunner):
    """Test runs list error handling."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        result = runner.invoke(main, ["runs", "list", "--repo", "owner/repo"])

        assert result.exit_code != 0
        assert "Error" in result.output


# --- Package Linking CLI Integration Tests ---


@pytest.mark.usefixtures("mock_client")
def test_pkg_link_command(runner: CliRunner):
    """Test pkg link command."""
    import httpx
    import respx

    with respx.mock:
        # Package API uses /api/packages/ not /api/v1/packages/
        route = respx.post(
            "https://test.example.com/api/packages/homelab/container/myimage/-/link/myproject"
        )
        route.mock(return_value=httpx.Response(201))

        result = runner.invoke(
            main,
            [
                "pkg",
                "link",
                "myimage",
                "--owner",
                "homelab",
                "--type",
                "container",
                "--repo",
                "myproject",
            ],
        )

        assert result.exit_code == 0
        assert route.called
        assert "linked" in result.output.lower()


@pytest.mark.usefixtures("mock_client")
def test_pkg_unlink_command(runner: CliRunner):
    """Test pkg unlink command."""
    import httpx
    import respx

    with respx.mock:
        # Package API uses /api/packages/ not /api/v1/packages/
        route = respx.post(
            "https://test.example.com/api/packages/homelab/container/myimage/-/unlink"
        )
        route.mock(return_value=httpx.Response(204))

        result = runner.invoke(
            main,
            [
                "pkg",
                "unlink",
                "myimage",
                "--owner",
                "homelab",
                "--type",
                "container",
            ],
        )

        assert result.exit_code == 0
        assert route.called
        assert "unlinked" in result.output.lower()


@pytest.mark.usefixtures("mock_client")
def test_pkg_latest_command(runner: CliRunner):
    """Test pkg latest command."""
    import httpx
    import respx

    with respx.mock:
        # Package API uses /api/packages/ and /-/latest endpoint
        route = respx.get(
            "https://test.example.com/api/packages/homelab/pypi/teax/-/latest"
        )
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 1,
                    "owner": {"id": 1, "login": "homelab", "full_name": ""},
                    "name": "teax",
                    "type": "pypi",
                    "version": "0.1.8",
                    "created_at": "2024-01-15T10:00:00Z",
                    "html_url": "https://example.com/packages/teax",
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "pkg",
                "latest",
                "teax",
                "--owner",
                "homelab",
                "--type",
                "pypi",
            ],
        )

        assert result.exit_code == 0
        assert route.called


@pytest.mark.usefixtures("mock_client")
def test_pkg_link_error_handling(runner: CliRunner):
    """Test pkg link error handling."""
    import httpx
    import respx

    with respx.mock:
        # Package API uses /api/packages/ not /api/v1/packages/
        respx.post(
            "https://test.example.com/api/packages/homelab/container/myimage/-/link/myproject"
        ).mock(return_value=httpx.Response(404, json={"message": "Package not found"}))

        result = runner.invoke(
            main,
            [
                "pkg",
                "link",
                "myimage",
                "--owner",
                "homelab",
                "--type",
                "container",
                "--repo",
                "myproject",
            ],
        )

        assert result.exit_code != 0
        assert "Error" in result.output


# --- Runs Enhancement Tests ---


def test_abbreviate_job_name_lint():
    """Test abbreviate_job_name for lint patterns."""
    from teax.cli import abbreviate_job_name

    assert abbreviate_job_name("lint") == "lint"
    assert abbreviate_job_name("Lint") == "lint"
    assert abbreviate_job_name("Run linting") == "lint"
    assert abbreviate_job_name("type check") == "lint"
    assert abbreviate_job_name("Type Check (Python)") == "lint"


def test_abbreviate_job_name_tests():
    """Test abbreviate_job_name for test patterns."""
    from teax.cli import abbreviate_job_name

    assert abbreviate_job_name("unit test") == "unit"
    assert abbreviate_job_name("Unit Tests (Python 3.11)") == "unit"
    assert abbreviate_job_name("integration test") == "int"
    assert abbreviate_job_name("e2e test") == "e2e"
    assert abbreviate_job_name("End-to-End Tests") == "e2e"
    assert abbreviate_job_name("smoke test") == "smoke"
    assert abbreviate_job_name("visual test") == "visual"


def test_abbreviate_job_name_build():
    """Test abbreviate_job_name for build patterns."""
    from teax.cli import abbreviate_job_name

    assert abbreviate_job_name("build") == "build"
    assert abbreviate_job_name("Build Docker") == "build"
    assert abbreviate_job_name("package") == "build"
    assert abbreviate_job_name("push") == "build"
    assert abbreviate_job_name("deploy") == "deploy"


def test_abbreviate_job_name_fallback():
    """Test abbreviate_job_name fallback to first 4 chars."""
    from teax.cli import abbreviate_job_name

    assert abbreviate_job_name("my-custom-job") == "mycu"
    assert abbreviate_job_name("!@#$unknown123") == "unkn"
    assert abbreviate_job_name("AB") == "ab"
    assert abbreviate_job_name("") == "job"
    assert abbreviate_job_name("!@#$%") == "job"  # No alphanumeric chars


def test_abbreviate_workflow_name_patterns():
    """Test abbreviate_workflow_name pattern matching."""
    from teax.cli import abbreviate_workflow_name

    # Standard patterns
    assert abbreviate_workflow_name("ci.yml") == "C"
    assert abbreviate_workflow_name("build.yml") == "B"
    assert abbreviate_workflow_name("test.yml") == "T"
    assert abbreviate_workflow_name("lint.yml") == "L"
    assert abbreviate_workflow_name("deploy.yml") == "D"
    assert abbreviate_workflow_name("verify.yml") == "V"
    assert abbreviate_workflow_name("publish.yml") == "P"

    # Hyphenated names - should match the key part
    assert abbreviate_workflow_name("staging-deploy.yml") == "D"
    assert abbreviate_workflow_name("staging-verify.yml") == "V"
    assert abbreviate_workflow_name("prod-deploy.yml") == "D"

    # Case insensitive
    assert abbreviate_workflow_name("CI.yml") == "C"
    assert abbreviate_workflow_name("BUILD.yaml") == "B"


def test_abbreviate_workflow_name_fallback():
    """Test abbreviate_workflow_name fallback to first char."""
    from teax.cli import abbreviate_workflow_name

    # No pattern match - use first letter
    assert abbreviate_workflow_name("custom.yml") == "C"
    assert abbreviate_workflow_name("my-workflow.yml") == "M"
    assert abbreviate_workflow_name("foo-bar.yml") == "F"

    # Edge cases
    assert abbreviate_workflow_name("") == "?"
    assert abbreviate_workflow_name("!@#.yml") == "?"


def test_extract_workflow_name():
    """Test extract_workflow_name handles various path formats."""
    from teax.cli import extract_workflow_name

    # Standard paths
    assert extract_workflow_name(".gitea/workflows/ci.yml") == "ci.yml"
    assert extract_workflow_name(".github/workflows/build.yml") == "build.yml"

    # Paths with @refs suffix (Gitea API format)
    assert (
        extract_workflow_name(".gitea/workflows/staging-deploy.yml@refs/heads/main")
        == "staging-deploy.yml"
    )
    assert (
        extract_workflow_name(".gitea/workflows/staging-verify.yml@refs/heads/feature")
        == "staging-verify.yml"
    )
    assert extract_workflow_name("ci.yml@refs/tags/v1.0.0") == "ci.yml"

    # Edge cases
    assert extract_workflow_name("") == "unknown"
    assert extract_workflow_name(None) == "unknown"


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_by_run_number(runner: CliRunner):
    """Test resolve_run_id resolves run_number to run_id."""
    import httpx
    import respx

    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 99999,
                            "run_number": 223,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc123",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        with GiteaClient() as client:
            # Small number should be resolved as run_number
            run_id = resolve_run_id(client, "owner", "repo", "223")
            assert run_id == 99999


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_large_number_as_run_id(runner: CliRunner):
    """Test resolve_run_id treats large numbers as run_id directly."""
    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with GiteaClient() as client:
        # Large number should be used directly as run_id
        run_id = resolve_run_id(client, "owner", "repo", "99999")
        assert run_id == 99999


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_negative_rejected(runner: CliRunner):
    """Test resolve_run_id rejects negative numbers."""
    import pytest

    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with GiteaClient() as client:
        with pytest.raises(ValueError, match="must be positive"):
            resolve_run_id(client, "owner", "repo", "-1")


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_zero_rejected(runner: CliRunner):
    """Test resolve_run_id rejects zero."""
    import pytest

    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with GiteaClient() as client:
        with pytest.raises(ValueError, match="must be positive"):
            resolve_run_id(client, "owner", "repo", "0")


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_not_found_errors(runner: CliRunner):
    """Test resolve_run_id errors when run_number not found."""
    import httpx
    import respx

    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={"workflow_runs": []},  # Empty - no runs found
            )
        )

        with GiteaClient() as client:
            # Small number not found should error, not fall through
            with pytest.raises(ValueError, match="not found in recent runs"):
                resolve_run_id(client, "owner", "repo", "999")


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_by_id_flag_forces_small_as_run_id(runner: CliRunner):
    """Test --by-id flag forces small number to be treated as run_id."""
    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with GiteaClient() as client:
        # With force_id=True, small number should be returned directly
        run_id = resolve_run_id(client, "owner", "repo", "42", force_id=True)
        assert run_id == 42


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_by_number_flag_forces_large_as_run_number(runner: CliRunner):
    """Test --by-number flag forces large number to be looked up as run_number."""
    import httpx
    import respx

    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 500000,
                            "run_number": 15000,  # Large run_number
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc123",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        with GiteaClient() as client:
            # With force_number=True, large number should be looked up as run_number
            run_id = resolve_run_id(client, "owner", "repo", "15000", force_number=True)
            assert run_id == 500000


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_both_flags_errors(runner: CliRunner):
    """Test that both --by-number and --by-id flags together raises error."""
    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with GiteaClient() as client:
        with pytest.raises(ValueError, match="Cannot specify both"):
            resolve_run_id(
                client, "owner", "repo", "42", force_number=True, force_id=True
            )


@pytest.mark.usefixtures("mock_client")
def test_resolve_run_id_non_numeric_errors(runner: CliRunner):
    """Test that non-numeric run_ref raises error."""
    from teax.api import GiteaClient
    from teax.cli import resolve_run_id

    with GiteaClient() as client:
        with pytest.raises(ValueError, match="Invalid run reference"):
            resolve_run_id(client, "owner", "repo", "abc")


@pytest.mark.usefixtures("mock_client")
def test_runs_failed_sha_sanitization(runner: CliRunner):
    """Test that sha parameter is sanitized in output (appears as literal text)."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={"workflow_runs": []},  # Empty - no failures
            )
        )

        # Test with Rich markup in sha (should be escaped and appear as literal text)
        result = runner.invoke(
            main,
            ["runs", "failed", "--repo", "owner/repo", "--sha", "[red]malicious[/red]"],
        )

        # Escaped markup appears as literal text [red] in output
        # (not rendered as ANSI color codes)
        assert "[red]malicious[/red]" in result.output
        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_runs_status_tmux_multiple_failed_jobs(runner: CliRunner):
    """Test runs status -o tmux shows count for multiple failed jobs."""
    import httpx
    import respx

    with respx.mock:
        # Mock runs list
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/main.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list with multiple failures
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                        {
                            "id": 102,
                            "name": "test",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                        {
                            "id": 103,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "tmux", "runs", "status", "--repo", "owner/repo", "--verbose"]
        )

        # Should show count [3] for multiple failed jobs
        assert "M:✗[3]" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_verbose_shows_failed_jobs(runner: CliRunner):
    """Test runs status --verbose shows failed job details."""
    import httpx
    import respx

    with respx.mock:
        # Mock runs list
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list for the failed run
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "runner-1",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                        {
                            "id": 102,
                            "name": "test",
                            "status": "completed",
                            "conclusion": "success",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "runner-1",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["runs", "status", "--repo", "owner/repo", "--verbose"]
        )

        # Should show failed job name
        assert "lint" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_tmux_with_failure_hint(runner: CliRunner):
    """Test runs status -o tmux shows failure hints."""
    import httpx
    import respx

    with respx.mock:
        # Mock runs list
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/main.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "Run linting",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "runner-1",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "tmux", "runs", "status", "--repo", "owner/repo", "--verbose"]
        )

        # Should show abbreviated job name in brackets
        assert "M:✗[lint]" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_json_with_verbose_includes_jobs(runner: CliRunner):
    """Test runs status -o json --verbose includes jobs array."""
    import json

    import httpx
    import respx

    with respx.mock:
        # Mock runs list
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "runs", "status", "--repo", "owner/repo", "--verbose"]
        )

        data = json.loads(result.output)
        ci_workflow = data["workflows"]["ci.yml"]
        assert "jobs" in ci_workflow
        assert "failed_jobs" in ci_workflow
        assert ci_workflow["failed_jobs"] == ["lint"]


@pytest.mark.usefixtures("mock_client")
def test_runs_failed_command(runner: CliRunner):
    """Test runs failed command shows most recent failure."""
    import httpx
    import respx

    with respx.mock:
        # Mock runs list
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "failed", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "ci.yml" in result.output
        assert "lint" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_failed_no_failures(runner: CliRunner):
    """Test runs failed with no failures."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "failed", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "No failed runs found" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_failed_no_failures_json_output(runner: CliRunner):
    """Test runs failed -o json returns valid JSON when no failures."""
    import json

    import httpx
    import respx

    with respx.mock:
        # Mock runs list with no failures
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",  # Not a failure
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "runs", "failed", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert data["error"] is None
        assert data["message"] == "No failed runs found"
        assert data["run"] is None


@pytest.mark.usefixtures("mock_client")
def test_runs_failed_json_output(runner: CliRunner):
    """Test runs failed with JSON output."""
    import json

    import httpx
    import respx

    with respx.mock:
        # Mock runs list
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                        {
                            "id": 102,
                            "name": "test",
                            "status": "completed",
                            "conclusion": "success",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main, ["-o", "json", "runs", "failed", "--repo", "owner/repo"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["run_id"] == 42
        assert data["run_number"] == 15
        assert data["workflow"] == "ci.yml"
        assert data["failed_jobs"] == ["lint"]
        assert len(data["jobs"]) == 2


@pytest.mark.usefixtures("mock_client")
def test_runs_get_with_run_number(runner: CliRunner):
    """Test runs get accepts run_number and resolves to run_id."""
    import httpx
    import respx

    with respx.mock:
        # Mock runs list for resolution
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 99999,
                            "run_number": 223,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs list for the resolved run_id
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/99999/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "run_id": 99999,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        result = runner.invoke(main, ["runs", "get", "223", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "build" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_get_by_id_flag_skips_resolution(runner: CliRunner):
    """Test runs get --by-id skips run_number resolution."""
    import httpx
    import respx

    with respx.mock:
        # Mock the jobs endpoint for direct run_id access (no runs list call)
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "run_id": 42,
                            "workflow_name": "CI",
                            "head_sha": "abc12345",
                            "runner_name": "",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "steps": [],
                        },
                    ]
                },
            )
        )

        # With --by-id, small number 42 should be used directly as run_id
        result = runner.invoke(
            main, ["runs", "get", "42", "--repo", "owner/repo", "--by-id"]
        )

        assert result.exit_code == 0
        assert "build" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_verbose_degrades_gracefully(runner: CliRunner):
    """Test runs status --verbose continues when job fetch fails for some workflows."""
    import httpx
    import respx

    with respx.mock:
        # Mock runs list with one failed workflow
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs endpoint to return 500 error (simulating fetch failure)
        respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(return_value=httpx.Response(500, json={"message": "Server error"}))

        # Status should still work even though jobs fetch failed
        result = runner.invoke(
            main, ["runs", "status", "--repo", "owner/repo", "--verbose"]
        )

        # Should not fail with exit code != 0 (degrades gracefully)
        # The run shows up but without job details
        assert result.exit_code == 1  # failure exit code from run conclusion
        assert "ci.yml" in result.output or "CI" in result.output


# --- runs status --show Integration Tests ---


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_matching_workflow(runner: CliRunner):
    """Test --show with a workflow that exists in the API response."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "tmux", "runs", "status", "-r", "owner/repo", "--show", "C:ci.yml"],
        )

        assert result.exit_code == 0
        assert "C:✓" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_workflow_not_triggered(runner: CliRunner):
    """Test --show with a workflow not in the API response (not triggered)."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Request deploy.yml which doesn't exist in the response
        result = runner.invoke(
            main,
            [
                "-o",
                "tmux",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "D:deploy.yml",
            ],
        )

        # Should exit with code 3 (pending/no_runs for specified workflows)
        assert result.exit_code == 3
        assert "D:-" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_mixed_status(runner: CliRunner):
    """Test --show with one existing and one missing workflow."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "tmux",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml,D:deploy.yml",
            ],
        )

        # Should succeed because ci.yml passed
        # (deploy.yml not triggered doesn't count as failure)
        assert result.exit_code == 0
        assert "C:✓" in result.output
        assert "D:-" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_failure_overrides_not_triggered(runner: CliRunner):
    """Test --show with a failure and a not-triggered workflow."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "tmux",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml,D:deploy.yml",
            ],
        )

        # Should fail (exit code 1) because ci.yml failed
        assert result.exit_code == 1
        assert "C:✗" in result.output
        assert "D:-" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_running_workflow(runner: CliRunner):
    """Test --show with a running workflow."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "in_progress",
                            "conclusion": None,
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            ["-o", "tmux", "runs", "status", "-r", "owner/repo", "--show", "C:ci.yml"],
        )

        # Should return exit code 2 for running
        assert result.exit_code == 2
        # Spinner character will vary, just check C: prefix is there
        assert "C:" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_json_array_format(runner: CliRunner):
    """Test --show with JSON output produces array format."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "2024-01-01T10:00:00Z",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "json",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml,D:deploy.yml",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)

        # With --show, workflows should be an array
        assert isinstance(data["workflows"], list)
        assert len(data["workflows"]) == 2

        # Check first workflow (triggered)
        ci_wf = data["workflows"][0]
        assert ci_wf["abbrev"] == "C"
        assert ci_wf["workflow"] == "ci.yml"
        assert ci_wf["triggered"] is True
        assert ci_wf["conclusion"] == "success"

        # Check second workflow (not triggered)
        deploy_wf = data["workflows"][1]
        assert deploy_wf["abbrev"] == "D"
        assert deploy_wf["workflow"] == "deploy.yml"
        assert deploy_wf["triggered"] is False
        assert deploy_wf["status"] is None


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_preserves_order(runner: CliRunner):
    """Test --show preserves the order specified in the flag."""
    import json

    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 41,
                            "run_number": 14,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "Build",
                            "path": ".gitea/workflows/build.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Request in order: ci, build (opposite of API order)
        result = runner.invoke(
            main,
            [
                "-o",
                "json",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml,B:build.yml",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)

        # Order should match --show specification, not API response
        assert data["workflows"][0]["workflow"] == "ci.yml"
        assert data["workflows"][1]["workflow"] == "build.yml"


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_invalid_format(runner: CliRunner):
    """Test --show with invalid format shows error."""
    result = runner.invoke(
        main,
        ["runs", "status", "-r", "owner/repo", "--show", "invalid"],
    )

    assert result.exit_code == 4
    assert "expected 'A:workflow.yml'" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_csv_includes_abbrev(runner: CliRunner):
    """Test --show with CSV output includes abbrev column."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "csv",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml,D:deploy.yml",
            ],
        )

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")

        # Check header includes abbrev and triggered
        assert "abbrev" in lines[0]
        assert "triggered" in lines[0]

        # Check data rows
        assert lines[1].startswith("C,ci.yml,true")
        assert lines[2].startswith("D,deploy.yml,false")


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_empty_string_errors(runner: CliRunner):
    """Test --show '' should error, not silently behave like no --show."""
    result = runner.invoke(
        main,
        ["runs", "status", "-r", "owner/repo", "--show", ""],
    )

    assert result.exit_code == 4
    assert "Empty --show specification" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_with_verbose(runner: CliRunner):
    """Test --show with --verbose filters job fetching correctly."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                        {
                            "id": 43,
                            "run_number": 16,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "Build",
                            "path": ".gitea/workflows/build.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        # Mock jobs endpoint for ci.yml only (build.yml not in show_map)
        jobs_route = respx.get(
            "https://test.example.com/api/v1/repos/owner/repo/actions/runs/42/jobs"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 101,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "failure",
                            "run_id": 42,
                            "started_at": "",
                            "completed_at": "",
                            "runner_id": 1,
                            "runner_name": "runner",
                            "steps": [],
                        }
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "tmux",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml",
                "--verbose",
            ],
        )

        assert result.exit_code == 1
        # Should show failure with job hint
        assert "C:✗" in result.output
        assert jobs_route.called


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_table_format(runner: CliRunner):
    """Test --show with default table format."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            ["runs", "status", "-r", "owner/repo", "--show", "C:ci.yml,D:deploy.yml"],
        )

        assert result.exit_code == 0
        # Table format shows workflow names and "not triggered"
        assert "ci.yml" in result.output
        assert "deploy.yml" in result.output
        assert "not triggered" in result.output


@pytest.mark.usefixtures("mock_client")
def test_runs_status_show_simple_format(runner: CliRunner):
    """Test --show with simple output format."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/actions/runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 42,
                            "run_number": 15,
                            "run_attempt": 1,
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc12345",
                            "head_branch": "main",
                            "event": "push",
                            "display_title": "CI",
                            "path": ".gitea/workflows/ci.yml",
                            "started_at": "",
                            "completed_at": "",
                            "html_url": "",
                            "url": "",
                            "repository_id": 1,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(
            main,
            [
                "-o",
                "simple",
                "runs",
                "status",
                "-r",
                "owner/repo",
                "--show",
                "C:ci.yml,D:deploy.yml",
            ],
        )

        assert result.exit_code == 0
        # Simple format shows workflow status
        assert "ci.yml: ✓ success" in result.output
        assert "deploy.yml: - not triggered" in result.output


# --- Helper Function Tests for Sprint Management ---


def test_compute_issue_fields_sprint_number():
    """Test compute_issue_fields extracts sprint number correctly."""
    from teax.cli import compute_issue_fields

    # Create mock issue with sprint label
    issue = SimpleNamespace(
        labels=[
            SimpleNamespace(name="sprint/28"),
            SimpleNamespace(name="ready"),
        ]
    )
    fields = compute_issue_fields(issue)
    assert fields["sprint_number"] == 28
    assert fields["is_ready"] is True


def test_compute_issue_fields_no_labels():
    """Test compute_issue_fields handles no labels."""
    from teax.cli import compute_issue_fields

    issue = SimpleNamespace(labels=None)
    fields = compute_issue_fields(issue)
    assert fields["sprint_number"] is None
    assert fields["is_ready"] is False
    assert fields["is_bug"] is False
    assert fields["effort"] is None
    assert fields["priority"] is None


def test_compute_issue_fields_bug_detection():
    """Test compute_issue_fields detects bug labels."""
    from teax.cli import compute_issue_fields

    issue1 = SimpleNamespace(labels=[SimpleNamespace(name="type/bug")])
    assert compute_issue_fields(issue1)["is_bug"] is True

    issue2 = SimpleNamespace(labels=[SimpleNamespace(name="bug")])
    assert compute_issue_fields(issue2)["is_bug"] is True


def test_compute_issue_fields_effort_priority():
    """Test compute_issue_fields extracts effort and priority."""
    from teax.cli import compute_issue_fields

    issue = SimpleNamespace(
        labels=[
            SimpleNamespace(name="effort/M"),
            SimpleNamespace(name="prio/p1"),
        ]
    )
    fields = compute_issue_fields(issue)
    assert fields["effort"] == "M"
    assert fields["priority"] == "p1"


def test_filter_issues_by_no_labels():
    """Test filter_issues_by_no_labels with glob patterns."""
    from teax.cli import filter_issues_by_no_labels

    issues = [
        SimpleNamespace(labels=[SimpleNamespace(name="sprint/28")]),
        SimpleNamespace(labels=[SimpleNamespace(name="ready")]),
        SimpleNamespace(
            labels=[SimpleNamespace(name="ready"), SimpleNamespace(name="sprint/29")]
        ),
        SimpleNamespace(labels=[]),
    ]

    # Filter out sprint/* labels
    filtered = filter_issues_by_no_labels(issues, ["sprint/*"])
    assert len(filtered) == 2
    # Should include 'ready' only and empty labels
    label_sets = [[lb.name for lb in i.labels] for i in filtered]
    assert ["ready"] in label_sets
    assert [] in label_sets


def test_filter_issues_by_no_labels_empty_patterns():
    """Test filter_issues_by_no_labels returns all when no patterns."""
    from teax.cli import filter_issues_by_no_labels

    issues = [
        SimpleNamespace(labels=[SimpleNamespace(name="sprint/28")]),
        SimpleNamespace(labels=[SimpleNamespace(name="ready")]),
    ]

    filtered = filter_issues_by_no_labels(issues, [])
    assert len(filtered) == 2


def test_compute_issue_fields_ignores_invalid_sprint_numbers():
    """Test compute_issue_fields ignores sprint/0 and negative sprint numbers."""
    from teax.cli import compute_issue_fields

    # Sprint number 0 should be ignored
    issue_zero = SimpleNamespace(labels=[SimpleNamespace(name="sprint/0")])
    assert compute_issue_fields(issue_zero)["sprint_number"] is None

    # Negative sprint number should be ignored
    issue_negative = SimpleNamespace(labels=[SimpleNamespace(name="sprint/-1")])
    assert compute_issue_fields(issue_negative)["sprint_number"] is None

    # Valid sprint number should work
    issue_valid = SimpleNamespace(labels=[SimpleNamespace(name="sprint/1")])
    assert compute_issue_fields(issue_valid)["sprint_number"] == 1


def test_print_issue_list_json_sanitizes_computed_fields():
    """Test that JSON output sanitizes computed effort/priority fields."""
    import json
    import sys
    from io import StringIO

    from teax.cli import OutputFormat

    # Create a mock issue with malicious escape sequences in labels
    issue = SimpleNamespace(
        number=1,
        title="Test Issue",
        state="open",
        labels=[
            SimpleNamespace(name="prio/\x1b[31mp0"),  # ANSI escape in priority
            SimpleNamespace(name="effort/\x1b[32mM"),  # ANSI escape in effort
        ],
        assignees=[],
        milestone=None,
    )

    output = OutputFormat("json")

    # Capture output
    old_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        output.print_issue_list([issue], include_computed=True)
    finally:
        sys.stdout = old_stdout

    result = captured.getvalue()
    data = json.loads(result)

    # Verify escape sequences are stripped from computed fields
    assert data[0]["priority"] == "p0"  # Not \x1b[31mp0
    assert data[0]["effort"] == "M"  # Not \x1b[32mM
    assert "\x1b" not in result  # No escape sequences anywhere


def test_filter_issues_by_no_labels_case_insensitive():
    """Test that filter_issues_by_no_labels is case-insensitive."""
    from teax.cli import filter_issues_by_no_labels

    issues = [
        SimpleNamespace(labels=[SimpleNamespace(name="Sprint/28")]),  # Uppercase
        SimpleNamespace(labels=[SimpleNamespace(name="sprint/29")]),  # Lowercase
        SimpleNamespace(labels=[SimpleNamespace(name="ready")]),
    ]

    # Pattern in lowercase should match both uppercase and lowercase labels
    filtered = filter_issues_by_no_labels(issues, ["sprint/*"])
    assert len(filtered) == 1
    assert filtered[0].labels[0].name == "ready"


def test_print_issues_json_sanitizes_state_field():
    """Test that print_issues() JSON output sanitizes the state field."""
    import json
    import sys
    from io import StringIO

    from teax.cli import OutputFormat

    # Create a mock issue with malicious escape sequence in state
    issue = SimpleNamespace(
        number=1,
        title="Test Issue",
        state="\x1b[31mopen\x1b[0m",  # ANSI escape in state
        labels=[],
        assignees=[],
        milestone=None,
        body="Test body",
    )

    output = OutputFormat("json")

    # Capture output
    old_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        output.print_issues([issue])
    finally:
        sys.stdout = old_stdout

    result = captured.getvalue()
    data = json.loads(result)

    # Verify escape sequences are stripped from state field
    assert data["issues"][0]["state"] == "open"  # Not \x1b[31mopen\x1b[0m
    assert "\x1b" not in result  # No escape sequences anywhere
