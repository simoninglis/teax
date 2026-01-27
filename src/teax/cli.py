"""teax CLI - Gitea companion for tea feature gaps."""

import csv
import io
import json
import os
import re
import sys
from typing import Any

import click
import httpx
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from teax import __version__
from teax.api import GiteaClient

# Pattern to match terminal escape sequences and control characters
# Handles: CSI (\x1b[), OSC (\x1b]), DCS (\x1bP), APC (\x1b_), PM (\x1b^), SOS (\x1bX)
# Also matches C1 control codes (0x80-0x9f) and regular control chars
_ESC_PATTERN = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI sequences (e.g., \x1b[31m)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC sequences (terminated by BEL or ST)
    r"|\x1b[P_^X][^\x1b]*(?:\x1b\\)?"  # DCS/APC/PM/SOS sequences
    r"|\x1b[NO][^\x1b]"  # SS2/SS3 single shifts
    r"|\x1b."  # Other 2-char escape sequences
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # C0 control chars (except tab/LF)
    r"|[\x80-\x9f]"  # C1 control chars
    r"|\r(?!\n)"  # Standalone CR (not CRLF) - prevents line-rewrite spoofing
)


def terminal_safe(text: str) -> str:
    """Strip terminal control and escape sequences for safe output.

    Used for all terminal output (simple, CSV, Rich) to prevent injection.
    """
    return _ESC_PATTERN.sub("", text)


def safe_rich(text: str) -> str:
    """Escape text for safe Rich markup display.

    Strips terminal control characters (including escape sequences)
    before escaping Rich markup to prevent terminal injection attacks.
    """
    return escape(terminal_safe(text))


def csv_safe(value: str) -> str:
    """Neutralize CSV formula injection and terminal escape sequences.

    Strips terminal escape sequences and prefixes dangerous characters that
    could execute formulas in spreadsheets (Excel, Google Sheets, LibreOffice)
    with a single quote. Also handles leading whitespace before formula chars.
    """
    # Strip terminal escapes first
    value = terminal_safe(value)
    # Check for formula chars after optional leading whitespace
    stripped = value.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value

console = Console()
err_console = Console(stderr=True)

# Exception types caught by CLI commands
CLI_ERRORS = (
    httpx.HTTPStatusError,
    httpx.RequestError,
    ValueError,
    FileNotFoundError,
    ValidationError,
    TypeError,  # e.g., malformed API responses
    KeyError,  # Unexpected API response format
)


def parse_repo(repo: str) -> tuple[str, str]:
    """Parse owner/repo string into components.

    Enforces exactly one slash - rejects nested paths like owner/my/repo.
    """
    repo = repo.strip()
    if repo.count("/") != 1:
        raise click.BadParameter(
            f"Repository must be in 'owner/repo' format, got: {terminal_safe(repo)}"
        )
    owner, repo_name = repo.split("/")
    owner, repo_name = owner.strip(), repo_name.strip()
    if not owner or not repo_name:
        raise click.BadParameter(
            f"Repository must be in 'owner/repo' format, got: {terminal_safe(repo)}"
        )
    return owner, repo_name


# Maximum number of issues allowed in a single bulk operation
MAX_BULK_ISSUES = 10000


def parse_issue_spec(spec: str) -> list[int]:
    """Parse issue specification into list of issue numbers.

    Supports:
        - Single issue: "17" -> [17]
        - Range: "17-23" -> [17, 18, 19, 20, 21, 22, 23]
        - Comma-separated: "17,18,19" -> [17, 18, 19]
        - Mixed: "17-19,25,30-32" -> [17, 18, 19, 25, 30, 31, 32]

    Args:
        spec: Issue specification string

    Returns:
        Sorted, deduplicated list of issue numbers

    Raises:
        click.BadParameter: If spec is invalid or exceeds MAX_BULK_ISSUES
    """
    result: set[int] = set()

    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            # Handle range
            range_parts = part.split("-")
            if len(range_parts) != 2:
                raise click.BadParameter(f"Invalid range format: {terminal_safe(part)}")
            try:
                start = int(range_parts[0].strip())
                end = int(range_parts[1].strip())
            except ValueError as e:
                safe_part = terminal_safe(part)
                raise click.BadParameter(f"Invalid number in range: {safe_part}") from e
            if start > end:
                safe_part = terminal_safe(part)
                raise click.BadParameter(f"Range start must be <= end: {safe_part}")
            # Check range size before expanding to prevent memory exhaustion
            range_size = end - start + 1
            if range_size > MAX_BULK_ISSUES:
                raise click.BadParameter(
                    f"Range too large: {range_size} issues (max {MAX_BULK_ISSUES})"
                )
            result.update(range(start, end + 1))
            if len(result) > MAX_BULK_ISSUES:
                raise click.BadParameter(
                    f"Too many issues: exceeds maximum of {MAX_BULK_ISSUES}"
                )
        else:
            # Handle single number
            try:
                result.add(int(part))
            except ValueError as e:
                safe_part = terminal_safe(part)
                raise click.BadParameter(f"Invalid issue number: {safe_part}") from e

    if not result:
        raise click.BadParameter("No valid issue numbers in specification")

    if len(result) > MAX_BULK_ISSUES:
        raise click.BadParameter(
            f"Too many issues: {len(result)} (max {MAX_BULK_ISSUES})"
        )

    return sorted(result)


