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
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies").mock(
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
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/blocks").mock(
            return_value=httpx.Response(200, json=[])
        )

        result = runner.invoke(main, ["deps", "list", "25", "--repo", "owner/repo"])

        assert result.exit_code == 0


@pytest.mark.usefixtures("mock_client")
def test_deps_list_with_blocks(runner: CliRunner):
    """Test deps list command with blocking issues."""
    import httpx
    import respx

    with respx.mock:
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/blocks").mock(
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
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999/dependencies").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies").mock(
            return_value=httpx.Response(201)
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/30/dependencies").mock(
            return_value=httpx.Response(201)
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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
        respx.delete("https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies").mock(
            return_value=httpx.Response(200)
        )

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
        respx.delete("https://test.example.com/api/v1/repos/owner/repo/issues/30/dependencies").mock(
            return_value=httpx.Response(200)
        )

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
        respx.delete("https://test.example.com/api/v1/repos/owner/repo/issues/25/dependencies").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/25/labels").mock(
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
        respx.delete("https://test.example.com/api/v1/repos/owner/repo/issues/25/labels/1").mock(
            return_value=httpx.Response(204)
        )

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
        respx.put("https://test.example.com/api/v1/repos/owner/repo/issues/25/labels").mock(
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
                "issue", "edit", "25",
                "--repo", "owner/repo",
                "--title", "New Title",
                "--assignees", "user1,user2",
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

        result = runner.invoke(
            main, ["issue", "batch", "999", "--repo", "owner/repo"]
        )

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
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/25/labels").mock(
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
        respx.get("https://test.example.com/api/v1/repos/owner/repo/issues/999/labels").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/18/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

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
        respx.get("https://test.example.com/api/v1/repos/owner/repo/milestones/999").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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
        respx.delete("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels/1").mock(
            return_value=httpx.Response(204)
        )

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
        respx.put("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

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

        result = runner.invoke(
            main, ["epic", "create", "test", "--repo", "owner/repo"]
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/18/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/18/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

        # Pass duplicate children: 17, 18, 17 (will be deduplicated to 17, 18)
        result = runner.invoke(
            main,
            [
                "epic", "create", "test", "-r", "owner/repo",
                "-c", "17", "-c", "18", "-c", "17",
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

        result = runner.invoke(
            main, ["epic", "create", "test", "--repo", "owner/repo"]
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/999/labels").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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

        result = runner.invoke(
            main, ["epic", "create", "test", "--repo", "owner/repo"]
        )

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

        result = runner.invoke(
            main, ["epic", "status", "50", "--repo", "owner/repo"]
        )

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

        result = runner.invoke(
            main, ["epic", "status", "50", "--repo", "owner/repo"]
        )

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

        result = runner.invoke(
            main, ["epic", "status", "50", "--repo", "owner/repo"]
        )

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

        result = runner.invoke(
            main, ["epic", "status", "999", "--repo", "owner/repo"]
        )

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
                    "labels": [
                        {"id": 10, "name": "epic/test", "color": "9b59b6"}
                    ],
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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/18/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

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
                    "labels": [
                        {"id": 10, "name": "epic/test", "color": "9b59b6"}
                    ],
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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/18/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/17/labels").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/18/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

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
                    "labels": [
                        {"id": 10, "name": "epic/test", "color": "9b59b6"}
                    ],
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
        respx.post("https://test.example.com/api/v1/repos/owner/repo/issues/999/labels").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

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
        respx.get(
            "https://test.example.com/api/v1/orgs/myorg/actions/runners"
        ).mock(
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

        result = runner.invoke(
            main, ["runners", "get", "42", "--repo", "owner/repo"]
        )

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

        result = runner.invoke(
            main, ["runners", "get", "999", "--repo", "owner/repo"]
        )

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
        ).mock(
            return_value=httpx.Response(
                200, json={"token": "AAABBBCCCDDD123456"}
            )
        )

        result = runner.invoke(
            main, ["runners", "token", "--repo", "owner/repo"]
        )

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
        ).mock(
            return_value=httpx.Response(
                200, json={"token": "AAABBBCCCDDD123456"}
            )
        )

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
        ).mock(
            return_value=httpx.Response(
                200, json={"token": "JSON_TOKEN_123"}
            )
        )

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

        result = runner.invoke(
            main, ["runners", "token", "--repo", "owner/repo"]
        )

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
        id=1, name="runner-1", status="online", busy=False,
        labels=["ubuntu-latest", "self-hosted"], version="v0.2.6"
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
        respx.get(
            "https://test.example.com/api/packages/myorg/generic/mypackage"
        ).mock(
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
                "pkg", "delete", "mypackage",
                "--owner", "myorg",
                "--type", "generic",
                "--version", "1.0.0",
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
                "pkg", "delete", "mypackage",
                "--owner", "myorg",
                "--type", "pypi",
                "--version", "0.1.0",
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
            "pkg", "delete", "mypackage",
            "--owner", "myorg",
            "--type", "generic",
            "--version", "1.0.0",
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
                "pkg", "delete", "[red]X[/red]",  # Malicious Rich markup
                "--owner", "myorg",
                "--type", "generic",
                "--version", "1.0.0",
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
        respx.get(
            "https://test.example.com/api/packages/myorg/container/myimage"
        ).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1, "version": "v1.0.0",
                            "created_at": "2024-01-01T00:00:00Z", "html_url": "",
                        },
                        {
                            "id": 2, "version": "v1.1.0",
                            "created_at": "2024-01-15T00:00:00Z", "html_url": "",
                        },
                        {
                            "id": 3, "version": "v1.2.0",
                            "created_at": "2024-02-01T00:00:00Z", "html_url": "",
                        },
                        {
                            "id": 4, "version": "v1.3.0",
                            "created_at": "2024-02-15T00:00:00Z", "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        result = runner.invoke(
            main,
            [
                "pkg", "prune", "myimage",
                "--owner", "myorg",
                "--type", "container",
                "--keep", "2",
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
        respx.get(
            "https://test.example.com/api/packages/myorg/container/myimage"
        ).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 3, "version": "v1.2.0",
                            "created_at": "2024-02-01T00:00:00Z", "html_url": "",
                        },
                        {
                            "id": 2, "version": "v1.1.0",
                            "created_at": "2024-01-15T00:00:00Z", "html_url": "",
                        },
                        {
                            "id": 1, "version": "v1.0.0",
                            "created_at": "2024-01-01T00:00:00Z", "html_url": "",
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
                "pkg", "prune", "myimage",
                "--owner", "myorg",
                "--type", "container",
                "--keep", "2",
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
            "pkg", "prune", "mypackage",
            "--owner", "myorg",
            "--type", "pypi",
            "--keep", "3",
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
        respx.get(
            "https://test.example.com/api/packages/myorg/container/myimage"
        ).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=[
                        {
                            "id": 1, "version": "v1.0.0",
                            "created_at": "2024-01-01T00:00:00Z", "html_url": "",
                        },
                    ],
                ),
                httpx.Response(200, json=[]),
            ]
        )

        result = runner.invoke(
            main,
            [
                "pkg", "prune", "myimage",
                "--owner", "myorg",
                "--type", "container",
                "--keep", "5",  # Keep more than exist
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
