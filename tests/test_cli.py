"""Tests for CLI commands."""

import pytest
from click.testing import CliRunner

from teax.cli import main, parse_repo


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


def test_deps_add_requires_on_or_blocks(runner: CliRunner):
    """Test that deps add requires --on or --blocks."""
    result = runner.invoke(main, ["deps", "add", "25", "--repo", "owner/repo"])
    assert result.exit_code != 0
    assert "Must specify either --on or --blocks" in result.output


def test_deps_add_rejects_both_on_and_blocks(runner: CliRunner):
    """Test that deps add rejects both --on and --blocks."""
    args = [
        "deps", "add", "25", "--repo", "owner/repo",
        "--on", "17", "--blocks", "30",
    ]
    result = runner.invoke(main, args)
    assert result.exit_code != 0
    assert "Cannot specify both" in result.output