class OutputFormat:
    """Output formatting helpers."""

    def __init__(self, format_type: str):
        self.format_type = format_type

    def print_deps(self, deps: list[Any], issue_num: int, direction: str) -> None:
        """Print dependency list."""
        if self.format_type == "simple":
            for d in deps:
                click.echo(f"#{d.number}")
        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["number", "title", "state", "repository"])
            for d in deps:
                writer.writerow([
                    d.number,
                    csv_safe(d.title),
                    csv_safe(d.state),
                    csv_safe(d.repository.full_name),
                ])
            click.echo(output.getvalue().rstrip())
        else:  # table (default)
            if not deps:
                console.print(f"[dim]Issue #{issue_num} has no {direction}[/dim]")
                return

            table = Table(title=f"Issue #{issue_num} {direction}")
            table.add_column("#", style="cyan")
            table.add_column("Title")
            table.add_column("State", style="green")
            table.add_column("Repository", style="dim")

            for d in deps:
                state_style = "green" if d.state == "open" else "dim"
                table.add_row(
                    str(d.number),
                    safe_rich(d.title),
                    f"[{state_style}]{safe_rich(d.state)}[/{state_style}]",
                    safe_rich(d.repository.full_name),
                )
            console.print(table)

    def print_labels(self, labels: list[Any]) -> None:
        """Print label list."""
        if self.format_type == "simple":
            for label in labels:
                click.echo(terminal_safe(label.name))
        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["name", "color", "description"])
            for label in labels:
                writer.writerow([
                    csv_safe(label.name),
                    csv_safe(label.color),
                    csv_safe(label.description),
                ])
            click.echo(output.getvalue().rstrip())
        else:  # table
            if not labels:
                console.print("[dim]No labels[/dim]")
                return

            table = Table(title="Labels")
            table.add_column("Name", style="cyan")
            table.add_column("Color")
            table.add_column("Description", style="dim")

            for label in labels:
                table.add_row(
                    safe_rich(label.name),
                    f"#{safe_rich(label.color)}",
                    safe_rich(label.description),
                )
            console.print(table)

    def print_issues(
        self, issues: list[Any], errors: dict[int, str] | None = None
    ) -> None:
        """Print issue list for batch view command.

        Args:
            issues: List of Issue objects to display
            errors: Optional dict of issue_num -> error message for failed fetches
        """
        errors = errors or {}

        if self.format_type == "json":
            # JSON output - full data including body
            output_data = {
                "issues": [
                    {
                        "number": issue.number,
                        "title": terminal_safe(issue.title),
                        "state": issue.state,
                        "labels": [
                            terminal_safe(lb.name) for lb in (issue.labels or [])
                        ],
                        "assignees": [
                            terminal_safe(a.login) for a in (issue.assignees or [])
                        ],
                        "milestone": (
                            terminal_safe(issue.milestone.title)
                            if issue.milestone
                            else None
                        ),
                        "body": terminal_safe(issue.body or ""),
                    }
                    for issue in issues
                ],
                "errors": {
                    str(num): terminal_safe(msg) for num, msg in errors.items()
                },
            }
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "number", "title", "state", "labels", "assignees", "milestone", "body"
            ])
            for issue in issues:
                labels_str = ",".join(
                    csv_safe(lb.name) for lb in (issue.labels or [])
                )
                assignees_str = ",".join(
                    csv_safe(a.login) for a in (issue.assignees or [])
                )
                milestone_str = (
                    csv_safe(issue.milestone.title) if issue.milestone else ""
                )
                # Truncate body for CSV
                body = issue.body or ""
                body_preview = body[:200] + "..." if len(body) > 200 else body
                writer.writerow([
                    issue.number,
                    csv_safe(issue.title),
                    csv_safe(issue.state),
                    labels_str,
                    assignees_str,
                    milestone_str,
                    csv_safe(body_preview),
                ])
            # Add error rows if any
            for num, msg in errors.items():
                writer.writerow([num, f"ERROR: {csv_safe(msg)}", "", "", "", "", ""])
            click.echo(output.getvalue().rstrip())

        elif self.format_type == "simple":
            for issue in issues:
                click.echo(f"#{issue.number} {terminal_safe(issue.title)}")
            for num, msg in errors.items():
                click.echo(f"#{num} ERROR: {terminal_safe(msg)}")

        else:  # table (default)
            if not issues and not errors:
                console.print("[dim]No issues found[/dim]")
                return

            table = Table(title="Issues")
            table.add_column("#", style="cyan")
            table.add_column("Title")
            table.add_column("State")
            table.add_column("Labels", style="dim")
            table.add_column("Assignees", style="dim")
            table.add_column("Milestone", style="dim")
            table.add_column("Body", style="dim", max_width=40)

            for issue in issues:
                state_style = "green" if issue.state == "open" else "red"
                labels_str = ", ".join(
                    safe_rich(lb.name) for lb in (issue.labels or [])
                )
                assignees_str = ", ".join(
                    safe_rich(a.login) for a in (issue.assignees or [])
                )
                milestone_str = (
                    safe_rich(issue.milestone.title) if issue.milestone else ""
                )
                # Truncate body for table
                body = issue.body or ""
                body_preview = body[:200] + "..." if len(body) > 200 else body
                table.add_row(
                    str(issue.number),
                    safe_rich(issue.title),
                    f"[{state_style}]{safe_rich(issue.state)}[/{state_style}]",
                    labels_str,
                    assignees_str,
                    milestone_str,
                    safe_rich(body_preview),
                )

            # Add error rows
            for num, msg in errors.items():
                table.add_row(
                    str(num),
                    f"[red]ERROR: {safe_rich(msg)}[/red]",
                    "", "", "", "", ""
                )

            console.print(table)

    def print_runners(self, runners: list[Any]) -> None:
        """Print runner list."""
        if self.format_type == "json":
            output_data = [
                {
                    "id": r.id,
                    "name": terminal_safe(r.name),
                    "status": terminal_safe(r.status),
                    "busy": r.busy,
                    "labels": [terminal_safe(lb) for lb in r.labels],
                    "version": terminal_safe(r.version),
                }
                for r in runners
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for r in runners:
                click.echo(f"{r.id} {terminal_safe(r.name)}")

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "name", "status", "busy", "labels", "version"])
            for r in runners:
                labels_str = ",".join(csv_safe(lb) for lb in r.labels)
                writer.writerow([
                    r.id,
                    csv_safe(r.name),
                    csv_safe(r.status),
                    r.busy,
                    labels_str,
                    csv_safe(r.version),
                ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not runners:
                console.print("[dim]No runners found[/dim]")
                return

            table = Table(title="Runners")
            table.add_column("ID", style="cyan")
            table.add_column("Name")
            table.add_column("Status")
            table.add_column("Busy")
            table.add_column("Labels", style="dim")
            table.add_column("Version", style="dim")

            for r in runners:
                status_style = "green" if r.status == "online" else "dim"
                busy_style = "yellow" if r.busy else "dim"
                labels_str = ", ".join(safe_rich(lb) for lb in r.labels)
                table.add_row(
                    str(r.id),
                    safe_rich(r.name),
                    f"[{status_style}]{safe_rich(r.status)}[/{status_style}]",
                    f"[{busy_style}]{r.busy}[/{busy_style}]",
                    labels_str,
                    safe_rich(r.version),
                )
            console.print(table)

    def print_packages(self, packages: list[Any]) -> None:
        """Print package list."""
        if self.format_type == "json":
            output_data = [
                {
                    "id": p.id,
                    "name": terminal_safe(p.name),
                    "type": terminal_safe(p.type),
                    "version": terminal_safe(p.version),
                    "owner": terminal_safe(p.owner.login),
                    "created_at": terminal_safe(p.created_at),
                }
                for p in packages
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for p in packages:
                click.echo(
                    f"{terminal_safe(p.type)}/{terminal_safe(p.name)}:"
                    f"{terminal_safe(p.version)}"
                )

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["name", "type", "version", "owner", "created_at"])
            for p in packages:
                writer.writerow([
                    csv_safe(p.name),
                    csv_safe(p.type),
                    csv_safe(p.version),
                    csv_safe(p.owner.login),
                    csv_safe(p.created_at),
                ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not packages:
                console.print("[dim]No packages found[/dim]")
                return

            table = Table(title="Packages")
            table.add_column("Name", style="cyan")
            table.add_column("Type")
            table.add_column("Version")
            table.add_column("Owner", style="dim")
            table.add_column("Created", style="dim")

            for p in packages:
                table.add_row(
                    safe_rich(p.name),
                    safe_rich(p.type),
                    safe_rich(p.version),
                    safe_rich(p.owner.login),
                    safe_rich(p.created_at[:10] if p.created_at else ""),
                )
            console.print(table)

    def print_package_versions(
        self, name: str, pkg_type: str, versions: list[Any]
    ) -> None:
        """Print package version list."""
        if self.format_type == "json":
            output_data = {
                "name": terminal_safe(name),
                "type": terminal_safe(pkg_type),
                "versions": [
                    {
                        "id": v.id,
                        "version": terminal_safe(v.version),
                        "created_at": terminal_safe(v.created_at),
                        "html_url": terminal_safe(v.html_url),
                    }
                    for v in versions
                ],
            }
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for v in versions:
                click.echo(terminal_safe(v.version))

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["version", "created_at", "html_url"])
            for v in versions:
                writer.writerow([
                    csv_safe(v.version),
                    csv_safe(v.created_at),
                    csv_safe(v.html_url),
                ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not versions:
                console.print("[dim]No versions found[/dim]")
                return

            esc_name = safe_rich(name)
            esc_type = safe_rich(pkg_type)
            table = Table(title=f"Package: {esc_name} ({esc_type})")
            table.add_column("Version", style="cyan")
            table.add_column("Created", style="dim")
            table.add_column("URL", style="dim")

            for v in versions:
                table.add_row(
                    safe_rich(v.version),
                    safe_rich(v.created_at[:10] if v.created_at else ""),
                    safe_rich(v.html_url),
                )
            console.print(table)

    def print_prune_preview(
        self,
        name: str,
        pkg_type: str,
        to_delete: list[Any],
        to_keep: list[Any],
        execute: bool,
    ) -> None:
        """Print package prune preview."""
        if self.format_type == "json":
            output_data = {
                "name": terminal_safe(name),
                "type": terminal_safe(pkg_type),
                "dry_run": not execute,
                "to_delete": [terminal_safe(v.version) for v in to_delete],
                "to_keep": [terminal_safe(v.version) for v in to_keep],
            }
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            action = "Deleting" if execute else "Would delete"
            for v in to_delete:
                click.echo(f"{action}: {terminal_safe(v.version)}")

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["version", "action"])
            for v in to_delete:
                action = "delete" if execute else "would_delete"
                writer.writerow([csv_safe(v.version), action])
            for v in to_keep:
                writer.writerow([csv_safe(v.version), "keep"])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            mode = "[green]Executing[/green]" if execute else "[yellow]Dry run[/yellow]"
            esc_name = safe_rich(name)
            esc_type = safe_rich(pkg_type)
            console.print(f"\n[bold]Prune {esc_name} ({esc_type})[/bold] - {mode}")

            if to_delete:
                console.print(f"\n[red]To delete ({len(to_delete)}):[/red]")
                for v in to_delete:
                    console.print(f"  - {safe_rich(v.version)}")

            if to_keep:
                console.print(f"\n[green]To keep ({len(to_keep)}):[/green]")
                for v in to_keep:
                    console.print(f"  - {safe_rich(v.version)}")

    def print_secrets(self, secrets: list[Any]) -> None:
        """Print secrets list (names only - values are never returned)."""
        if self.format_type == "json":
            output_data = [
                {
                    "name": terminal_safe(s.name),
                    "created_at": terminal_safe(s.created_at),
                }
                for s in secrets
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for s in secrets:
                click.echo(terminal_safe(s.name))

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["name", "created_at"])
            for s in secrets:
                writer.writerow([csv_safe(s.name), csv_safe(s.created_at)])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not secrets:
                console.print("[dim]No secrets found[/dim]")
                return

            table = Table(title="Secrets")
            table.add_column("Name", style="cyan")
            table.add_column("Created", style="dim")

            for s in secrets:
                table.add_row(safe_rich(s.name), safe_rich(s.created_at))

            console.print(table)

    def print_variables(self, variables: list[Any]) -> None:
        """Print variables list."""
        if self.format_type == "json":
            output_data = [
                {
                    "name": terminal_safe(v.name),
                    "value": terminal_safe(v.data),
                }
                for v in variables
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for v in variables:
                click.echo(f"{terminal_safe(v.name)}={terminal_safe(v.data)}")

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["name", "value"])
            for v in variables:
                writer.writerow([csv_safe(v.name), csv_safe(v.data)])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not variables:
                console.print("[dim]No variables found[/dim]")
                return

            table = Table(title="Variables")
            table.add_column("Name", style="cyan")
            table.add_column("Value")

            for v in variables:
                table.add_row(safe_rich(v.name), safe_rich(v.data))

            console.print(table)

    def print_mutation(self, action: str, name: str) -> None:
        """Print mutation result (create/update/delete).

        Args:
            action: The action performed (e.g., 'created', 'updated', 'deleted')
            name: The name of the resource affected
        """
        if self.format_type == "json":
            click.echo(
                json.dumps(
                    {"action": terminal_safe(action), "name": terminal_safe(name)},
                    indent=2,
                )
            )
        elif self.format_type == "simple":
            click.echo(f"{terminal_safe(action)}: {terminal_safe(name)}")
        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["action", "name"])
            writer.writerow([csv_safe(action), csv_safe(name)])
            click.echo(output.getvalue().rstrip())
        else:  # table (default)
            # Capitalize first letter for display
            display_action = action.capitalize()
            console.print(f"[green]{display_action}:[/green] {safe_rich(name)}")

    def print_workflows(self, workflows: list[Any]) -> None:
        """Print workflow list."""
        if self.format_type == "json":
            output_data = [
                {
                    "id": terminal_safe(w.id),
                    "name": terminal_safe(w.name),
                    "path": terminal_safe(w.path),
                    "state": terminal_safe(w.state),
                    # Emit null for missing timestamps (more accurate than "")
                    "created_at": terminal_safe(w.created_at) if w.created_at else None,
                    "updated_at": terminal_safe(w.updated_at) if w.updated_at else None,
                }
                for w in workflows
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for w in workflows:
                click.echo(f"{terminal_safe(w.id)} {terminal_safe(w.name)}")

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "name", "path", "state"])
            for w in workflows:
                writer.writerow([
                    csv_safe(w.id),
                    csv_safe(w.name),
                    csv_safe(w.path),
                    csv_safe(w.state),
                ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not workflows:
                console.print("[dim]No workflows found[/dim]")
                return

            table = Table(title="Workflows")
            table.add_column("ID", style="cyan")
            table.add_column("Name")
            table.add_column("Path", style="dim")
            table.add_column("State")

            for w in workflows:
                state_style = "green" if w.state == "active" else "yellow"
                table.add_row(
                    safe_rich(w.id),
                    safe_rich(w.name),
                    safe_rich(w.path),
                    f"[{state_style}]{safe_rich(w.state)}[/{state_style}]",
                )
            console.print(table)

    def print_runs(self, runs: list[Any]) -> None:
        """Print workflow runs list."""
        if self.format_type == "json":
            output_data = [
                {
                    "id": r.id,
                    "run_number": r.run_number,
                    "status": terminal_safe(r.status),
                    "conclusion": terminal_safe(r.conclusion) if r.conclusion else None,
                    "head_sha": terminal_safe(r.head_sha[:8]),
                    "head_branch": terminal_safe(r.head_branch),
                    "event": terminal_safe(r.event),
                    "display_title": terminal_safe(r.display_title),
                    "path": terminal_safe(r.path),
                    "started_at": terminal_safe(r.started_at) if r.started_at else None,
                    "html_url": terminal_safe(r.html_url),
                }
                for r in runs
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for r in runs:
                conclusion = r.conclusion or r.status
                sha = r.head_sha[:8] if r.head_sha else ""
                click.echo(
                    f"#{r.run_number} {terminal_safe(conclusion)} "
                    f"{terminal_safe(sha)} {terminal_safe(r.head_branch)}"
                )

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "id", "run_number", "status", "conclusion",
                "head_sha", "head_branch", "event", "path"
            ])
            for r in runs:
                writer.writerow([
                    r.id,
                    r.run_number,
                    csv_safe(r.status),
                    csv_safe(r.conclusion or ""),
                    csv_safe(r.head_sha[:8] if r.head_sha else ""),
                    csv_safe(r.head_branch),
                    csv_safe(r.event),
                    csv_safe(r.path),
                ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not runs:
                console.print("[dim]No workflow runs found[/dim]")
                return

            table = Table(title="Workflow Runs")
            table.add_column("#", style="cyan")
            table.add_column("Status")
            table.add_column("SHA", style="dim")
            table.add_column("Branch")
            table.add_column("Workflow")
            table.add_column("Event", style="dim")

            for r in runs:
                conclusion = r.conclusion or r.status
                if conclusion == "success":
                    status_str = "[green]✓ success[/green]"
                elif conclusion == "failure":
                    status_str = "[red]✗ failure[/red]"
                elif conclusion in ("cancelled", "skipped"):
                    status_str = f"[yellow]○ {safe_rich(conclusion)}[/yellow]"
                else:
                    status_str = f"[blue]● {safe_rich(r.status)}[/blue]"

                # Extract workflow name from path
                workflow_name = r.path.split("/")[-1] if r.path else ""

                table.add_row(
                    str(r.run_number),
                    status_str,
                    safe_rich(r.head_sha[:8] if r.head_sha else ""),
                    safe_rich(r.head_branch),
                    safe_rich(workflow_name),
                    safe_rich(r.event),
                )
            console.print(table)

    def print_run_status(self, runs: list[Any]) -> None:
        """Print workflow health status (latest run per workflow)."""
        # Group runs by workflow
        workflow_runs: dict[str, Any] = {}
        for r in runs:
            workflow_name = r.path.split("/")[-1] if r.path else "unknown"
            if workflow_name not in workflow_runs:
                workflow_runs[workflow_name] = r

        if self.format_type == "json":
            output_data = {
                wf: {
                    "run_id": r.id,
                    "run_number": r.run_number,
                    "status": terminal_safe(r.status),
                    "conclusion": terminal_safe(r.conclusion) if r.conclusion else None,
                    "head_sha": terminal_safe(r.head_sha[:8]),
                    "head_branch": terminal_safe(r.head_branch),
                    "started_at": terminal_safe(r.started_at) if r.started_at else None,
                }
                for wf, r in workflow_runs.items()
            }
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for wf, r in workflow_runs.items():
                conclusion = r.conclusion or r.status
                symbol = "✓" if conclusion == "success" else "✗"
                click.echo(
                    f"{terminal_safe(wf)}: {symbol} {terminal_safe(conclusion)} "
                    f"(#{r.run_number})"
                )

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "workflow", "status", "conclusion", "run_number", "head_sha"
            ])
            for wf, r in workflow_runs.items():
                writer.writerow([
                    csv_safe(wf),
                    csv_safe(r.status),
                    csv_safe(r.conclusion or ""),
                    r.run_number,
                    csv_safe(r.head_sha[:8] if r.head_sha else ""),
                ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not workflow_runs:
                console.print("[dim]No workflow runs found[/dim]")
                return

            for wf, r in workflow_runs.items():
                conclusion = r.conclusion or r.status
                if conclusion == "success":
                    status_str = "[green]✓ success[/green]"
                elif conclusion == "failure":
                    status_str = "[red]✗ failure[/red]"
                elif conclusion in ("cancelled", "skipped"):
                    status_str = f"[yellow]○ {safe_rich(conclusion)}[/yellow]"
                else:
                    status_str = f"[blue]● {safe_rich(r.status)}[/blue]"

                sha = r.head_sha[:8] if r.head_sha else ""
                console.print(
                    f"[bold]{safe_rich(wf)}[/bold]: {status_str} "
                    f"(#{r.run_number}, {safe_rich(sha)})"
                )

    def print_jobs(self, jobs: list[Any], errors_only: bool = False) -> None:
        """Print jobs list with steps."""
        if errors_only:
            jobs = [j for j in jobs if j.conclusion == "failure"]

        if self.format_type == "json":
            output_data = [
                {
                    "id": j.id,
                    "name": terminal_safe(j.name),
                    "status": terminal_safe(j.status),
                    "conclusion": terminal_safe(j.conclusion) if j.conclusion else None,
                    "runner_name": (
                        terminal_safe(j.runner_name) if j.runner_name else None
                    ),
                    "started_at": (
                        terminal_safe(j.started_at) if j.started_at else None
                    ),
                    "completed_at": (
                        terminal_safe(j.completed_at) if j.completed_at else None
                    ),
                    "steps": [
                        {
                            "number": s.number,
                            "name": terminal_safe(s.name),
                            "status": terminal_safe(s.status),
                            "conclusion": (
                                terminal_safe(s.conclusion) if s.conclusion else None
                            ),
                        }
                        for s in j.steps
                    ],
                }
                for j in jobs
            ]
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "simple":
            for j in jobs:
                conclusion = j.conclusion or j.status
                symbol = "✓" if conclusion == "success" else "✗"
                name = terminal_safe(j.name)
                click.echo(f"{symbol} {name} ({terminal_safe(conclusion)})")
                for s in j.steps:
                    step_conclusion = s.conclusion or s.status
                    step_symbol = "✓" if step_conclusion == "success" else "✗"
                    click.echo(f"  {step_symbol} {terminal_safe(s.name)}")

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "job_id", "job_name", "job_conclusion",
                "step_number", "step_name", "step_conclusion"
            ])
            for j in jobs:
                for s in j.steps:
                    writer.writerow([
                        j.id,
                        csv_safe(j.name),
                        csv_safe(j.conclusion or ""),
                        s.number,
                        csv_safe(s.name),
                        csv_safe(s.conclusion or ""),
                    ])
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not jobs:
                console.print("[dim]No jobs found[/dim]")
                return

            for j in jobs:
                conclusion = j.conclusion or j.status
                if conclusion == "success":
                    job_status = "[green]✓ success[/green]"
                elif conclusion == "failure":
                    job_status = "[red]✗ failure[/red]"
                else:
                    job_status = f"[blue]● {safe_rich(j.status)}[/blue]"

                runner = f" on {safe_rich(j.runner_name)}" if j.runner_name else ""
                job_name = safe_rich(j.name)
                console.print(f"\n[bold]{job_name}[/bold] {job_status}{runner}")

                if j.steps:
                    for s in j.steps:
                        step_conclusion = s.conclusion or s.status
                        if step_conclusion == "success":
                            step_status = "[green]✓[/green]"
                        elif step_conclusion == "failure":
                            step_status = "[red]✗[/red]"
                        elif step_conclusion == "skipped":
                            step_status = "[dim]○[/dim]"
                        else:
                            step_status = "[blue]●[/blue]"
                        console.print(f"  {step_status} {safe_rich(s.name)}")


# --- Main CLI Group ---


@click.group()
@click.version_option(__version__, prog_name="teax")
@click.option("--login", "-l", "login_name", help="Use specific tea login")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "simple", "csv", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def main(ctx: click.Context, login_name: str | None, output: str) -> None:
    """teax - Gitea CLI companion for tea feature gaps.

    Provides commands that tea CLI doesn't support:
    - Issue editing (labels, assignees, milestones)
    - Dependency management (blockers/blocked-by)
    - Bulk operations

    Uses tea's configuration for authentication.
    """
    ctx.ensure_object(dict)
    ctx.obj["login_name"] = login_name
    ctx.obj["output"] = OutputFormat(output)


# --- Dependencies Group ---


@main.group()
def deps() -> None:
    """Manage issue dependencies."""
    pass


@deps.command("list")
@click.argument("issue", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def deps_list(ctx: click.Context, issue: int, repo: str) -> None:
    """List dependencies for an issue.

    Shows both issues this depends on and issues this blocks.

    Example:
        teax deps list 25 --repo homelab/myproject
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            depends_on = client.list_dependencies(owner, repo_name, issue)
            blocks = client.list_blocks(owner, repo_name, issue)

            output.print_deps(depends_on, issue, "depends on")
            if blocks:
                console.print()
                output.print_deps(blocks, issue, "blocks")
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@deps.command("add")
@click.argument("issue", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--on", "depends_on", type=int, help="Issue number this depends on")
@click.option("--blocks", type=int, help="Issue number this blocks")
@click.pass_context
def deps_add(
    ctx: click.Context,
    issue: int,
    repo: str,
    depends_on: int | None,
    blocks: int | None,
) -> None:
    """Add a dependency relationship.

    Use --on to specify that ISSUE depends on another issue.
    Use --blocks to specify that ISSUE blocks another issue.

    Examples:
        teax deps add 25 --repo homelab/myproject --on 17
        teax deps add 17 --repo homelab/myproject --blocks 25
    """
    if depends_on is None and blocks is None:
        raise click.UsageError("Must specify either --on or --blocks")
    if depends_on is not None and blocks is not None:
        raise click.UsageError("Cannot specify both --on and --blocks")

    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            if depends_on is not None:
                # issue depends on depends_on
                client.add_dependency(
                    owner, repo_name, issue, owner, repo_name, depends_on
                )
                console.print(
                    f"[green]Added:[/green] #{issue} now depends on #{depends_on}"
                )
            else:
                # issue blocks 'blocks' -> blocks depends on issue
                assert blocks is not None
                client.add_dependency(owner, repo_name, blocks, owner, repo_name, issue)
                console.print(f"[green]Added:[/green] #{issue} now blocks #{blocks}")
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@deps.command("rm")
@click.argument("issue", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--on", "depends_on", type=int, help="Remove dependency on this issue")
@click.option("--blocks", type=int, help="Remove blocks relationship")
@click.pass_context
def deps_rm(
    ctx: click.Context,
    issue: int,
    repo: str,
    depends_on: int | None,
    blocks: int | None,
) -> None:
    """Remove a dependency relationship.

    Examples:
        teax deps rm 25 --repo homelab/myproject --on 17
    """
    if depends_on is None and blocks is None:
        raise click.UsageError("Must specify either --on or --blocks")
    if depends_on is not None and blocks is not None:
        raise click.UsageError("Cannot specify both --on and --blocks")

    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            if depends_on is not None:
                client.remove_dependency(
                    owner, repo_name, issue, owner, repo_name, depends_on
                )
                msg = f"#{issue} no longer depends on #{depends_on}"
                console.print(f"[yellow]Removed:[/yellow] {msg}")
            elif blocks is not None:
                client.remove_dependency(
                    owner, repo_name, blocks, owner, repo_name, issue
                )
                console.print(
                    f"[yellow]Removed:[/yellow] #{issue} no longer blocks #{blocks}"
                )
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Issue Group ---


@main.group()
def issue() -> None:
    """View and edit issues (labels, assignees, milestones)."""
    pass


@issue.command("view")
@click.argument("issue_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--comments", "-c", is_flag=True, help="Show comments")
@click.pass_context
def issue_view(
    ctx: click.Context, issue_num: int, repo: str, comments: bool
) -> None:
    """View issue details and optionally comments.

    Example:
        teax issue view 42 --repo owner/repo
        teax issue view 42 --repo owner/repo --comments
    """
    login_name = ctx.obj.get("login_name")
    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=login_name) as client:
            issue = client.get_issue(owner, repo_name, issue_num)

            # Header
            state_color = "green" if issue.state == "open" else "red"
            state_display = safe_rich(issue.state)
            console.print(
                f"[bold]#{issue.number}[/bold] {safe_rich(issue.title)} "
                f"[{state_color}]({state_display})[/{state_color}]"
            )
            console.print()

            # Labels
            if issue.labels and len(issue.labels) > 0:
                label_str = ", ".join(safe_rich(lb.name) for lb in issue.labels)
                console.print(f"[dim]Labels:[/dim] {label_str}")

            # Assignees
            if issue.assignees and len(issue.assignees) > 0:
                assignee_str = ", ".join(safe_rich(a.login) for a in issue.assignees)
                console.print(f"[dim]Assignees:[/dim] {assignee_str}")

            # Milestone
            if issue.milestone:
                ms_title = safe_rich(issue.milestone.title)
                console.print(f"[dim]Milestone:[/dim] {ms_title}")

            # Body (use markup=False to prevent Rich markup injection)
            if issue.body:
                console.print()
                console.print(terminal_safe(issue.body), markup=False)

            # Comments
            if comments:
                issue_comments = client.list_comments(owner, repo_name, issue_num)
                if issue_comments:
                    console.print()
                    count = len(issue_comments)
                    console.print(f"[bold]--- Comments ({count}) ---[/bold]")
                    for comment in issue_comments:
                        console.print()
                        # Sanitize all server-provided fields
                        date_display = safe_rich(comment.created_at[:10])
                        console.print(
                            f"[dim]{safe_rich(comment.user.login)} "
                            f"({date_display}):[/dim]"
                        )
                        # Use markup=False to prevent Rich markup injection
                        console.print(terminal_safe(comment.body), markup=False)
                else:
                    console.print()
                    console.print("[dim]No comments[/dim]")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("batch")
@click.argument("issues", type=str)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def issue_batch(ctx: click.Context, issues: str, repo: str) -> None:
    """View multiple issues at once.

    ISSUES can be:
      - Single: 17
      - Range: 17-23
      - List: 17,18,19
      - Mixed: 17-19,25,30-32

    Useful for automation tools like Claude Code that need to fetch
    multiple issue details in one operation.

    Examples:
        teax issue batch 1-5 --repo owner/repo
        teax issue batch "17,18,25-30" --repo owner/repo --output json
        teax -o json issue batch 1,2,3 --repo owner/repo
    """
    owner, repo_name = parse_repo(repo)
    issue_nums = parse_issue_spec(issues)
    output: OutputFormat = ctx.obj["output"]

    fetched_issues = []
    errors: dict[int, str] = {}

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            for issue_num in issue_nums:
                try:
                    issue = client.get_issue(owner, repo_name, issue_num)
                    fetched_issues.append(issue)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        errors[issue_num] = "Issue not found"
                    else:
                        errors[issue_num] = f"HTTP {e.response.status_code}"
                except httpx.RequestError as e:
                    errors[issue_num] = f"Request error: {type(e).__name__}"

            output.print_issues(fetched_issues, errors)

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)

    # Exit with error code if any issues failed
    if errors:
        sys.exit(1)


@issue.command("edit")
@click.argument("issue_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--add-labels", help="Labels to add (comma-separated)")
@click.option("--rm-labels", help="Labels to remove (comma-separated)")
@click.option("--set-labels", help="Replace all labels (comma-separated)")
@click.option("--assignees", help="Set assignees (comma-separated usernames)")
@click.option("--milestone", help="Set milestone (ID, empty to clear)")
@click.option("--title", help="Set new title")
@click.option("--body", help="Set new body text")
@click.pass_context
def issue_edit(
    ctx: click.Context,
    issue_num: int,
    repo: str,
    add_labels: str | None,
    rm_labels: str | None,
    set_labels: str | None,
    assignees: str | None,
    milestone: str | None,
    title: str | None,
    body: str | None,
) -> None:
    """Edit an existing issue.

    Examples:
        teax issue edit 25 --repo homelab/myproject --add-labels "epic/foo,prio/p1"
        teax issue edit 25 --repo homelab/myproject --rm-labels "needs-triage"
        teax issue edit 25 --repo homelab/myproject --assignees "user1,user2"
        teax issue edit 25 --repo homelab/myproject --milestone 5
        teax issue edit 25 --repo homelab/myproject --body "Updated description"
    """
    owner, repo_name = parse_repo(repo)
    changes_made = []

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Handle labels
            if set_labels is not None:
                labels = [s.strip() for s in set_labels.split(",") if s.strip()]
                client.set_issue_labels(owner, repo_name, issue_num, labels)
                changes_made.append(f"labels set to: {', '.join(labels)}")

            if add_labels is not None:
                labels = [s.strip() for s in add_labels.split(",") if s.strip()]
                client.add_issue_labels(owner, repo_name, issue_num, labels)
                changes_made.append(f"labels added: {', '.join(labels)}")

            if rm_labels is not None:
                labels = [s.strip() for s in rm_labels.split(",") if s.strip()]
                for label in labels:
                    client.remove_issue_label(owner, repo_name, issue_num, label)
                changes_made.append(f"labels removed: {', '.join(labels)}")

            # Handle other edits
            edit_kwargs: dict[str, Any] = {}
            if title is not None:
                edit_kwargs["title"] = title
                changes_made.append(f"title: {title}")

            if body is not None:
                edit_kwargs["body"] = body
                # Truncate body preview for change log
                preview = body[:50] + "..." if len(body) > 50 else body
                changes_made.append(f"body: {preview}")

            if assignees is not None:
                usernames = [u.strip() for u in assignees.split(",") if u.strip()]
                edit_kwargs["assignees"] = usernames
                changes_made.append(f"assignees: {', '.join(usernames)}")

            if milestone is not None:
                if milestone == "" or milestone.lower() == "none":
                    edit_kwargs["milestone"] = 0
                    changes_made.append("milestone: cleared")
                else:
                    # Resolve milestone by ID or name
                    milestone_id = client.resolve_milestone(owner, repo_name, milestone)
                    edit_kwargs["milestone"] = milestone_id
                    changes_made.append(f"milestone: {milestone}")

            if edit_kwargs:
                client.edit_issue(owner, repo_name, issue_num, **edit_kwargs)

            if changes_made:
                console.print(f"[green]Updated issue #{issue_num}:[/green]")
                for change in changes_made:
                    console.print(f"  - {safe_rich(change)}")
            else:
                console.print("[yellow]No changes specified[/yellow]")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("labels")
@click.argument("issue_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def issue_labels(ctx: click.Context, issue_num: int, repo: str) -> None:
    """List labels on an issue.

    Example:
        teax issue labels 25 --repo homelab/myproject
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            labels = client.get_issue_labels(owner, repo_name, issue_num)
            output.print_labels(labels)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("bulk")
@click.argument("issues", type=str)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--add-labels", help="Labels to add (comma-separated)")
@click.option("--rm-labels", help="Labels to remove (comma-separated)")
@click.option("--set-labels", help="Replace all labels (comma-separated)")
@click.option("--assignees", help="Set assignees (comma-separated usernames)")
@click.option("--milestone", help="Set milestone (ID, empty to clear)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def issue_bulk(
    ctx: click.Context,
    issues: str,
    repo: str,
    add_labels: str | None,
    rm_labels: str | None,
    set_labels: str | None,
    assignees: str | None,
    milestone: str | None,
    yes: bool,
) -> None:
    """Apply changes to multiple issues.

    ISSUES can be:
      - Single: 17
      - Range: 17-23
      - List: 17,18,19
      - Mixed: 17-19,25,30-32

    Examples:
        teax issue bulk 17-23 --repo owner/repo --add-labels "epic/foo"
        teax issue bulk "17,18,25-30" --repo owner/repo --assignees "user1"
        teax issue bulk 17-20 --repo owner/repo --milestone 5
    """
    owner, repo_name = parse_repo(repo)
    issue_nums = parse_issue_spec(issues)

    if not any([add_labels, rm_labels, set_labels, assignees, milestone]):
        console.print("[yellow]No changes specified[/yellow]")
        return

    # Build change preview
    changes: list[str] = []
    if set_labels is not None:
        changes.append(f"Set labels to: {set_labels}")
    if add_labels is not None:
        changes.append(f"Add labels: {add_labels}")
    if rm_labels is not None:
        changes.append(f"Remove labels: {rm_labels}")
    if assignees is not None:
        changes.append(f"Set assignees: {assignees}")
    if milestone is not None:
        if milestone == "" or milestone.lower() == "none":
            changes.append("Clear milestone")
        else:
            changes.append(f"Set milestone: {milestone}")

    # Show preview
    esc_repo = safe_rich(repo)
    console.print(f"\n[bold]Bulk edit {len(issue_nums)} issues in {esc_repo}[/bold]")
    console.print(f"Issues: {', '.join(f'#{n}' for n in issue_nums[:10])}", end="")
    if len(issue_nums) > 10:
        console.print(f" ... and {len(issue_nums) - 10} more")
    else:
        console.print()
    console.print("\n[bold]Changes:[/bold]")
    for change in changes:
        console.print(f"  • {safe_rich(change)}")
    console.print()

    # Confirm unless --yes
    if not yes:
        if not click.confirm("Proceed with changes?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    success_count = 0
    error_count = 0

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Pre-validate milestone if provided (fail fast before any changes)
            milestone_id: int | None = None
            needs_milestone = (
                milestone is not None
                and milestone != ""
                and milestone.lower() != "none"
            )
            if needs_milestone:
                assert milestone is not None  # Type guard: checked in needs_milestone
                try:
                    milestone_id = client.resolve_milestone(
                        owner, repo_name, milestone
                    )
                except (ValueError, httpx.HTTPStatusError) as e:
                    if isinstance(e, httpx.HTTPStatusError):
                        if e.response.status_code == 404:
                            err_console.print(
                                f"[red]Error:[/red] Milestone "
                                f"'{safe_rich(milestone)}' not found"
                            )
                        else:
                            err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
                    else:
                        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
                    sys.exit(1)
            for issue_num in issue_nums:
                try:
                    # Handle labels
                    if set_labels is not None:
                        labels = [s.strip() for s in set_labels.split(",") if s.strip()]
                        client.set_issue_labels(owner, repo_name, issue_num, labels)

                    if add_labels is not None:
                        labels = [s.strip() for s in add_labels.split(",") if s.strip()]
                        client.add_issue_labels(owner, repo_name, issue_num, labels)

                    if rm_labels is not None:
                        labels = [s.strip() for s in rm_labels.split(",") if s.strip()]
                        for label in labels:
                            client.remove_issue_label(
                                owner, repo_name, issue_num, label
                            )

                    # Handle other edits
                    edit_kwargs: dict[str, Any] = {}

                    if assignees is not None:
                        parts = assignees.split(",")
                        usernames = [u.strip() for u in parts if u.strip()]
                        edit_kwargs["assignees"] = usernames

                    if milestone is not None:
                        if milestone == "" or milestone.lower() == "none":
                            edit_kwargs["milestone"] = 0
                        else:
                            # Use pre-validated milestone_id
                            edit_kwargs["milestone"] = milestone_id

                    if edit_kwargs:
                        client.edit_issue(owner, repo_name, issue_num, **edit_kwargs)

                    console.print(f"  [green]✓[/green] #{issue_num}")
                    success_count += 1

                except CLI_ERRORS as e:
                    console.print(f"  [red]✗[/red] #{issue_num}: {safe_rich(str(e))}")
                    error_count += 1

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)

    # Print summary
    console.print()
    console.print(
        f"[bold]Summary:[/bold] {success_count} succeeded, {error_count} failed"
    )

    if error_count > 0:
        sys.exit(1)


# --- Epic Group ---


@main.group()
def epic() -> None:
    """Manage epic issues (parent issues tracking multiple child issues)."""
    pass


@epic.command("create")
@click.argument("name")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--title", "-t", help="Epic title (default: 'Epic: {name}')")
@click.option(
    "--child", "-c", "children", multiple=True, type=int, help="Child issue numbers"
)
@click.option("--color", default="9b59b6", help="Label color (hex, default: purple)")
@click.pass_context
def epic_create(
    ctx: click.Context,
    name: str,
    repo: str,
    title: str | None,
    children: tuple[int, ...],
    color: str,
) -> None:
    """Create a new epic with optional child issues.

    Creates:
    1. An epic/{name} label (if it doesn't exist)
    2. A new issue with the epic template
    3. Applies labels to the epic and any specified child issues

    NAME is used for both the label (epic/{name}) and default title.

    Examples:
        teax epic create diagnostics --repo homelab/myproject
        teax epic create auth --repo owner/repo --title "Auth System" -c 17 -c 18
        teax epic create refactor --repo owner/repo --child 25 --child 26
    """
    owner, repo_name = parse_repo(repo)
    epic_label = f"epic/{name}"
    epic_title = title or f"Epic: {name}"

    # Validate hex color format
    import re

    if not re.match(r"^[0-9a-fA-F]{6}$", color):
        safe_color = terminal_safe(color)
        raise click.BadParameter(
            f"Color must be a 6-character hex code (e.g., 'ff0000'), got: {safe_color}"
        )

    # Deduplicate and sort children
    unique_children = sorted(set(children))
    if len(unique_children) < len(children):
        console.print(
            f"[yellow]Warning:[/yellow] Duplicate child issues removed "
            f"({len(children)} → {len(unique_children)})"
        )

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Check if epic label exists, create if not
            existing_labels = client.list_repo_labels(owner, repo_name)
            label_names = {label.name: label.id for label in existing_labels}

            if epic_label not in label_names:
                console.print(f"Creating label [cyan]{safe_rich(epic_label)}[/cyan]...")
                created_label = client.create_label(
                    owner, repo_name, epic_label, color, f"Epic: {name}"
                )
                label_names[epic_label] = created_label.id
                console.print(f"  [green]✓[/green] Created label #{created_label.id}")

            # Build the epic body with checklist if there are children
            body_lines = [f"# {epic_title}", "", "## Child Issues", ""]
            if unique_children:
                for child_num in unique_children:
                    body_lines.append(f"- [ ] #{child_num}")
            else:
                body_lines.append(
                    "_No child issues yet. Use `teax epic add` to add issues._"
                )
            body_lines.extend(["", "---", f"_Tracked by label: `{epic_label}`_"])
            body = "\n".join(body_lines)

            # Get label IDs for the epic
            type_epic_id = label_names.get("type/epic")
            epic_label_id = label_names[epic_label]
            issue_labels = [epic_label_id]
            if type_epic_id:
                issue_labels.insert(0, type_epic_id)

            # Create the epic issue
            esc_title = safe_rich(epic_title)
            console.print(f"Creating epic issue [cyan]{esc_title}[/cyan]...")
            issue = client.create_issue(
                owner, repo_name, epic_title, body, labels=issue_labels
            )
            console.print(f"  [green]✓[/green] Created issue #{issue.number}")

            # Apply epic label to child issues
            if unique_children:
                escaped_label = safe_rich(epic_label)
                console.print(f"Applying [cyan]{escaped_label}[/cyan] to child issues…")
                for child_num in unique_children:
                    try:
                        client.add_issue_labels(
                            owner, repo_name, child_num, [epic_label]
                        )
                        console.print(f"  [green]✓[/green] #{child_num}")
                    except CLI_ERRORS as e:
                        esc_err = safe_rich(str(e))
                        console.print(f"  [red]✗[/red] #{child_num}: {esc_err}")

            # Print summary
            console.print()
            console.print("[bold]Epic created successfully![/bold]")
            console.print(f"  Issue: #{issue.number}")
            console.print(f"  Label: {safe_rich(epic_label)}")
            if unique_children:
                console.print(f"  Children: {len(unique_children)} issues labeled")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


def _parse_epic_children(body: str) -> list[int]:
    """Parse child issue numbers from epic body.

    Looks for checklist items like:
        - [ ] #17
        - [x] #18
        - [ ] #19 Some title

    Returns:
        List of issue numbers found
    """
    import re

    pattern = r"^- \[[x ]\] #(\d+)"
    matches = re.findall(pattern, body, re.MULTILINE)
    return [int(m) for m in matches]


@epic.command("status")
@click.argument("issue", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def epic_status(
    ctx: click.Context,
    issue: int,
    repo: str,
) -> None:
    """Show status and progress of an epic.

    Parses the epic issue body for child issue references (checklist items)
    and displays their current states with progress percentage.

    ISSUE is the epic issue number.

    Examples:
        teax epic status 25 --repo owner/repo
        teax epic status 100 -r homelab/project
    """
    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Fetch the epic issue
            epic_issue = client.get_issue(owner, repo_name, issue)

            # Parse child issues from body (deduplicate while preserving order)
            parsed = _parse_epic_children(epic_issue.body or "")
            child_nums = list(dict.fromkeys(parsed))

            if not child_nums:
                esc_title = safe_rich(epic_issue.title)
                console.print(f"[bold]Epic #{issue}:[/bold] {esc_title}")
                console.print("[yellow]No child issues found in epic body[/yellow]")
                return

            # Fetch child issue states
            open_issues: list[tuple[int, str]] = []
            closed_issues: list[tuple[int, str]] = []

            for child_num in child_nums:
                try:
                    child = client.get_issue(owner, repo_name, child_num)
                    if child.state == "closed":
                        closed_issues.append((child_num, child.title))
                    else:
                        open_issues.append((child_num, child.title))
                except httpx.HTTPStatusError:
                    open_issues.append((child_num, "(unable to fetch)"))

            total = len(child_nums)
            completed = len(closed_issues)
            percentage = (completed / total * 100) if total > 0 else 0

            # Display status
            esc_title = safe_rich(epic_issue.title)
            console.print(f"\n[bold]Epic #{issue}:[/bold] {esc_title}")
            pct = f"{percentage:.0f}%"
            console.print(f"[bold]Progress:[/bold] {completed}/{total} ({pct})")

            # Progress bar
            bar_width = 30
            filled = int(bar_width * completed / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_width - filled)
            console.print(f"[green]{bar}[/green]")

            # List issues by state
            if closed_issues:
                console.print(f"\n[green]Completed ({len(closed_issues)}):[/green]")
                for num, title in closed_issues:
                    console.print(f"  [green]✓[/green] #{num} {safe_rich(title)}")

            if open_issues:
                console.print(f"\n[yellow]Open ({len(open_issues)}):[/yellow]")
                for num, title in open_issues:
                    console.print(f"  [ ] #{num} {safe_rich(title)}")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


def _append_children_to_body(body: str, new_children: list[int]) -> str:
    """Append new child issues to epic body.

    Finds the "## Child Issues" section and appends new checklist items.
    If no section found, creates one.

    Args:
        body: Existing epic body
        new_children: Issue numbers to add

    Returns:
        Updated body text
    """
    import re

    # Build new checklist items
    new_items = "\n".join(f"- [ ] #{n}" for n in new_children)

    # Look for ## Child Issues section
    pattern = r"(## Child Issues\s*\n)"
    match = re.search(pattern, body)

    if match:
        # Find where to insert (after existing checklist items or placeholder)
        section_start = match.end()
        # Find the next section (## or ---) or end of string
        next_section = re.search(r"\n(##|---)", body[section_start:])
        if next_section:
            insert_pos = section_start + next_section.start()
        else:
            insert_pos = len(body)

        # Check if there's placeholder text to remove
        placeholder = "_No child issues yet."
        placeholder_match = re.search(
            re.escape(placeholder) + r"[^\n]*\n?",
            body[section_start:insert_pos],
        )
        if placeholder_match:
            # Remove placeholder and insert new items
            pl_start = section_start + placeholder_match.start()
            pl_end = section_start + placeholder_match.end()
            return body[:pl_start] + new_items + "\n" + body[pl_end:]

        # Insert before next section, ensuring newline separation
        return body[:insert_pos].rstrip() + "\n" + new_items + "\n" + body[insert_pos:]
    else:
        # No section found, append at end
        return body.rstrip() + "\n\n## Child Issues\n\n" + new_items + "\n"


@epic.command("add")
@click.argument("epic_issue", type=int)
@click.argument("children", type=int, nargs=-1, required=True)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def epic_add(
    ctx: click.Context,
    epic_issue: int,
    children: tuple[int, ...],
    repo: str,
) -> None:
    """Add issues to an existing epic.

    Appends child issues to the epic's checklist and applies the epic's label
    to each child issue.

    EPIC_ISSUE is the epic issue number.
    CHILDREN are the issue numbers to add to the epic.

    Examples:
        teax epic add 25 17 18 19 --repo owner/repo
        teax epic add 100 42 -r homelab/project
    """
    owner, repo_name = parse_repo(repo)

    # Deduplicate and sort children
    unique_children = sorted(set(children))
    if len(unique_children) < len(children):
        console.print(
            f"[yellow]Warning:[/yellow] Duplicate child issues removed "
            f"({len(children)} → {len(unique_children)})"
        )

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Fetch the epic issue
            epic = client.get_issue(owner, repo_name, epic_issue)

            # Find the epic label from the issue's labels
            epic_label = None
            for label in epic.labels or []:
                if label.name.startswith("epic/"):
                    epic_label = label.name
                    break

            if not epic_label:
                console.print(
                    f"[yellow]Warning:[/yellow] No epic/* label found on #{epic_issue}"
                )

            # Filter out children already in the epic body
            existing_children = set(_parse_epic_children(epic.body or ""))
            new_children = [c for c in unique_children if c not in existing_children]

            if not new_children:
                console.print(
                    "[yellow]Warning:[/yellow] All specified issues are already "
                    "in the epic"
                )
                return

            if len(new_children) < len(unique_children):
                skipped = len(unique_children) - len(new_children)
                console.print(
                    f"[yellow]Warning:[/yellow] {skipped} issue(s) already in epic, "
                    "skipping"
                )

            # Update the epic body with new children
            new_body = _append_children_to_body(epic.body, new_children)
            client.edit_issue(owner, repo_name, epic_issue, body=new_body)
            console.print(f"[green]✓[/green] Updated epic #{epic_issue} body")

            # Apply epic label to child issues
            if epic_label:
                escaped = safe_rich(epic_label)
                console.print(f"Applying [cyan]{escaped}[/cyan] to child issues...")
                for child_num in new_children:
                    try:
                        client.add_issue_labels(
                            owner, repo_name, child_num, [epic_label]
                        )
                        console.print(f"  [green]✓[/green] #{child_num}")
                    except CLI_ERRORS as e:
                        esc_err = safe_rich(str(e))
                        console.print(f"  [red]✗[/red] #{child_num}: {esc_err}")

            # Print summary
            console.print()
            count = len(new_children)
            console.print(f"[bold]Added {count} issues to epic #{epic_issue}[/bold]")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Runners Group ---


def validate_scope(
    repo: str | None, org: str | None, global_scope: bool
) -> tuple[str | None, str | None, str | None, bool]:
    """Validate and parse scope options.

    Args:
        repo: Repository in owner/repo format
        org: Organisation name
        global_scope: If True, use global scope

    Returns:
        Tuple of (owner, repo_name, org, global_scope)

    Raises:
        click.UsageError: If scope is invalid
    """
    scope_count = sum([bool(repo), bool(org), global_scope])

    if scope_count == 0:
        raise click.UsageError("Must specify --repo, --org, or --global")
    if scope_count > 1:
        raise click.UsageError("Specify only one of --repo, --org, or --global")

    owner = None
    repo_name = None
    if repo:
        owner, repo_name = parse_repo(repo)

    return owner, repo_name, org, global_scope


@main.group()
def runners() -> None:
    """Manage Gitea Actions runners."""
    pass


@runners.command("list")
@click.option("--repo", "-r", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--global", "global_scope", is_flag=True, help="Global scope (admin)")
@click.pass_context
def runners_list(
    ctx: click.Context, repo: str | None, org: str | None, global_scope: bool
) -> None:
    """List runners for a repository, organisation, or globally.

    Specify scope with --repo, --org, or --global.

    Examples:
        teax runners list --repo owner/repo
        teax runners list --org myorg
        teax runners list --global
    """
    owner, repo_name, org_name, is_global = validate_scope(repo, org, global_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            runner_list = client.list_runners(
                owner=owner,
                repo=repo_name,
                org=org_name,
                global_scope=is_global,
            )
            output.print_runners(runner_list)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runners.command("get")
@click.argument("runner_id", type=int)
@click.option("--repo", "-r", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--global", "global_scope", is_flag=True, help="Global scope (admin)")
@click.pass_context
def runners_get(
    ctx: click.Context,
    runner_id: int,
    repo: str | None,
    org: str | None,
    global_scope: bool,
) -> None:
    """Get details for a specific runner.

    Examples:
        teax runners get 42 --repo owner/repo
        teax runners get 42 --org myorg
    """
    owner, repo_name, org_name, is_global = validate_scope(repo, org, global_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            runner = client.get_runner(
                runner_id,
                owner=owner,
                repo=repo_name,
                org=org_name,
                global_scope=is_global,
            )
            # Print as single-item list for consistent formatting
            output.print_runners([runner])
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runners.command("delete")
@click.argument("runner_id", type=int)
@click.option("--repo", "-r", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--global", "global_scope", is_flag=True, help="Global scope (admin)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def runners_delete(
    ctx: click.Context,
    runner_id: int,
    repo: str | None,
    org: str | None,
    global_scope: bool,
    yes: bool,
) -> None:
    """Delete a runner.

    Examples:
        teax runners delete 42 --repo owner/repo
        teax runners delete 42 --org myorg -y
    """
    owner, repo_name, org_name, is_global = validate_scope(repo, org, global_scope)

    # Build scope description for confirmation (sanitize user input)
    if is_global:
        scope_desc = "global"
    elif org_name:
        scope_desc = f"org '{terminal_safe(org_name)}'"
    else:
        scope_desc = f"repo '{terminal_safe(repo or '')}'"

    if not yes:
        if not click.confirm(f"Delete runner {runner_id} from {scope_desc}?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.delete_runner(
                runner_id,
                owner=owner,
                repo=repo_name,
                org=org_name,
                global_scope=is_global,
            )
            console.print(f"[green]Deleted runner {runner_id}[/green]")
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runners.command("token")
@click.option("--repo", "-r", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--global", "global_scope", is_flag=True, help="Global scope (admin)")
@click.pass_context
def runners_token(
    ctx: click.Context, repo: str | None, org: str | None, global_scope: bool
) -> None:
    """Get a runner registration token.

    The token is used to register new runners with act_runner.

    Examples:
        teax runners token --repo owner/repo
        teax runners token --org myorg
        teax runners token --global

    Use with act_runner:
        act_runner register --token $(teax -o simple runners token -r owner/repo)
    """
    owner, repo_name, org_name, is_global = validate_scope(repo, org, global_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            token = client.get_runner_registration_token(
                owner=owner,
                repo=repo_name,
                org=org_name,
                global_scope=is_global,
            )

            if output.format_type == "simple":
                # Simple format - just the token (for scripting)
                click.echo(terminal_safe(token.token))
            elif output.format_type == "json":
                click.echo(json.dumps({"token": terminal_safe(token.token)}, indent=2))
            elif output.format_type == "csv":
                click.echo("token")
                click.echo(csv_safe(token.token))
            else:  # table
                # Show warning in table mode (interactive)
                console.print(
                    "[yellow]Warning:[/yellow] This token should be kept secret. "
                    "Use -o simple for scripting."
                )
                console.print()
                token_display = safe_rich(token.token)
                console.print(f"[bold]Registration Token:[/bold] {token_display}")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Package Group ---


@main.group()
def pkg() -> None:
    """Manage Gitea packages (PyPI, Container, Generic, etc.)."""
    pass


@pkg.command("list")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", help="Filter by type (pypi, container, etc.)")
@click.pass_context
def pkg_list(ctx: click.Context, owner: str, pkg_type: str | None) -> None:
    """List packages for an owner.

    Examples:
        teax pkg list --owner homelab-teams
        teax pkg list --owner homelab-teams --type pypi
        teax pkg list --owner myuser --type container -o json
    """
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            packages = client.list_packages(owner, pkg_type)
            output.print_packages(packages)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@pkg.command("info")
@click.argument("name")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", required=True, help="Package type")
@click.pass_context
def pkg_info(ctx: click.Context, name: str, owner: str, pkg_type: str) -> None:
    """Show package info with all versions.

    NAME is the package name.

    Examples:
        teax pkg info teax --owner homelab-teams --type pypi
        teax pkg info myimage --owner homelab-teams --type container
    """
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            versions = client.list_package_versions(owner, pkg_type, name)
            output.print_package_versions(name, pkg_type, versions)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@pkg.command("delete")
@click.argument("name")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", required=True, help="Package type")
@click.option("--version", "-v", "version", required=True, help="Version to delete")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def pkg_delete(
    ctx: click.Context,
    name: str,
    owner: str,
    pkg_type: str,
    version: str,
    yes: bool,
) -> None:
    """Delete a specific package version.

    NAME is the package name.

    NOTE: PyPI packages cannot be deleted via API (Gitea limitation).
    Use the Gitea web UI for PyPI package deletion.

    Examples:
        teax pkg delete mypkg -o homelab-teams --type generic -v 1.0.0
        teax pkg delete myimage -o homelab-teams --type container -v latest -y
    """
    # Check for PyPI upfront with helpful message
    if pkg_type.lower() == "pypi":
        err_console.print(
            "[red]Error:[/red] PyPI packages cannot be deleted via API "
            "(Gitea limitation).\n"
            "Use the Gitea web UI: Settings → Packages → Delete.\n"
            "See: https://github.com/go-gitea/gitea/issues/22303"
        )
        sys.exit(1)

    # Build safe strings for display
    # Use terminal_safe for plain text output (click.confirm)
    safe_name_plain = terminal_safe(name)
    safe_type_plain = terminal_safe(pkg_type)
    safe_version_plain = terminal_safe(version)
    safe_owner_plain = terminal_safe(owner)
    # Use safe_rich for Rich markup output (console.print)
    safe_name_rich = safe_rich(name)
    safe_type_rich = safe_rich(pkg_type)
    safe_version_rich = safe_rich(version)

    if not yes:
        if not click.confirm(
            f"Delete {safe_type_plain}/{safe_name_plain}:{safe_version_plain} "
            f"from {safe_owner_plain}?"
        ):
            console.print("[yellow]Aborted[/yellow]")
            return

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.delete_package_version(owner, pkg_type, name, version)
            console.print(
                f"[green]Deleted:[/green] "
                f"{safe_type_rich}/{safe_name_rich}:{safe_version_rich}"
            )
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@pkg.command("prune")
@click.argument("name")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", required=True, help="Package type")
@click.option("--keep", "-k", type=int, default=3, help="Versions to keep (default: 3)")
@click.option("--execute", is_flag=True, help="Actually delete (default: dry-run)")
@click.pass_context
def pkg_prune(
    ctx: click.Context,
    name: str,
    owner: str,
    pkg_type: str,
    keep: int,
    execute: bool,
) -> None:
    """Prune old package versions, keeping the N most recent.

    NAME is the package name.

    By default, runs in dry-run mode showing what would be deleted.
    Use --execute to actually delete the versions.

    NOTE: PyPI packages cannot be pruned via API (Gitea limitation).

    Examples:
        teax pkg prune myimage --owner homelab-teams --type container --keep 3
        teax pkg prune myimage --owner homelab-teams --type container --keep 3 --execute
    """
    # Check for PyPI upfront with helpful message
    if pkg_type.lower() == "pypi":
        err_console.print(
            "[red]Error:[/red] PyPI packages cannot be deleted via API "
            "(Gitea limitation).\n"
            "Use the Gitea web UI: Settings → Packages → Delete.\n"
            "See: https://github.com/go-gitea/gitea/issues/22303"
        )
        sys.exit(1)

    if keep < 0:
        raise click.BadParameter("--keep must be >= 0")

    output: OutputFormat = ctx.obj["output"]
    # Use stderr for status messages in machine-readable formats
    log = (
        err_console
        if output.format_type in ("json", "csv", "simple")
        else console
    )

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Get all versions (sorted by created_at descending by default)
            versions = client.list_package_versions(owner, pkg_type, name)

            if not versions:
                log.print("[dim]No versions found[/dim]")
                return

            # Split into keep and delete lists
            to_keep = versions[:keep]
            to_delete = versions[keep:]

            if not to_delete:
                msg = f"Nothing to prune - only {len(versions)} version(s) exist"
                log.print(f"[dim]{msg}[/dim]")
                return

            # Show preview
            output.print_prune_preview(name, pkg_type, to_delete, to_keep, execute)

            if execute:
                # Actually delete
                success_count = 0
                error_count = 0

                for v in to_delete:
                    try:
                        client.delete_package_version(
                            owner, pkg_type, name, v.version
                        )
                        ver = safe_rich(v.version)
                        log.print(f"  [green]✓[/green] Deleted {ver}")
                        success_count += 1
                    except CLI_ERRORS as e:
                        ver = safe_rich(v.version)
                        err = safe_rich(str(e))
                        log.print(f"  [red]✗[/red] {ver}: {err}")
                        error_count += 1

                log.print()
                msg = f"{success_count} deleted, {error_count} failed"
                log.print(f"[bold]Summary:[/bold] {msg}")

                if error_count > 0:
                    sys.exit(1)
            else:
                log.print()
                log.print(
                    "[dim]Use --execute to actually delete these versions[/dim]"
                )

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Secrets Group ---


# Pattern for valid secret/variable names: alphanumeric + underscores, no leading digit
_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_secret_name(name: str) -> str:
    """Validate and normalize a secret or variable name.

    Names must be alphanumeric with underscores, and cannot start with a digit.
    This matches GitHub Actions and Gitea's naming requirements.

    Raises:
        click.BadParameter: If name is invalid
    """
    name = name.strip()
    if not name:
        raise click.BadParameter("Name cannot be empty")
    if not _NAME_PATTERN.match(name):
        raise click.BadParameter(
            f"Invalid name '{terminal_safe(name)}': must contain only letters, "
            "numbers, and underscores, and cannot start with a number"
        )
    return name


def validate_secrets_scope(
    repo: str | None, org: str | None, user_scope: bool
) -> tuple[str | None, str | None, str | None, bool]:
    """Validate and parse scope options for secrets/variables.

    Args:
        repo: Repository in owner/repo format
        org: Organisation name
        user_scope: If True, use user-level scope

    Returns:
        Tuple of (owner, repo_name, org, user_scope)

    Raises:
        click.UsageError: If scope is invalid
    """
    scope_count = sum([bool(repo), bool(org), user_scope])

    if scope_count == 0:
        raise click.UsageError("Must specify --repo, --org, or --user")
    if scope_count > 1:
        raise click.UsageError("Specify only one of --repo, --org, or --user")

    owner = None
    repo_name = None
    org_name = None

    if repo:
        owner, repo_name = parse_repo(repo)
    elif org:
        # Validate and sanitize org name
        org_name = org.strip()
        if not org_name or "/" in org_name:
            raise click.BadParameter(
                f"Invalid organisation name: {terminal_safe(org)}"
            )

    return owner, repo_name, org_name, user_scope


@main.group()
def secrets() -> None:
    """Manage Gitea Actions secrets."""
    pass


@secrets.command("list")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.pass_context
def secrets_list(
    ctx: click.Context,
    repo: str | None,
    org: str | None,
    user_scope: bool,
) -> None:
    """List secrets (names only - values are never returned).

    Examples:
        teax secrets list --repo owner/repo
        teax secrets list --org myorg
        teax secrets list --user
    """
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            secrets_list = client.list_secrets(
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )
            output.print_secrets(secrets_list)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@secrets.command("set")
@click.argument("name")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.option(
    "--from-env",
    "env_var",
    help="Read value from environment variable",
)
@click.pass_context
def secrets_set(
    ctx: click.Context,
    name: str,
    repo: str | None,
    org: str | None,
    user_scope: bool,
    env_var: str | None,
) -> None:
    """Create or update a secret.

    The value can be provided via:
    - Interactive prompt (default, hidden input)
    - Stdin pipe: echo "value" | teax secrets set NAME -r owner/repo
    - Environment variable: teax secrets set NAME -r owner/repo --from-env MY_VAR

    Examples:
        teax secrets set DEPLOY_TOKEN --repo owner/repo
        teax secrets set API_KEY --org myorg --from-env MY_API_KEY
        echo "secret-value" | teax secrets set TOKEN --repo owner/repo
    """
    name = validate_secret_name(name)
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    # Get the secret value
    if env_var:
        value = os.environ.get(env_var)
        if value is None:
            err_console.print(
                f"[red]Error:[/red] Environment variable '{safe_rich(env_var)}' not set"
            )
            sys.exit(1)
    elif not sys.stdin.isatty():
        # Read from stdin (piped input)
        value = sys.stdin.read().rstrip("\n")
    else:
        # Interactive prompt with hidden input
        value = click.prompt("Secret value", hide_input=True, confirmation_prompt=True)

    if not value:
        err_console.print("[red]Error:[/red] Secret value cannot be empty")
        sys.exit(1)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            created = client.set_secret(
                name=name,
                value=value,
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )
            action = "created" if created else "updated"
            output.print_mutation(action, name)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@secrets.command("delete")
@click.argument("name")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def secrets_delete(
    ctx: click.Context,
    name: str,
    repo: str | None,
    org: str | None,
    user_scope: bool,
    yes: bool,
) -> None:
    """Delete a secret.

    Examples:
        teax secrets delete DEPLOY_TOKEN --repo owner/repo
        teax secrets delete API_KEY --org myorg -y
    """
    name = validate_secret_name(name)
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    if not yes:
        safe_name = terminal_safe(name)
        if not click.confirm(f"Delete secret '{safe_name}'?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.delete_secret(
                name=name,
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )
            output.print_mutation("deleted", name)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Variables Group ---


@main.group()
def vars() -> None:
    """Manage Gitea Actions variables."""
    pass


@vars.command("list")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.pass_context
def vars_list(
    ctx: click.Context,
    repo: str | None,
    org: str | None,
    user_scope: bool,
) -> None:
    """List variables.

    Examples:
        teax vars list --repo owner/repo
        teax vars list --org myorg
        teax vars list --user
    """
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            variables = client.list_variables(
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )
            output.print_variables(variables)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@vars.command("get")
@click.argument("name")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.pass_context
def vars_get(
    ctx: click.Context,
    name: str,
    repo: str | None,
    org: str | None,
    user_scope: bool,
) -> None:
    """Get a variable's value.

    Examples:
        teax vars get ENV_NAME --repo owner/repo
        teax -o simple vars get ENV_NAME --repo owner/repo  # Just the value
    """
    name = validate_secret_name(name)
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            variable = client.get_variable(
                name=name,
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )

            if output.format_type == "json":
                click.echo(
                    json.dumps(
                        {
                            "name": terminal_safe(variable.name),
                            "value": terminal_safe(variable.data),
                        },
                        indent=2,
                    )
                )
            elif output.format_type == "simple":
                click.echo(terminal_safe(variable.data))
            elif output.format_type == "csv":
                output_buf = io.StringIO()
                writer = csv.writer(output_buf)
                writer.writerow(["name", "value"])
                writer.writerow([csv_safe(variable.name), csv_safe(variable.data)])
                click.echo(output_buf.getvalue().rstrip())
            else:  # table
                console.print(f"[bold]{safe_rich(variable.name)}[/bold]")
                console.print(safe_rich(variable.data))

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@vars.command("set")
@click.argument("name")
@click.option("-v", "--value", required=True, help="Variable value")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.pass_context
def vars_set(
    ctx: click.Context,
    name: str,
    value: str,
    repo: str | None,
    org: str | None,
    user_scope: bool,
) -> None:
    """Create or update a variable.

    Examples:
        teax vars set ENV_NAME --value production --repo owner/repo
        teax vars set BUILD_FLAGS --value "-O2" --org myorg
    """
    name = validate_secret_name(name)
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            created = client.set_variable(
                name=name,
                value=value,
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )
            action = "created" if created else "updated"
            output.print_mutation(action, name)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@vars.command("delete")
@click.argument("name")
@click.option("-r", "--repo", help="Repository (owner/repo)")
@click.option("--org", help="Organisation name")
@click.option("--user", "user_scope", is_flag=True, help="User-level scope")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def vars_delete(
    ctx: click.Context,
    name: str,
    repo: str | None,
    org: str | None,
    user_scope: bool,
    yes: bool,
) -> None:
    """Delete a variable.

    Examples:
        teax vars delete ENV_NAME --repo owner/repo
        teax vars delete BUILD_FLAGS --org myorg -y
    """
    name = validate_secret_name(name)
    owner, repo_name, org_name, is_user = validate_secrets_scope(repo, org, user_scope)
    output: OutputFormat = ctx.obj["output"]

    if not yes:
        safe_name = terminal_safe(name)
        if not click.confirm(f"Delete variable '{safe_name}'?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.delete_variable(
                name=name,
                owner=owner,
                repo=repo_name,
                org=org_name,
                user_scope=is_user,
            )
            output.print_mutation("deleted", name)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Workflow Group ---


def parse_workflow_inputs(inputs: tuple[str, ...]) -> dict[str, str]:
    """Parse workflow input arguments.

    Accepts inputs in the format "key=value". The value can contain '=' signs.

    Args:
        inputs: Tuple of "key=value" strings from --input options

    Returns:
        Dict mapping input names to values

    Raises:
        click.BadParameter: If input format is invalid
    """
    result: dict[str, str] = {}
    for item in inputs:
        if "=" not in item:
            safe_item = terminal_safe(item)
            raise click.BadParameter(
                f"Invalid input format: '{safe_item}' (expected 'key=value')"
            )
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise click.BadParameter("Input key cannot be empty")
        result[key] = value
    return result


def validate_workflow_id(workflow_id: str) -> str:
    """Validate and normalize workflow_id.

    Args:
        workflow_id: Raw workflow ID from CLI

    Returns:
        Stripped workflow_id

    Raises:
        click.BadParameter: If workflow_id is empty or whitespace-only
    """
    workflow_id = workflow_id.strip()
    if not workflow_id:
        raise click.BadParameter(
            "Workflow ID cannot be empty or whitespace-only"
        )
    return workflow_id


@main.group()
def workflow() -> None:
    """Manage Gitea Actions workflows."""
    pass


@workflow.command("list")
@click.option("-r", "--repo", required=True, help="Repository (owner/repo)")
@click.pass_context
def workflow_list(ctx: click.Context, repo: str) -> None:
    """List workflows for a repository.

    Examples:
        teax workflow list --repo owner/repo
        teax workflow list -r owner/repo -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            workflows = client.list_workflows(owner, repo_name)
            output.print_workflows(workflows)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@workflow.command("get")
@click.argument("workflow_id")
@click.option("-r", "--repo", required=True, help="Repository (owner/repo)")
@click.pass_context
def workflow_get(ctx: click.Context, workflow_id: str, repo: str) -> None:
    """Get workflow details.

    WORKFLOW_ID can be a numeric ID or filename (e.g., "ci.yml").

    Examples:
        teax workflow get ci.yml --repo owner/repo
        teax workflow get 123 -r owner/repo
    """
    workflow_id = validate_workflow_id(workflow_id)
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            wf = client.get_workflow(owner, repo_name, workflow_id)
            # Print as single-item list for consistent formatting
            output.print_workflows([wf])
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@workflow.command("dispatch")
@click.argument("workflow_id")
@click.option("-r", "--repo", required=True, help="Repository (owner/repo)")
@click.option("--ref", required=True, help="Git reference (branch, tag, or SHA)")
@click.option(
    "-i", "--input", "inputs", multiple=True, help="Workflow input (key=value)"
)
@click.pass_context
def workflow_dispatch(
    ctx: click.Context,
    workflow_id: str,
    repo: str,
    ref: str,
    inputs: tuple[str, ...],
) -> None:
    """Dispatch a workflow run.

    WORKFLOW_ID can be a numeric ID or filename (e.g., "ci.yml").

    Examples:
        teax workflow dispatch ci.yml --repo owner/repo --ref main
        teax workflow dispatch deploy.yml -r owner/repo --ref main -i v=1.0
    """
    workflow_id = validate_workflow_id(workflow_id)
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    # Validate ref is not whitespace-only
    ref = ref.strip()
    if not ref:
        raise click.BadParameter("Git reference cannot be empty or whitespace-only")

    # Parse workflow inputs
    input_dict = parse_workflow_inputs(inputs) if inputs else None

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.dispatch_workflow(owner, repo_name, workflow_id, ref, input_dict)

            # Build success message
            safe_id = terminal_safe(workflow_id)
            safe_ref = terminal_safe(ref)

            if output.format_type == "json":
                # Sanitize input keys and values to prevent terminal injection
                safe_inputs = {
                    terminal_safe(k): terminal_safe(v)
                    for k, v in (input_dict or {}).items()
                }
                output_data = {
                    "action": "dispatched",
                    "workflow": safe_id,
                    "ref": safe_ref,
                    "inputs": safe_inputs,
                }
                click.echo(json.dumps(output_data, indent=2))
            elif output.format_type == "simple":
                click.echo(f"dispatched: {safe_id} on {safe_ref}")
            elif output.format_type == "csv":
                output_buf = io.StringIO()
                writer = csv.writer(output_buf)
                writer.writerow(["action", "workflow", "ref"])
                writer.writerow(["dispatched", csv_safe(workflow_id), csv_safe(ref)])
                click.echo(output_buf.getvalue().rstrip())
            else:  # table
                console.print(
                    f"[green]Dispatched:[/green] {safe_rich(workflow_id)} "
                    f"on ref [cyan]{safe_rich(ref)}[/cyan]"
                )
                if input_dict:
                    console.print("[dim]Inputs:[/dim]")
                    for k, v in input_dict.items():
                        console.print(f"  {safe_rich(k)}={safe_rich(v)}")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@workflow.command("enable")
@click.argument("workflow_id")
@click.option("-r", "--repo", required=True, help="Repository (owner/repo)")
@click.pass_context
def workflow_enable(ctx: click.Context, workflow_id: str, repo: str) -> None:
    """Enable a workflow.

    WORKFLOW_ID can be a numeric ID or filename (e.g., "ci.yml").

    Examples:
        teax workflow enable ci.yml --repo owner/repo
    """
    workflow_id = validate_workflow_id(workflow_id)
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.enable_workflow(owner, repo_name, workflow_id)
            output.print_mutation("enabled", workflow_id)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@workflow.command("disable")
@click.argument("workflow_id")
@click.option("-r", "--repo", required=True, help="Repository (owner/repo)")
@click.pass_context
def workflow_disable(ctx: click.Context, workflow_id: str, repo: str) -> None:
    """Disable a workflow.

    WORKFLOW_ID can be a numeric ID or filename (e.g., "ci.yml").

    Examples:
        teax workflow disable ci.yml --repo owner/repo
    """
    workflow_id = validate_workflow_id(workflow_id)
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.disable_workflow(owner, repo_name, workflow_id)
            output.print_mutation("disabled", workflow_id)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Runs Group ---


@main.group()
def runs() -> None:
    """Manage workflow runs - list, inspect, and debug CI/CD."""
    pass


@runs.command("status")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def runs_status(ctx: click.Context, repo: str) -> None:
    """Show workflow health status (latest run per workflow).

    Quick overview of CI/CD health for all workflows.

    Examples:
        teax runs status -r owner/repo
        teax runs status -r owner/repo -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            runs_list = client.list_runs(owner, repo_name, limit=50, max_pages=2)
            output.print_run_status(runs_list)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("list")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--workflow", "-w", help="Filter by workflow filename (e.g., ci.yml)")
@click.option("--branch", "-b", help="Filter by branch name")
@click.option("--status", "-s", help="Filter by status (queued, in_progress, etc.)")
@click.option("--limit", "-n", default=20, help="Number of results (default: 20)")
@click.pass_context
def runs_list(
    ctx: click.Context,
    repo: str,
    workflow: str | None,
    branch: str | None,
    status: str | None,
    limit: int,
) -> None:
    """List workflow runs for a repository.

    Examples:
        teax runs list -r owner/repo
        teax runs list -r owner/repo --workflow ci.yml
        teax runs list -r owner/repo --status failure --limit 5
        teax runs list -r owner/repo --branch main -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            runs_list = client.list_runs(
                owner, repo_name,
                workflow=workflow,
                branch=branch,
                status=status,
                limit=limit,
            )
            output.print_runs(runs_list)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("get")
@click.argument("run_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--errors-only", "-e", is_flag=True, help="Show only failed jobs/steps")
@click.pass_context
def runs_get(
    ctx: click.Context,
    run_id: int,
    repo: str,
    errors_only: bool,
) -> None:
    """Get workflow run details with jobs and steps.

    Examples:
        teax runs get 42 -r owner/repo
        teax runs get 42 -r owner/repo --errors-only
        teax runs get 42 -r owner/repo -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            jobs = client.list_run_jobs(owner, repo_name, run_id)
            output.print_jobs(jobs, errors_only=errors_only)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("jobs")
@click.argument("run_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--errors-only", "-e", is_flag=True, help="Show only failed jobs")
@click.pass_context
def runs_jobs(
    ctx: click.Context,
    run_id: int,
    repo: str,
    errors_only: bool,
) -> None:
    """List jobs for a workflow run.

    Examples:
        teax runs jobs 42 -r owner/repo
        teax runs jobs 42 -r owner/repo --errors-only
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            jobs = client.list_run_jobs(owner, repo_name, run_id)
            output.print_jobs(jobs, errors_only=errors_only)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


def filter_logs(
    logs: str,
    tail: int | None = None,
    head: int | None = None,
    grep: str | None = None,
    context: int = 0,
    strip_ansi: bool = False,
) -> str:
    """Filter log output with various options.

    Args:
        logs: Raw log content
        tail: Show last N lines (must be positive if set)
        head: Show first N lines (must be positive if set)
        grep: Regex pattern to filter lines
        context: Lines of context around grep matches (must be non-negative)
        strip_ansi: Remove all terminal escape sequences (uses terminal_safe)

    Returns:
        Filtered log content

    Raises:
        click.BadParameter: If grep pattern is invalid regex
    """
    if strip_ansi:
        # Use terminal_safe for comprehensive escape removal (OSC, CSI, DCS, etc.)
        logs = terminal_safe(logs)

    lines = logs.splitlines()

    # Validate context is non-negative
    context = max(0, context)

    if grep:
        # Find matching lines with context
        try:
            pattern = re.compile(grep, re.IGNORECASE)
        except re.error as e:
            raise click.BadParameter(
                f"Invalid regex pattern: {terminal_safe(str(e))}"
            ) from None
        matched_indices: set[int] = set()
        for i, line in enumerate(lines):
            if pattern.search(line):
                for j in range(max(0, i - context), min(len(lines), i + context + 1)):
                    matched_indices.add(j)
        lines = [lines[i] for i in sorted(matched_indices)]

    # Handle head/tail - only apply if positive
    if head is not None and head > 0:
        lines = lines[:head]
    elif tail is not None and tail > 0:
        lines = lines[-tail:]

    return '\n'.join(lines)


@runs.command("logs")
@click.argument("job_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--tail", "-t", type=int, help="Show last N lines")
@click.option("--head", "-H", type=int, help="Show first N lines")
@click.option("--grep", "-g", help="Filter lines matching pattern (regex)")
@click.option("--context", "-C", type=int, default=0, help="Context lines around grep")
@click.option("--strip-ansi", is_flag=True, help="Strip all escape sequences")
@click.option(
    "--raw", is_flag=True,
    help="Output exact server bytes (no filtering/sanitization)"
)
@click.pass_context
def runs_logs(
    ctx: click.Context,
    job_id: int,
    repo: str,
    tail: int | None,
    head: int | None,
    grep: str | None,
    context: int,
    strip_ansi: bool,
    raw: bool,
) -> None:
    """Get logs for a job.

    By default, escape sequences are sanitized for terminal safety.
    Use --raw for exact server output (no filtering - use with caution).
    Note: --raw is mutually exclusive with filtering options.

    Examples:
        teax runs logs 123 -r owner/repo
        teax runs logs 123 -r owner/repo --tail 100
        teax runs logs 123 -r owner/repo --grep "Error|FAILED" --context 5
        teax runs logs 123 -r owner/repo --raw
    """
    # Validate mutually exclusive options
    if raw and (
        strip_ansi
        or tail is not None
        or head is not None
        or grep
        or context
    ):
        err_console.print(
            "[red]Error:[/red] --raw cannot be used with filtering options"
        )
        sys.exit(1)

    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            logs = client.get_job_logs(owner, repo_name, job_id)

            # If --raw, output exactly as received (no filtering/normalization)
            if raw:
                click.echo(logs, nl=False)
                return

            filtered = filter_logs(
                logs,
                tail=tail,
                head=head,
                grep=grep,
                context=context,
                strip_ansi=strip_ansi,
            )
            # Sanitize output unless strip_ansi already did it
            if not strip_ansi:
                filtered = terminal_safe(filtered)
            click.echo(filtered)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)
    except click.BadParameter as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("rerun")
@click.argument("run_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def runs_rerun(ctx: click.Context, run_id: int, repo: str) -> None:
    """Rerun a workflow (via dispatch).

    Note: Uses workflow dispatch as a workaround since Gitea's native
    rerun API is not yet available. Limitations:
    - Only works for workflows with workflow_dispatch trigger
    - Original inputs not preserved
    - Original event context (PR number, etc.) lost

    Examples:
        teax runs rerun 42 -r owner/repo
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Get run info first to show what we're rerunning
            run = client.get_run(owner, repo_name, run_id)
            workflow_name = run.path.split("/")[-1] if run.path else "unknown"

            client.rerun_workflow(owner, repo_name, run_id)

            console.print(
                "[yellow]Note:[/yellow] Using workflow dispatch "
                "(native rerun API not available)"
            )
            output.print_mutation(
                "dispatched",
                f"{terminal_safe(workflow_name)} on {terminal_safe(run.head_branch)}"
            )
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("delete")
@click.argument("run_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def runs_delete(ctx: click.Context, run_id: int, repo: str, yes: bool) -> None:
    """Delete a workflow run.

    Examples:
        teax runs delete 42 -r owner/repo
        teax runs delete 42 -r owner/repo -y
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    if not yes:
        if not click.confirm(f"Delete run #{run_id}?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.delete_run(owner, repo_name, run_id)
            output.print_mutation("deleted", f"run #{run_id}")
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Package Linking Commands ---


@pkg.command("link")
@click.argument("name")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", required=True, help="Package type")
@click.option("--repo", "-r", required=True, help="Repository name to link to")
@click.pass_context
def pkg_link(
    ctx: click.Context,
    name: str,
    owner: str,
    pkg_type: str,
    repo: str,
) -> None:
    """Link a package to a repository.

    Examples:
        teax pkg link myimage --owner homelab-teams --type container --repo myproject
    """
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.link_package(owner, pkg_type, name, repo)
            msg = f"{terminal_safe(name)} to {terminal_safe(repo)}"
            output.print_mutation("linked", msg)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@pkg.command("unlink")
@click.argument("name")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", required=True, help="Package type")
@click.pass_context
def pkg_unlink(
    ctx: click.Context,
    name: str,
    owner: str,
    pkg_type: str,
) -> None:
    """Unlink a package from its repository.

    Examples:
        teax pkg unlink myimage --owner homelab-teams --type container
    """
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            client.unlink_package(owner, pkg_type, name)
            output.print_mutation("unlinked", terminal_safe(name))
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@pkg.command("latest")
@click.argument("name")
@click.option("--owner", "-o", required=True, help="Package owner (user or org)")
@click.option("--type", "pkg_type", required=True, help="Package type")
@click.pass_context
def pkg_latest(
    ctx: click.Context,
    name: str,
    owner: str,
    pkg_type: str,
) -> None:
    """Get the latest version of a package.

    Examples:
        teax pkg latest teax --owner homelab-teams --type pypi
        teax pkg latest myimage --owner homelab-teams --type container -o json
    """
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            pkg = client.get_latest_package_version(owner, pkg_type, name)
            # Use print_packages with a single-item list
            output.print_packages([pkg])
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


if __name__ == "__main__":
    main()
