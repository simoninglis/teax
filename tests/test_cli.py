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
