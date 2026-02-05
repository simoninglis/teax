"""teax CLI - Gitea companion for tea feature gaps."""

import csv
import fnmatch
import io
import json
import os
import re
import sys
import time
from datetime import UTC
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
    r"|[\u200e\u200f\u202a-\u202e\u2066-\u2069]"  # Unicode bidi control characters
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

# Spinner frames for animated "running" indicator in tmux (time-based animation)
# Each tmux refresh shows next frame based on current second
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Workflow name abbreviation mappings for compact output (e.g., tmux status bars)
# Maps single-char abbreviation to patterns that match workflow filenames
WORKFLOW_ABBREVIATIONS: dict[str, list[str]] = {
    "C": ["ci", "check"],
    "B": ["build", "package"],
    "T": ["test"],
    "L": ["lint"],
    "D": ["deploy", "release"],
    "V": ["verify", "validate"],
    "P": ["publish"],
    "S": ["scan", "security"],
    "M": ["merge", "main"],
}


def extract_workflow_name(path: str | None) -> str:
    """Extract workflow filename from API path field.

    API returns paths like:
    - ".gitea/workflows/ci.yml"
    - ".gitea/workflows/staging-deploy.yml@refs/heads/main"

    Args:
        path: Workflow path from API (may include @refs/... suffix)

    Returns:
        Workflow filename (e.g., "ci.yml", "staging-deploy.yml")
    """
    if not path:
        return "unknown"
    # Strip @refs/... suffix first (before splitting by /)
    if "@" in path:
        path = path.split("@")[0]
    # Get last path component
    return path.split("/")[-1] or "unknown"


def abbreviate_workflow_name(workflow: str) -> str:
    """Get single-char abbreviation for workflow name.

    Matches workflow names against known patterns (case-insensitive).
    Falls back to first alphanumeric character if no pattern matches.

    Args:
        workflow: Workflow filename (e.g., "ci.yml", "staging-deploy.yml")

    Returns:
        Single uppercase character abbreviation
    """
    # Sanitize and remove .yml/.yaml extension, then lowercase
    base = terminal_safe(workflow).lower()
    for ext in [".yml", ".yaml"]:
        if base.endswith(ext):
            base = base[: -len(ext)]
            break

    # Check each abbreviation pattern
    for abbrev, patterns in WORKFLOW_ABBREVIATIONS.items():
        for pattern in patterns:
            if pattern in base:
                return abbrev

    # Fallback: first alphanumeric char, uppercase
    for c in base:
        if c.isalnum():
            return c.upper()
    return "?"


# Job name abbreviation mappings for compact output (e.g., tmux status bars)
JOB_ABBREVIATIONS: dict[str, list[str]] = {
    "lint": ["lint", "type check", "linting"],
    "unit": ["unit test", "unit tests"],
    "int": ["integration test", "integration tests"],
    "smoke": ["smoke test", "smoke tests"],
    "e2e": ["e2e test", "e2e tests", "end-to-end"],
    "visual": ["visual test", "visual tests"],
    "build": ["build", "push", "package"],
    "deploy": ["deploy"],
    "verify": ["verify"],
}


def abbreviate_job_name(name: str) -> str:
    """Get short abbreviation for job name.

    Matches job names against known patterns (case-insensitive substring match).
    Falls back to first 4 alphanumeric characters if no pattern matches.

    Args:
        name: Job name to abbreviate

    Returns:
        Short abbreviation (typically 3-5 chars)
    """
    lower_name = name.lower()
    for abbrev, patterns in JOB_ABBREVIATIONS.items():
        if any(p in lower_name for p in patterns):
            return abbrev
    # Fallback: first 4 alphanumeric chars
    return "".join(c for c in name if c.isalnum())[:4].lower() or "job"


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


def parse_show_spec(show: str) -> list[tuple[str, str]]:
    """Parse --show specification into (abbreviation, workflow_name) tuples.

    Format: "A:ci.yml,B:build.yml,D:deploy.yml"

    Args:
        show: Show specification string

    Returns:
        List of (abbreviation, workflow_name) tuples preserving order

    Raises:
        click.BadParameter: If spec is invalid
    """
    if not show.strip():
        raise click.BadParameter("Empty --show specification")

    result: list[tuple[str, str]] = []
    seen_abbrevs: set[str] = set()
    seen_workflows: set[str] = set()

    for part in show.split(","):
        part = part.strip()
        if not part:
            continue

        # Split on first colon only (workflow names could contain colons)
        if ":" not in part:
            safe_part = terminal_safe(part)
            raise click.BadParameter(
                f"Invalid format, expected 'A:workflow.yml': {safe_part}"
            )

        colon_idx = part.index(":")
        abbrev = part[:colon_idx].strip()
        workflow = part[colon_idx + 1 :].strip()

        # Validate abbreviation: single ASCII alphanumeric character
        # (Unicode chars like ß can expand when uppercased, breaking invariants)
        if len(abbrev) != 1 or not abbrev.isascii() or not abbrev.isalnum():
            safe_abbrev = terminal_safe(abbrev)
            raise click.BadParameter(
                f"Abbreviation must be single ASCII alphanumeric: {safe_abbrev}"
            )

        # Validate workflow name: must end in .yml or .yaml
        if not (workflow.endswith(".yml") or workflow.endswith(".yaml")):
            safe_wf = terminal_safe(workflow)
            raise click.BadParameter(f"Workflow must end in .yml or .yaml: {safe_wf}")

        # Check for duplicates
        abbrev_upper = abbrev.upper()
        if abbrev_upper in seen_abbrevs:
            raise click.BadParameter(f"Duplicate abbreviation: {terminal_safe(abbrev)}")
        if workflow in seen_workflows:
            raise click.BadParameter(f"Duplicate workflow: {terminal_safe(workflow)}")

        seen_abbrevs.add(abbrev_upper)
        seen_workflows.add(workflow)
        result.append((abbrev.upper(), workflow))

    if not result:
        raise click.BadParameter("No valid workflow specifications")

    return result


def compute_issue_fields(issue: Any) -> dict[str, Any]:
    """Derive computed fields from issue labels for sprint management.

    Extracts:
    - sprint_number: int | None from "sprint/N" label
    - is_ready: bool from "ready" label presence
    - is_bug: bool from "type/bug" or "bug" label presence
    - effort: str | None from "effort/XS", "effort/S", etc.
    - priority: str | None from "prio/p0", "prio/p1", etc. or "priority/..."

    Args:
        issue: Issue object with labels attribute

    Returns:
        Dict with computed fields
    """
    labels = [lb.name.lower() for lb in (issue.labels or [])]
    original_labels = [lb.name for lb in (issue.labels or [])]

    result: dict[str, Any] = {
        "sprint_number": None,
        "is_ready": False,
        "is_bug": False,
        "effort": None,
        "priority": None,
    }

    for label in labels:
        # Sprint detection: sprint/1, sprint/28, etc. (only valid sprint numbers >= 1)
        if label.startswith("sprint/"):
            try:
                sprint_num = int(label.split("/")[1])
                if sprint_num >= 1:
                    result["sprint_number"] = sprint_num
            except (ValueError, IndexError):
                pass

        # Ready detection
        if label == "ready":
            result["is_ready"] = True

        # Bug detection: type/bug or bug
        if label in ("type/bug", "bug"):
            result["is_bug"] = True

        # Effort detection: effort/XS, effort/S, effort/M, etc.
        if label.startswith("effort/"):
            # Preserve original case
            for orig in original_labels:
                if orig.lower() == label:
                    result["effort"] = orig.split("/")[1]
                    break

        # Priority detection: prio/p0, prio/p1, priority/high, etc.
        if label.startswith(("prio/", "priority/")):
            for orig in original_labels:
                if orig.lower() == label:
                    result["priority"] = orig.split("/")[1]
                    break

    return result


def filter_issues_by_no_labels(issues: list[Any], patterns: list[str]) -> list[Any]:
    """Exclude issues where any label matches any glob pattern.

    Uses case-insensitive matching for consistent behavior across platforms.

    Args:
        issues: List of Issue objects
        patterns: List of fnmatch glob patterns (e.g., "sprint/*", "epic/*")

    Returns:
        Filtered list excluding issues with matching labels
    """
    if not patterns:
        return issues

    # Normalize patterns to lowercase for case-insensitive matching
    lower_patterns = [p.lower() for p in patterns]

    result = []
    for issue in issues:
        labels = [lb.name.lower() for lb in (issue.labels or [])]
        # Check if any label matches any exclusion pattern
        # Use fnmatchcase for platform-independent behavior
        has_excluded_label = any(
            fnmatch.fnmatchcase(label, pattern)
            for label in labels
            for pattern in lower_patterns
        )
        if not has_excluded_label:
            result.append(issue)
    return result


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
                writer.writerow(
                    [
                        d.number,
                        csv_safe(d.title),
                        csv_safe(d.state),
                        csv_safe(d.repository.full_name),
                    ]
                )
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
                writer.writerow(
                    [
                        csv_safe(label.name),
                        csv_safe(label.color),
                        csv_safe(label.description),
                    ]
                )
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

    def print_milestones(self, milestones: list[Any]) -> None:
        """Print milestone list."""
        if self.format_type == "json":
            output_data = []
            for ms in milestones:
                item = {
                    "id": ms.id,
                    "title": terminal_safe(ms.title),
                    "state": terminal_safe(ms.state),
                    "description": terminal_safe(ms.description),
                    "open_issues": ms.open_issues,
                    "closed_issues": ms.closed_issues,
                    "due_on": ms.due_on.isoformat() if ms.due_on else None,
                    "created_at": ms.created_at.isoformat() if ms.created_at else None,
                    "updated_at": ms.updated_at.isoformat() if ms.updated_at else None,
                    "closed_at": ms.closed_at.isoformat() if ms.closed_at else None,
                }
                output_data.append(item)
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                ["id", "title", "state", "open_issues", "closed_issues", "due_on"]
            )
            for ms in milestones:
                due_str = ms.due_on.strftime("%Y-%m-%d") if ms.due_on else ""
                writer.writerow(
                    [
                        ms.id,
                        csv_safe(ms.title),
                        csv_safe(ms.state),
                        ms.open_issues,
                        ms.closed_issues,
                        due_str,
                    ]
                )
            click.echo(output.getvalue().rstrip())

        elif self.format_type == "simple":
            for ms in milestones:
                click.echo(terminal_safe(ms.title))

        else:  # table (default)
            if not milestones:
                console.print("[dim]No milestones[/dim]")
                return

            table = Table(title="Milestones")
            table.add_column("ID", style="cyan")
            table.add_column("Title")
            table.add_column("State")
            table.add_column("Open", justify="right")
            table.add_column("Closed", justify="right")
            table.add_column("Due", style="dim")

            for ms in milestones:
                state_style = "green" if ms.state == "open" else "dim"
                due_str = ms.due_on.strftime("%Y-%m-%d") if ms.due_on else ""
                table.add_row(
                    str(ms.id),
                    safe_rich(ms.title),
                    f"[{state_style}]{safe_rich(ms.state)}[/{state_style}]",
                    str(ms.open_issues),
                    str(ms.closed_issues),
                    due_str,
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
                        "state": terminal_safe(issue.state),
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
                "errors": {str(num): terminal_safe(msg) for num, msg in errors.items()},
            }
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                ["number", "title", "state", "labels", "assignees", "milestone", "body"]
            )
            for issue in issues:
                labels_str = ",".join(csv_safe(lb.name) for lb in (issue.labels or []))
                assignees_str = ",".join(
                    csv_safe(a.login) for a in (issue.assignees or [])
                )
                milestone_str = (
                    csv_safe(issue.milestone.title) if issue.milestone else ""
                )
                # Truncate body for CSV
                body = issue.body or ""
                body_preview = body[:200] + "..." if len(body) > 200 else body
                writer.writerow(
                    [
                        issue.number,
                        csv_safe(issue.title),
                        csv_safe(issue.state),
                        labels_str,
                        assignees_str,
                        milestone_str,
                        csv_safe(body_preview),
                    ]
                )
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
                    str(num), f"[red]ERROR: {safe_rich(msg)}[/red]", "", "", "", "", ""
                )

            console.print(table)

    def print_issue_list(
        self,
        issues: list[Any],
        *,
        include_computed: bool = False,
    ) -> None:
        """Print issue list for `issue list` command.

        Args:
            issues: List of Issue objects to display
            include_computed: If True, include computed fields (sprint_number, etc.)
        """
        if self.format_type == "json":
            output_data = []
            for issue in issues:
                item: dict[str, Any] = {
                    "number": issue.number,
                    "title": terminal_safe(issue.title),
                    "state": terminal_safe(issue.state),
                    "labels": [terminal_safe(lb.name) for lb in (issue.labels or [])],
                    "assignees": [
                        terminal_safe(a.login) for a in (issue.assignees or [])
                    ],
                    "milestone": (
                        terminal_safe(issue.milestone.title)
                        if issue.milestone
                        else None
                    ),
                }
                if include_computed:
                    computed = compute_issue_fields(issue)
                    # Sanitize string fields to prevent terminal injection
                    item.update(
                        {
                            "sprint_number": computed["sprint_number"],
                            "is_ready": computed["is_ready"],
                            "is_bug": computed["is_bug"],
                            "effort": (
                                terminal_safe(computed["effort"])
                                if computed["effort"]
                                else None
                            ),
                            "priority": (
                                terminal_safe(computed["priority"])
                                if computed["priority"]
                                else None
                            ),
                        }
                    )
                output_data.append(item)
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            headers = ["number", "title", "state", "labels", "assignees", "milestone"]
            if include_computed:
                headers.extend(
                    ["sprint_number", "is_ready", "is_bug", "effort", "priority"]
                )
            writer.writerow(headers)
            for issue in issues:
                labels_str = ",".join(csv_safe(lb.name) for lb in (issue.labels or []))
                assignees_str = ",".join(
                    csv_safe(a.login) for a in (issue.assignees or [])
                )
                milestone_str = (
                    csv_safe(issue.milestone.title) if issue.milestone else ""
                )
                row: list[Any] = [
                    issue.number,
                    csv_safe(issue.title),
                    csv_safe(issue.state),
                    labels_str,
                    assignees_str,
                    milestone_str,
                ]
                if include_computed:
                    computed = compute_issue_fields(issue)
                    row.extend(
                        [
                            computed["sprint_number"] or "",
                            computed["is_ready"],
                            computed["is_bug"],
                            csv_safe(computed["effort"] or ""),
                            csv_safe(computed["priority"] or ""),
                        ]
                    )
                writer.writerow(row)
            click.echo(output.getvalue().rstrip())

        elif self.format_type == "simple":
            for issue in issues:
                click.echo(f"#{issue.number} {terminal_safe(issue.title)}")

        else:  # table (default)
            if not issues:
                console.print("[dim]No issues found[/dim]")
                return

            table = Table(title="Issues")
            table.add_column("#", style="cyan")
            table.add_column("Title")
            table.add_column("State")
            table.add_column("Labels", style="dim")
            table.add_column("Assignee", style="dim")
            if include_computed:
                table.add_column("Sprint", style="cyan")
                table.add_column("Priority", style="yellow")

            for issue in issues:
                state_style = "green" if issue.state == "open" else "red"
                labels_str = ", ".join(
                    safe_rich(lb.name) for lb in (issue.labels or [])
                )
                assignees = issue.assignees or []
                assignee_str = safe_rich(assignees[0].login) if assignees else ""

                row = [
                    str(issue.number),
                    safe_rich(issue.title),
                    f"[{state_style}]{safe_rich(issue.state)}[/{state_style}]",
                    labels_str,
                    assignee_str,
                ]

                if include_computed:
                    computed = compute_issue_fields(issue)
                    sprint_str = (
                        str(computed["sprint_number"])
                        if computed["sprint_number"]
                        else ""
                    )
                    priority_str = safe_rich(computed["priority"] or "")
                    row.extend([sprint_str, priority_str])

                table.add_row(*row)
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
                writer.writerow(
                    [
                        r.id,
                        csv_safe(r.name),
                        csv_safe(r.status),
                        r.busy,
                        labels_str,
                        csv_safe(r.version),
                    ]
                )
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
                writer.writerow(
                    [
                        csv_safe(p.name),
                        csv_safe(p.type),
                        csv_safe(p.version),
                        csv_safe(p.owner.login),
                        csv_safe(p.created_at),
                    ]
                )
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
                writer.writerow(
                    [
                        csv_safe(v.version),
                        csv_safe(v.created_at),
                        csv_safe(v.html_url),
                    ]
                )
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
                writer.writerow(
                    [
                        csv_safe(w.id),
                        csv_safe(w.name),
                        csv_safe(w.path),
                        csv_safe(w.state),
                    ]
                )
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
                    f"{r.id} {terminal_safe(conclusion)} "
                    f"{terminal_safe(sha)} {terminal_safe(r.head_branch)}"
                )

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "id",
                    "run_number",
                    "status",
                    "conclusion",
                    "head_sha",
                    "head_branch",
                    "event",
                    "path",
                ]
            )
            for r in runs:
                writer.writerow(
                    [
                        r.id,
                        r.run_number,
                        csv_safe(r.status),
                        csv_safe(r.conclusion or ""),
                        csv_safe(r.head_sha[:8] if r.head_sha else ""),
                        csv_safe(r.head_branch),
                        csv_safe(r.event),
                        csv_safe(r.path),
                    ]
                )
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            if not runs:
                console.print("[dim]No workflow runs found[/dim]")
                return

            table = Table(title="Workflow Runs")
            table.add_column("ID", style="cyan")
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
                workflow_name = extract_workflow_name(r.path)

                table.add_row(
                    str(r.id),
                    status_str,
                    safe_rich(r.head_sha[:8] if r.head_sha else ""),
                    safe_rich(r.head_branch),
                    safe_rich(workflow_name),
                    safe_rich(r.event),
                )
            console.print(table)

    def print_run_status(
        self,
        runs: list[Any],
        commit_sha: str | None = None,
        verbose: bool = False,
        workflow_jobs: dict[int, list[Any]] | None = None,
        show_map: list[tuple[str, str]] | None = None,
    ) -> str:
        """Print workflow health status (latest run per workflow).

        Args:
            runs: List of workflow runs
            commit_sha: Optional commit SHA being queried (for display)
            verbose: If True, show failed job details
            workflow_jobs: Pre-fetched jobs for failed workflows {run_id: [jobs]}
            show_map: Optional list of (abbreviation, workflow_name) tuples
                      for explicit workflow ordering and custom abbreviations

        Returns:
            Overall status: "success", "failure", "running", "no_runs", or "pending"
        """
        workflow_jobs = workflow_jobs or {}

        # Group runs by workflow (keep latest per workflow)
        workflow_runs: dict[str, Any] = {}
        for r in runs:
            workflow_name = extract_workflow_name(r.path)
            if workflow_name not in workflow_runs:
                workflow_runs[workflow_name] = r

        # When show_map is provided, filter to only specified workflows
        if show_map:
            # Build ordered list of (abbrev, workflow, run_or_none)
            show_workflows = [
                (abbrev, wf, workflow_runs.get(wf)) for abbrev, wf in show_map
            ]
            active_runs = [r for _, _, r in show_workflows if r is not None]

            # Calculate overall status based on specified workflows only
            if not active_runs:
                overall_status = "pending"  # None triggered
            elif any(r.conclusion == "failure" for r in active_runs):
                overall_status = "failure"
            elif any(
                r.status in ("queued", "in_progress", "waiting") for r in active_runs
            ):
                overall_status = "running"
            elif all(r.conclusion == "success" for r in active_runs):
                overall_status = "success"
            else:
                # Mixed state (cancelled, skipped, etc.) - success if no failures
                overall_status = "success"
        else:
            show_workflows = None  # Not using show_map mode

            # Calculate overall status
            if not workflow_runs:
                overall_status = "no_runs"
            elif any(r.conclusion == "failure" for r in workflow_runs.values()):
                overall_status = "failure"
            elif any(
                r.status in ("queued", "in_progress", "waiting")
                for r in workflow_runs.values()
            ):
                overall_status = "running"
            elif all(r.conclusion == "success" for r in workflow_runs.values()):
                overall_status = "success"
            else:
                # Mixed state (cancelled, skipped, etc.) - success if no failures
                overall_status = "success"

        if self.format_type == "json":
            output_data: dict[str, Any] = {
                "commit": terminal_safe(commit_sha[:8]) if commit_sha else None,
                "commit_full": terminal_safe(commit_sha) if commit_sha else None,
                "overall_status": overall_status,
            }

            if show_workflows is not None:
                # Array format with explicit abbreviations
                workflows_list: list[dict[str, Any]] = []
                for abbrev, wf, r in show_workflows:
                    if r is None:
                        # Workflow not triggered
                        workflows_list.append(
                            {
                                "abbrev": terminal_safe(abbrev),
                                "workflow": terminal_safe(wf),
                                "triggered": False,
                                "status": None,
                                "conclusion": None,
                            }
                        )
                    else:
                        wf_data: dict[str, Any] = {
                            "abbrev": terminal_safe(abbrev),
                            "workflow": terminal_safe(wf),
                            "triggered": True,
                            "run_id": r.id,
                            "run_number": r.run_number,
                            "status": terminal_safe(r.status),
                            "conclusion": (
                                terminal_safe(r.conclusion) if r.conclusion else None
                            ),
                            "head_sha": terminal_safe(r.head_sha[:8]),
                            "head_branch": terminal_safe(r.head_branch or ""),
                            "started_at": (
                                terminal_safe(r.started_at) if r.started_at else None
                            ),
                        }
                        # Add jobs data if verbose and available
                        if verbose and r.id in workflow_jobs:
                            jobs = workflow_jobs[r.id]
                            wf_data["jobs"] = [
                                {
                                    "id": j.id,
                                    "name": terminal_safe(j.name),
                                    "status": terminal_safe(j.status),
                                    "conclusion": (
                                        terminal_safe(j.conclusion)
                                        if j.conclusion
                                        else None
                                    ),
                                }
                                for j in jobs
                            ]
                            wf_data["failed_jobs"] = [
                                terminal_safe(j.name)
                                for j in jobs
                                if j.conclusion == "failure"
                            ]
                        workflows_list.append(wf_data)
                output_data["workflows"] = workflows_list
            else:
                # Dict format (original behavior)
                workflows_dict: dict[str, Any] = {}
                for wf, r in workflow_runs.items():
                    wf_data = {
                        "run_id": r.id,
                        "run_number": r.run_number,
                        "status": terminal_safe(r.status),
                        "conclusion": (
                            terminal_safe(r.conclusion) if r.conclusion else None
                        ),
                        "head_sha": terminal_safe(r.head_sha[:8]),
                        "head_branch": terminal_safe(r.head_branch or ""),
                        "started_at": (
                            terminal_safe(r.started_at) if r.started_at else None
                        ),
                    }
                    # Add jobs data if verbose and available
                    if verbose and r.id in workflow_jobs:
                        jobs = workflow_jobs[r.id]
                        wf_data["jobs"] = [
                            {
                                "id": j.id,
                                "name": terminal_safe(j.name),
                                "status": terminal_safe(j.status),
                                "conclusion": (
                                    terminal_safe(j.conclusion)
                                    if j.conclusion
                                    else None
                                ),
                            }
                            for j in jobs
                        ]
                        wf_data["failed_jobs"] = [
                            terminal_safe(j.name)
                            for j in jobs
                            if j.conclusion == "failure"
                        ]
                    workflows_dict[wf] = wf_data
                output_data["workflows"] = workflows_dict
            click.echo(json.dumps(output_data, indent=2))

        elif self.format_type == "tmux":
            # Compact format for tmux status bars: C:✓ B:✓ D:✓
            # For failures with jobs, show hints: M:✗[lint] or M:✗[3]

            def _tmux_status(abbrev: str, r: Any | None) -> str:
                """Format a single workflow status for tmux."""
                if r is None:
                    return f"{terminal_safe(abbrev)}:-"
                conclusion = r.conclusion or r.status
                if conclusion == "success":
                    return f"{terminal_safe(abbrev)}:✓"
                elif conclusion == "failure":
                    # Check if we have job info for failure hints
                    if r.id in workflow_jobs:
                        jobs = workflow_jobs[r.id]
                        failed = [j for j in jobs if j.conclusion == "failure"]
                        if len(failed) == 1:
                            hint = abbreviate_job_name(failed[0].name)
                            return f"{terminal_safe(abbrev)}:✗[{terminal_safe(hint)}]"
                        elif len(failed) > 1:
                            return f"{terminal_safe(abbrev)}:✗[{len(failed)}]"
                    return f"{terminal_safe(abbrev)}:✗"
                elif r.status in ("queued", "in_progress", "waiting"):
                    # Animated spinner - frame based on current second
                    spinner = SPINNER_FRAMES[int(time.time()) % len(SPINNER_FRAMES)]
                    return f"{terminal_safe(abbrev)}:{spinner}"
                elif conclusion in ("cancelled", "skipped"):
                    return f"{terminal_safe(abbrev)}:○"
                else:
                    return f"{terminal_safe(abbrev)}:-"

            if show_workflows is not None:
                # Use explicit abbreviations from show_map
                parts = [_tmux_status(abbrev, r) for abbrev, _, r in show_workflows]
            elif not workflow_runs:
                click.echo("CI:?")
                return overall_status
            else:
                # Auto-generate abbreviations (original behavior)
                parts = []
                for wf, r in sorted(workflow_runs.items()):
                    abbrev = abbreviate_workflow_name(wf)
                    parts.append(_tmux_status(abbrev, r))
            click.echo(" ".join(parts))

        elif self.format_type == "simple":

            def _simple_symbol(conclusion: str) -> str:
                """Get symbol for simple format (matches tmux/table consistency)."""
                if conclusion == "success":
                    return "✓"
                elif conclusion == "failure":
                    return "✗"
                elif conclusion in ("cancelled", "skipped"):
                    return "○"
                else:
                    return "●"  # Running or other states

            if show_workflows is not None:
                for _abbrev, wf, r in show_workflows:
                    if r is None:
                        click.echo(f"{terminal_safe(wf)}: - not triggered")
                    else:
                        conclusion = r.conclusion or r.status
                        symbol = _simple_symbol(conclusion)
                        click.echo(
                            f"{terminal_safe(wf)}: {symbol} "
                            f"{terminal_safe(conclusion)} (#{r.run_number})"
                        )
                        # Show failed jobs if verbose
                        if verbose and r.id in workflow_jobs:
                            failed = [
                                j
                                for j in workflow_jobs[r.id]
                                if j.conclusion == "failure"
                            ]
                            for j in failed:
                                click.echo(f"  ✗ {terminal_safe(j.name)}")
            else:
                for wf, r in workflow_runs.items():
                    conclusion = r.conclusion or r.status
                    symbol = _simple_symbol(conclusion)
                    click.echo(
                        f"{terminal_safe(wf)}: {symbol} {terminal_safe(conclusion)} "
                        f"(#{r.run_number})"
                    )
                    # Show failed jobs if verbose
                    if verbose and r.id in workflow_jobs:
                        failed = [
                            j for j in workflow_jobs[r.id] if j.conclusion == "failure"
                        ]
                        for j in failed:
                            click.echo(f"  ✗ {terminal_safe(j.name)}")

        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)

            if show_workflows is not None:
                # Include abbrev column when using --show
                base_cols = ["abbrev", "workflow", "triggered", "status", "conclusion"]
                if verbose:
                    writer.writerow(
                        base_cols + ["run_number", "head_sha", "failed_jobs"]
                    )
                else:
                    writer.writerow(base_cols + ["run_number", "head_sha"])

                for abbrev, wf, r in show_workflows:
                    if r is None:
                        row: list[Any] = [
                            csv_safe(abbrev),
                            csv_safe(wf),
                            "false",
                            "",
                            "",
                            "",
                            "",
                        ]
                        if verbose:
                            row.append("")
                    else:
                        row = [
                            csv_safe(abbrev),
                            csv_safe(wf),
                            "true",
                            csv_safe(r.status),
                            csv_safe(r.conclusion or ""),
                            r.run_number,
                            csv_safe(r.head_sha[:8] if r.head_sha else ""),
                        ]
                        if verbose:
                            if r.id in workflow_jobs:
                                failed = [
                                    j
                                    for j in workflow_jobs[r.id]
                                    if j.conclusion == "failure"
                                ]
                                row.append(csv_safe(";".join(j.name for j in failed)))
                            else:
                                row.append("")
                    writer.writerow(row)
            else:
                # Original format without abbrev column
                if verbose:
                    writer.writerow(
                        [
                            "workflow",
                            "status",
                            "conclusion",
                            "run_number",
                            "head_sha",
                            "failed_jobs",
                        ]
                    )
                else:
                    writer.writerow(
                        ["workflow", "status", "conclusion", "run_number", "head_sha"]
                    )
                for wf, r in workflow_runs.items():
                    row = [
                        csv_safe(wf),
                        csv_safe(r.status),
                        csv_safe(r.conclusion or ""),
                        r.run_number,
                        csv_safe(r.head_sha[:8] if r.head_sha else ""),
                    ]
                    if verbose:
                        if r.id in workflow_jobs:
                            failed = [
                                j
                                for j in workflow_jobs[r.id]
                                if j.conclusion == "failure"
                            ]
                            row.append(csv_safe(";".join(j.name for j in failed)))
                        else:
                            row.append("")
                    writer.writerow(row)
            click.echo(output.getvalue().rstrip())

        else:  # table (default)
            # Show commit SHA if filtering
            if commit_sha:
                console.print(f"[dim]Commit: {safe_rich(commit_sha[:8])}[/dim]")

            # Show overall status
            if overall_status == "success":
                console.print("[green]Pipeline Status: ✅ All passed[/green]")
            elif overall_status == "failure":
                console.print("[red]Pipeline Status: ❌ Failed[/red]")
            elif overall_status == "running":
                console.print("[blue]Pipeline Status: ⏳ Running[/blue]")
            elif overall_status == "pending":
                console.print("[dim]Pipeline Status: ⊘ No workflows triggered[/dim]")
            elif overall_status == "no_runs":
                console.print("[dim]No workflow runs found[/dim]")
                return overall_status
            console.print()

            if show_workflows is not None:
                for _abbrev, wf, r in show_workflows:
                    if r is None:
                        console.print(
                            f"[bold]{safe_rich(wf)}[/bold]: [dim]- not triggered[/dim]"
                        )
                    else:
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

                        # Show failed jobs if verbose
                        if verbose and r.id in workflow_jobs:
                            failed = [
                                j
                                for j in workflow_jobs[r.id]
                                if j.conclusion == "failure"
                            ]
                            for j in failed:
                                console.print(f"  [red]✗ {safe_rich(j.name)}[/red]")
            else:
                if not workflow_runs:
                    return overall_status

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

                    # Show failed jobs if verbose
                    if verbose and r.id in workflow_jobs:
                        failed = [
                            j for j in workflow_jobs[r.id] if j.conclusion == "failure"
                        ]
                        for j in failed:
                            console.print(f"  [red]✗ {safe_rich(j.name)}[/red]")

        return overall_status

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
            writer.writerow(
                [
                    "job_id",
                    "job_name",
                    "job_conclusion",
                    "step_number",
                    "step_name",
                    "step_conclusion",
                ]
            )
            for j in jobs:
                for s in j.steps:
                    writer.writerow(
                        [
                            j.id,
                            csv_safe(j.name),
                            csv_safe(j.conclusion or ""),
                            s.number,
                            csv_safe(s.name),
                            csv_safe(s.conclusion or ""),
                        ]
                    )
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
    type=click.Choice(["table", "simple", "csv", "json", "tmux"]),
    default="table",
    help="Output format (tmux is compact for status bars)",
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
def issue_view(ctx: click.Context, issue_num: int, repo: str, comments: bool) -> None:
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
                            f"[dim]#{comment.id} - {safe_rich(comment.user.login)} "
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


@issue.command("list")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option(
    "--state",
    default="open",
    type=click.Choice(["open", "closed", "all"]),
    help="Filter by state (default: open)",
)
@click.option(
    "--label", "-l", "labels", multiple=True, help="Filter by label (can repeat)"
)
@click.option(
    "--no-label",
    "no_labels",
    multiple=True,
    help="Exclude by glob pattern (e.g., 'sprint/*')",
)
@click.option("--assignee", help="Filter by assignee username")
@click.option("--milestone", help="Filter by milestone name")
@click.option(
    "--computed",
    is_flag=True,
    help="Include computed fields (table: Sprint/Priority; JSON/CSV: all fields)",
)
@click.pass_context
def issue_list(
    ctx: click.Context,
    repo: str,
    state: str,
    labels: tuple[str, ...],
    no_labels: tuple[str, ...],
    assignee: str | None,
    milestone: str | None,
    computed: bool,
) -> None:
    """List issues in a repository.

    Supports filtering by state, labels, assignee, and milestone.
    Use --no-label to exclude issues with matching labels (glob patterns supported).

    Examples:
        teax issue list --repo owner/repo
        teax issue list --repo owner/repo --state all
        teax issue list --repo owner/repo --label ready
        teax issue list --repo owner/repo --no-label "sprint/*"
        teax issue list --repo owner/repo --label ready --no-label "sprint/*" -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            issues = client.list_issues(
                owner,
                repo_name,
                state=state,
                labels=list(labels) if labels else None,
                milestone=milestone,
                assignee=assignee,
            )

            # Apply client-side --no-label filtering
            if no_labels:
                issues = filter_issues_by_no_labels(issues, list(no_labels))

            output.print_issue_list(issues, include_computed=computed)
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
@click.option("--dry-run", is_flag=True, help="Preview changes without executing")
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
    dry_run: bool,
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
        teax issue bulk 17-20 --repo owner/repo --add-labels "ready" --dry-run
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

    # Dry-run mode: show preview with current vs after state
    if dry_run:
        console.print("[yellow]DRY RUN - no changes made[/yellow]\n")

        try:
            with GiteaClient(login_name=ctx.obj["login_name"]) as client:
                # Build preview table
                table = Table(title="Preview: Label Changes")
                table.add_column("#", style="cyan")
                table.add_column("Current Labels")
                table.add_column("After Labels")

                for issue_num in issue_nums:
                    try:
                        issue = client.get_issue(owner, repo_name, issue_num)
                        current_labels = {lb.name for lb in (issue.labels or [])}

                        # Calculate expected labels after changes
                        after_labels = current_labels.copy()
                        if set_labels is not None:
                            after_labels = {
                                s.strip() for s in set_labels.split(",") if s.strip()
                            }
                        if add_labels is not None:
                            after_labels.update(
                                s.strip() for s in add_labels.split(",") if s.strip()
                            )
                        if rm_labels is not None:
                            after_labels -= {
                                s.strip() for s in rm_labels.split(",") if s.strip()
                            }

                        # Show changes
                        current_str = ", ".join(sorted(current_labels)) or "(none)"
                        after_str = ", ".join(sorted(after_labels)) or "(none)"

                        # Highlight if changed
                        if current_labels != after_labels:
                            table.add_row(
                                str(issue_num),
                                safe_rich(current_str),
                                f"[green]{safe_rich(after_str)}[/green]",
                            )
                        else:
                            table.add_row(
                                str(issue_num),
                                safe_rich(current_str),
                                f"[dim]{safe_rich(after_str)}[/dim] (no change)",
                            )
                    except CLI_ERRORS as e:
                        table.add_row(
                            str(issue_num),
                            f"[red]Error: {safe_rich(str(e))}[/red]",
                            "",
                        )

                console.print(table)
                console.print(
                    "\n[dim]To execute: remove --dry-run and add --yes flag[/dim]"
                )
        except CLI_ERRORS as e:
            err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
            sys.exit(1)
        return

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
                    milestone_id = client.resolve_milestone(owner, repo_name, milestone)
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


@issue.command("close")
@click.argument("issues")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation for multiple issues")
@click.pass_context
def issue_close(
    ctx: click.Context,
    issues: str,
    repo: str,
    yes: bool,
) -> None:
    """Close one or more issues.

    ISSUES can be a single number, comma-separated list, or range:
      42        - Single issue
      42,43,44  - Multiple issues
      42-50     - Range of issues
      42-45,50  - Mixed

    Examples:
      teax issue close 42 -r owner/repo
      teax issue close 42,43,44 -r owner/repo
      teax issue close 42-50 -r owner/repo -y
    """
    output: OutputFormat = ctx.obj["output"]
    try:
        owner, repo_name = parse_repo(repo)
        issue_nums = parse_issue_spec(issues)

        # Confirm for multiple issues
        if len(issue_nums) > 1 and not yes:
            console.print(
                f"About to close {len(issue_nums)} issues: "
                f"{', '.join(f'#{n}' for n in sorted(issue_nums)[:5])}"
                f"{'...' if len(issue_nums) > 5 else ''}"
            )
            if not click.confirm("Continue?"):
                console.print("[yellow]Cancelled[/yellow]")
                return

        success_count = 0
        error_count = 0
        closed_issues: list[Any] = []
        errors: dict[int, str] = {}

        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            for issue_num in sorted(issue_nums):
                try:
                    updated = client.edit_issue(
                        owner, repo_name, issue_num, state="closed"
                    )
                    closed_issues.append(updated)
                    if output.format_type == "simple":
                        console.print(f"[green]✓[/green] Closed #{issue_num}")
                    success_count += 1
                except CLI_ERRORS as e:
                    errors[issue_num] = str(e)
                    if output.format_type == "simple":
                        console.print(f"[red]✗[/red] #{issue_num}: {safe_rich(str(e))}")
                    error_count += 1

        # Output for non-simple formats
        if output.format_type != "simple":
            output.print_issues(closed_issues, errors=errors if errors else None)

        # Summary for multiple issues (stderr for JSON/CSV to preserve output)
        if len(issue_nums) > 1:
            summary_console = (
                err_console if output.format_type in ("json", "csv") else console
            )
            summary_console.print(
                f"\n[bold]Summary:[/bold] {success_count} closed, {error_count} failed"
            )

        if error_count > 0:
            sys.exit(1)

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("reopen")
@click.argument("issues")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation for multiple issues")
@click.pass_context
def issue_reopen(
    ctx: click.Context,
    issues: str,
    repo: str,
    yes: bool,
) -> None:
    """Reopen one or more closed issues.

    ISSUES can be a single number, comma-separated list, or range:
      42        - Single issue
      42,43,44  - Multiple issues
      42-50     - Range of issues
      42-45,50  - Mixed

    Examples:
      teax issue reopen 42 -r owner/repo
      teax issue reopen 42,43,44 -r owner/repo
      teax issue reopen 42-50 -r owner/repo -y
    """
    output: OutputFormat = ctx.obj["output"]
    try:
        owner, repo_name = parse_repo(repo)
        issue_nums = parse_issue_spec(issues)

        # Confirm for multiple issues
        if len(issue_nums) > 1 and not yes:
            console.print(
                f"About to reopen {len(issue_nums)} issues: "
                f"{', '.join(f'#{n}' for n in sorted(issue_nums)[:5])}"
                f"{'...' if len(issue_nums) > 5 else ''}"
            )
            if not click.confirm("Continue?"):
                console.print("[yellow]Cancelled[/yellow]")
                return

        success_count = 0
        error_count = 0
        reopened_issues: list[Any] = []
        errors: dict[int, str] = {}

        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            for issue_num in sorted(issue_nums):
                try:
                    updated = client.edit_issue(
                        owner, repo_name, issue_num, state="open"
                    )
                    reopened_issues.append(updated)
                    if output.format_type == "simple":
                        console.print(f"[green]✓[/green] Reopened #{issue_num}")
                    success_count += 1
                except CLI_ERRORS as e:
                    errors[issue_num] = str(e)
                    if output.format_type == "simple":
                        console.print(f"[red]✗[/red] #{issue_num}: {safe_rich(str(e))}")
                    error_count += 1

        # Output for non-simple formats
        if output.format_type != "simple":
            output.print_issues(reopened_issues, errors=errors if errors else None)

        # Summary for multiple issues (stderr for JSON/CSV to preserve output)
        if len(issue_nums) > 1:
            summary_console = (
                err_console if output.format_type in ("json", "csv") else console
            )
            summary_console.print(
                f"\n[bold]Summary:[/bold] "
                f"{success_count} reopened, {error_count} failed"
            )

        if error_count > 0:
            sys.exit(1)

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("create")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--title", "-t", required=True, help="Issue title")
@click.option("--body", "-b", default="", help="Issue body/description")
@click.option("--labels", "-l", help="Labels (comma-separated names)")
@click.option("--assignees", "-a", help="Assignees (comma-separated usernames)")
@click.option("--milestone", "-m", help="Milestone (ID or name)")
@click.pass_context
def issue_create(
    ctx: click.Context,
    repo: str,
    title: str,
    body: str,
    labels: str | None,
    assignees: str | None,
    milestone: str | None,
) -> None:
    """Create a new issue.

    Examples:
      teax issue create -r owner/repo --title "Fix login bug"
      teax issue create -r owner/repo -t "feat: Add dark mode" -b "Description here"
      teax issue create -r owner/repo -t "Bug" --labels "bug,urgent" --assignees "user1"
      teax -o json issue create -r owner/repo -t "Feature" --milestone "v1.0"
    """
    output: OutputFormat = ctx.obj["output"]
    try:
        owner, repo_name = parse_repo(repo)

        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Resolve label names to IDs (exact match for consistency with API)
            label_ids: list[int] | None = None
            if labels:
                label_names = [lb.strip() for lb in labels.split(",") if lb.strip()]
                if label_names:
                    existing_labels = client.list_repo_labels(owner, repo_name)
                    name_to_id = {lb.name: lb.id for lb in existing_labels}
                    label_ids = []
                    for name in label_names:
                        label_id = name_to_id.get(name)
                        if label_id is None:
                            raise ValueError(f"Label not found: {name}")
                        label_ids.append(label_id)

            # Resolve milestone name to ID
            milestone_id: int | None = None
            if milestone:
                milestone_id = client.resolve_milestone(owner, repo_name, milestone)

            # Parse assignees
            assignee_list: list[str] | None = None
            if assignees:
                assignee_list = [a.strip() for a in assignees.split(",") if a.strip()]

            # Create the issue
            created = client.create_issue(
                owner,
                repo_name,
                title,
                body=body,
                labels=label_ids,
                assignees=assignee_list,
                milestone=milestone_id,
            )

            # Output
            if output.format_type == "simple":
                console.print(
                    f"[green]✓[/green] Created #{created.number}: "
                    f"{safe_rich(created.title)}"
                )
            elif output.format_type == "json":
                import json

                output_data = {
                    "number": created.number,
                    "title": terminal_safe(created.title),
                    "state": terminal_safe(created.state),
                    "url": terminal_safe(created.html_url),
                    "labels": [terminal_safe(lb.name) for lb in (created.labels or [])],
                    "assignees": [
                        terminal_safe(a.login) for a in (created.assignees or [])
                    ],
                    "milestone": (
                        terminal_safe(created.milestone.title)
                        if created.milestone
                        else None
                    ),
                }
                click.echo(json.dumps(output_data, indent=2))
            else:  # table, csv, or tmux - use table output
                output.print_issues([created])

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Comment Commands ---


@issue.command("comment")
@click.argument("issue_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--message", "-m", "body", required=True, help="Comment body")
@click.pass_context
def issue_comment(ctx: click.Context, issue_num: int, repo: str, body: str) -> None:
    """Add a comment to an issue.

    Examples:
        teax issue comment 42 -r owner/repo -m "This is my comment"
        teax issue comment 42 -r owner/repo --message "Fixed in commit abc123"
    """
    login_name = ctx.obj.get("login_name")
    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=login_name) as client:
            comment = client.create_comment(owner, repo_name, issue_num, body)
            console.print(
                f"[green]✓[/green] Added comment #{comment.id} to issue #{issue_num}"
            )

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("comment-edit")
@click.argument("comment_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--message", "-m", "body", required=True, help="New comment body")
@click.pass_context
def issue_comment_edit(
    ctx: click.Context, comment_id: int, repo: str, body: str
) -> None:
    """Edit an existing comment.

    COMMENT_ID can be found using 'teax issue view <num> --comments'.

    Examples:
        teax issue comment-edit 12345 -r owner/repo -m "Updated comment text"
    """
    login_name = ctx.obj.get("login_name")
    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=login_name) as client:
            comment = client.edit_comment(owner, repo_name, comment_id, body)
            console.print(f"[green]✓[/green] Updated comment #{comment.id}")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@issue.command("comment-delete")
@click.argument("comment_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def issue_comment_delete(
    ctx: click.Context, comment_id: int, repo: str, yes: bool
) -> None:
    """Delete a comment.

    COMMENT_ID can be found using 'teax issue view <num> --comments'.

    Examples:
        teax issue comment-delete 12345 -r owner/repo
        teax issue comment-delete 12345 -r owner/repo -y
    """
    login_name = ctx.obj.get("login_name")
    owner, repo_name = parse_repo(repo)

    if not yes:
        if not click.confirm(f"Delete comment #{comment_id}?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    try:
        with GiteaClient(login_name=login_name) as client:
            client.delete_comment(owner, repo_name, comment_id)
            console.print(f"[green]✓[/green] Deleted comment #{comment_id}")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
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
                owner, repo_name, epic_title, body=body, labels=issue_labels
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


# --- Label Group ---


@main.group()
def label() -> None:
    """Label management commands."""
    pass


@label.command("ensure")
@click.argument("name")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--color", default="1d76db", help="Hex color (default: blue)")
@click.option("--description", default="", help="Label description")
@click.pass_context
def label_ensure(
    ctx: click.Context,
    name: str,
    repo: str,
    color: str,
    description: str,
) -> None:
    """Ensure a label exists (idempotent create).

    Creates the label if it doesn't exist, otherwise does nothing.
    Useful for sprint setup scripts.

    Examples:
        teax label ensure sprint/28 --repo owner/repo
        teax label ensure ready --repo owner/repo --color 00ff00
        teax label ensure "type/bug" -r owner/repo --description "Bug report"
    """
    # Validate hex color format
    if not re.match(r"^[0-9a-fA-F]{6}$", color):
        safe_color = terminal_safe(color)
        raise click.BadParameter(
            f"Color must be a 6-character hex code (e.g., 'ff0000'), got: {safe_color}"
        )

    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            label_obj, was_created = client.ensure_label(
                owner, repo_name, name, color, description
            )

            if was_created:
                output.print_mutation("created", name)
            else:
                output.print_mutation("exists", name)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Sprint Group ---


@main.group()
def sprint() -> None:
    """Sprint management commands."""
    pass


@sprint.command("status")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def sprint_status(ctx: click.Context, repo: str) -> None:
    """Show sprint overview.

    Displays the current sprint (highest sprint/N with open issues),
    counts of open/closed issues, ready queue size, and backlog size.

    Examples:
        teax sprint status --repo owner/repo
    """
    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Fetch all issues (both open and closed for counting)
            all_issues = client.list_issues(owner, repo_name, state="all")

            # Group issues by sprint number
            sprint_issues: dict[int, list[Any]] = {}
            ready_queue: list[Any] = []
            backlog: list[Any] = []

            for issue in all_issues:
                computed = compute_issue_fields(issue)
                sprint_num = computed["sprint_number"]

                if sprint_num is not None:
                    if sprint_num not in sprint_issues:
                        sprint_issues[sprint_num] = []
                    sprint_issues[sprint_num].append(issue)
                elif computed["is_ready"] and issue.state == "open":
                    ready_queue.append(issue)
                elif issue.state == "open":
                    backlog.append(issue)

            # Find current sprint (highest sprint with open issues)
            current_sprint = None
            for snum in sorted(sprint_issues.keys(), reverse=True):
                issues_in_sprint = sprint_issues[snum]
                if any(i.state == "open" for i in issues_in_sprint):
                    current_sprint = snum
                    break

            # Display output
            esc_repo = safe_rich(repo)
            console.print(f"\n[bold]Sprint Status: {esc_repo}[/bold]")
            console.print("━" * 30)

            if current_sprint is not None:
                issues_in_current = sprint_issues[current_sprint]
                open_count = sum(1 for i in issues_in_current if i.state == "open")
                closed_count = sum(1 for i in issues_in_current if i.state == "closed")
                console.print(f"\nCurrent Sprint: [cyan]{current_sprint}[/cyan]")
                console.print(
                    f"  Open: [yellow]{open_count}[/yellow] | "
                    f"Closed: [green]{closed_count}[/green]"
                )
            else:
                console.print("\n[dim]No active sprint found[/dim]")

            console.print(f"\nReady Queue: [cyan]{len(ready_queue)}[/cyan] issues")
            console.print(f"Backlog: [dim]{len(backlog)}[/dim] issues")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@sprint.command("ready")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.pass_context
def sprint_ready(ctx: click.Context, repo: str) -> None:
    """List issues in the ready queue.

    Shows open issues with the 'ready' label that are not yet assigned
    to a sprint (no sprint/* label).

    Examples:
        teax sprint ready --repo owner/repo
        teax sprint ready --repo owner/repo -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Fetch issues with ready label
            issues = client.list_issues(
                owner, repo_name, state="open", labels=["ready"]
            )

            # Filter out issues already in a sprint
            ready_issues = filter_issues_by_no_labels(issues, ["sprint/*"])

            output.print_issue_list(ready_issues, include_computed=True)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@sprint.command("issues")
@click.argument("sprint_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option(
    "--state",
    default="all",
    type=click.Choice(["open", "closed", "all"]),
    help="Filter by state (default: all)",
)
@click.pass_context
def sprint_issues(ctx: click.Context, sprint_num: int, repo: str, state: str) -> None:
    """List issues in a specific sprint.

    Shows all issues with the sprint/N label.

    Examples:
        teax sprint issues 28 --repo owner/repo
        teax sprint issues 28 --repo owner/repo --state open
    """
    if sprint_num < 1:
        raise click.BadParameter(f"Sprint number must be >= 1, got: {sprint_num}")

    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            issues = client.list_issues(
                owner, repo_name, state=state, labels=[f"sprint/{sprint_num}"]
            )

            output.print_issue_list(issues, include_computed=True)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@sprint.command("plan")
@click.argument("sprint_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option(
    "--issues",
    "issue_spec",
    help="Issue numbers to add (e.g., 17-23,25). Defaults to ready queue.",
)
@click.option("--confirm", is_flag=True, help="Execute (default: dry-run preview)")
@click.option(
    "--create-label", is_flag=True, help="Create sprint label if it doesn't exist"
)
@click.pass_context
def sprint_plan(
    ctx: click.Context,
    sprint_num: int,
    repo: str,
    issue_spec: str | None,
    confirm: bool,
    create_label: bool,
) -> None:
    """Plan a sprint by adding issues to it.

    By default, shows a preview of what would happen (dry-run).
    Use --confirm to execute the changes.

    If --issues is not specified, uses the ready queue (issues with 'ready'
    label but no sprint/* label).

    Examples:
        teax sprint plan 29 --repo owner/repo
        teax sprint plan 29 --repo owner/repo --issues 17-23,25
        teax sprint plan 29 --repo owner/repo --confirm
        teax sprint plan 29 --repo owner/repo --create-label --confirm
    """
    if sprint_num < 1:
        raise click.BadParameter(f"Sprint number must be >= 1, got: {sprint_num}")

    owner, repo_name = parse_repo(repo)
    sprint_label = f"sprint/{sprint_num}"

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Get issues to add
            if issue_spec:
                issue_nums = parse_issue_spec(issue_spec)
                issues_to_add = []
                for num in issue_nums:
                    try:
                        issue = client.get_issue(owner, repo_name, num)
                        issues_to_add.append(issue)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            console.print(
                                f"[yellow]Warning:[/yellow] Issue #{num} not found"
                            )
                        else:
                            raise
            else:
                # Default to ready queue
                issues = client.list_issues(
                    owner, repo_name, state="open", labels=["ready"]
                )
                issues_to_add = filter_issues_by_no_labels(issues, ["sprint/*"])

            if not issues_to_add:
                console.print("[dim]No issues to add to sprint[/dim]")
                return

            # Show preview
            esc_label = safe_rich(sprint_label)
            console.print(f"\n[bold]Sprint Plan: {esc_label}[/bold]")
            console.print(f"Issues to add: {len(issues_to_add)}\n")

            table = Table()
            table.add_column("#", style="cyan")
            table.add_column("Title")
            table.add_column("Current Labels", style="dim")

            for issue in issues_to_add:
                labels_str = ", ".join(
                    safe_rich(lb.name) for lb in (issue.labels or [])
                )
                table.add_row(str(issue.number), safe_rich(issue.title), labels_str)

            console.print(table)

            if not confirm:
                console.print(
                    "\n[yellow]DRY RUN[/yellow] - no changes made. "
                    "Add --confirm to execute."
                )
                return

            # Execute: ensure label exists if requested
            if create_label:
                _, was_created = client.ensure_label(
                    owner, repo_name, sprint_label, color="1d76db"
                )
                if was_created:
                    console.print(
                        f"\n[green]✓[/green] Created label [cyan]{esc_label}[/cyan]"
                    )

            # Add sprint label to each issue
            console.print(f"\nAdding [cyan]{esc_label}[/cyan] to issues...")
            success_count = 0
            error_count = 0

            for issue in issues_to_add:
                try:
                    client.add_issue_labels(
                        owner, repo_name, issue.number, [sprint_label]
                    )
                    console.print(f"  [green]✓[/green] #{issue.number}")
                    success_count += 1
                except CLI_ERRORS as e:
                    console.print(
                        f"  [red]✗[/red] #{issue.number}: {safe_rich(str(e))}"
                    )
                    error_count += 1

            # Summary
            console.print()
            console.print(
                f"[bold]Summary:[/bold] {success_count} added, {error_count} failed"
            )

            if error_count > 0:
                sys.exit(1)

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
    log = err_console if output.format_type in ("json", "csv", "simple") else console

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
                        client.delete_package_version(owner, pkg_type, name, v.version)
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
                log.print("[dim]Use --execute to actually delete these versions[/dim]")

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
            raise click.BadParameter(f"Invalid organisation name: {terminal_safe(org)}")

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
        raise click.BadParameter("Workflow ID cannot be empty or whitespace-only")
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


def resolve_run_id(
    client: GiteaClient,
    owner: str,
    repo: str,
    run_ref: str,
    *,
    force_number: bool = False,
    force_id: bool = False,
) -> int:
    """Resolve run_number or run_id to actual run_id.

    Uses a heuristic to distinguish run_numbers (typically < 10000) from run_ids
    (Gitea's global sequential IDs, typically larger numbers). Use force_number
    or force_id to override the heuristic.

    Args:
        client: GiteaClient instance
        owner: Repository owner
        repo: Repository name
        run_ref: Either a run_number or run_id as string
        force_number: If True, interpret as run_number regardless of value
        force_id: If True, interpret as run_id regardless of value

    Returns:
        The resolved run_id (Gitea's internal ID)

    Raises:
        ValueError: If run_ref can't be resolved or is invalid
    """
    if force_number and force_id:
        raise ValueError("Cannot specify both --by-number and --by-id")

    try:
        ref_int = int(run_ref)
    except ValueError as e:
        raise ValueError(f"Invalid run reference: {run_ref}") from e

    # Validate positive integer
    if ref_int <= 0:
        raise ValueError(f"Run reference must be positive, got: {ref_int}")

    # Force interpretation as run_id
    if force_id:
        return ref_int

    # Force interpretation as run_number or use heuristic for small numbers
    if force_number or ref_int < 10000:
        runs_list = client.list_runs(owner, repo, limit=100, max_pages=5)
        for r in runs_list:
            if r.run_number == ref_int:
                return r.id
        # Not found as run_number
        if force_number:
            raise ValueError(f"Run number {ref_int} not found in recent runs.")
        raise ValueError(
            f"Run number {ref_int} not found in recent runs. "
            f"If this is a run_id, use --by-id flag."
        )

    return ref_int


@main.group()
def runs() -> None:
    """Manage workflow runs - list, inspect, and debug CI/CD."""
    pass


@runs.command("status")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option(
    "--sha",
    "-s",
    help="Filter by commit SHA (prefix match). Use 'HEAD' for current git HEAD.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show failed job details (fetches jobs for failed workflows)",
)
@click.option(
    "--show",
    help=(
        "Explicit workflow list with custom abbreviations. "
        "Format: 'A:ci.yml,B:build.yml,D:deploy.yml'. "
        "Workflows not triggered show '-' status."
    ),
)
@click.pass_context
def runs_status(
    ctx: click.Context, repo: str, sha: str | None, verbose: bool, show: str | None
) -> None:
    """Show workflow health status (latest run per workflow).

    Quick overview of CI/CD health for all workflows.

    Exit codes:
      0 = All triggered workflows succeeded (not-triggered are neutral)
      1 = Any workflow failed
      2 = Workflows still running (none failed)
      3 = No workflows found/triggered for commit
      4 = Error (git HEAD, API error, invalid --show format)

    Examples:
        teax runs status -r owner/repo
        teax runs status -r owner/repo -o json
        teax runs status -r owner/repo --sha HEAD
        teax runs status -r owner/repo --sha abc123
        teax runs status -r owner/repo -o tmux  # For status bars
        teax runs status -r owner/repo --verbose  # Show failed job details
        teax runs status -r owner/repo --show "C:ci.yml,B:build.yml"
    """
    import subprocess

    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    # Parse --show specification if provided
    show_map: list[tuple[str, str]] | None = None
    if show is not None:
        try:
            show_map = parse_show_spec(show)
        except click.BadParameter as e:
            err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
            sys.exit(4)

    # Resolve HEAD to actual SHA if requested
    head_sha = sha
    if sha and sha.upper() == "HEAD":
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            head_sha = result.stdout.strip()[:12]
        except (subprocess.CalledProcessError, FileNotFoundError):
            err_console.print(
                "[red]Error:[/red] Could not resolve HEAD (not in git repo?)"
            )
            sys.exit(4)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            runs_list = client.list_runs(
                owner, repo_name, head_sha=head_sha, limit=50, max_pages=5
            )

            # Pre-fetch jobs for failed workflows when verbose
            workflow_jobs: dict[int, list[Any]] = {}
            if verbose:
                # Group runs by workflow, keep latest per workflow
                workflow_runs_map: dict[str, Any] = {}
                for r in runs_list:
                    wf_name = extract_workflow_name(r.path)
                    if wf_name not in workflow_runs_map:
                        workflow_runs_map[wf_name] = r

                # Determine which workflows to fetch jobs for
                if show_map:
                    # Only fetch for workflows specified in show_map
                    target_workflows = {wf for _, wf in show_map}
                else:
                    # Fetch for all workflows
                    target_workflows = set(workflow_runs_map.keys())

                for wf_name in target_workflows:
                    run = workflow_runs_map.get(wf_name)
                    if run and run.conclusion == "failure":
                        try:
                            workflow_jobs[run.id] = client.list_run_jobs(
                                owner, repo_name, run.id
                            )
                        except CLI_ERRORS:
                            # Degrade gracefully - skip job details for this run
                            pass

            overall_status = output.print_run_status(
                runs_list,
                commit_sha=head_sha,
                verbose=verbose,
                workflow_jobs=workflow_jobs,
                show_map=show_map,
            )

            # Exit codes based on overall status
            if overall_status == "success":
                sys.exit(0)
            elif overall_status == "failure":
                sys.exit(1)
            elif overall_status == "running":
                sys.exit(2)
            else:  # no_runs or pending
                sys.exit(3)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(4)


@runs.command("failed")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--sha", "-s", help="Check specific commit (default: latest failure)")
@click.option("--workflow", "-w", help="Filter to specific workflow")
@click.option("--logs", is_flag=True, help="Fetch first 50 lines of failed job logs")
@click.pass_context
def runs_failed(
    ctx: click.Context,
    repo: str,
    sha: str | None,
    workflow: str | None,
    logs: bool,
) -> None:
    """Show details of the most recent failed run.

    Finds the most recent failed workflow run and shows job-level details
    including which jobs failed and their status.

    Examples:
        teax runs failed -r owner/repo
        teax runs failed -r owner/repo --sha abc123
        teax runs failed -r owner/repo --workflow ci.yml
        teax runs failed -r owner/repo --logs
        teax runs failed -r owner/repo -o json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Find most recent failed run
            runs_list = client.list_runs(
                owner,
                repo_name,
                workflow=workflow,
                head_sha=sha,
                limit=50,
                max_pages=5,
            )

            failed_run = None
            for r in runs_list:
                if r.conclusion == "failure":
                    failed_run = r
                    break

            if not failed_run:
                if output.format_type == "json":
                    empty_result = {
                        "error": None,
                        "message": "No failed runs found",
                        "run": None,
                    }
                    click.echo(json.dumps(empty_result))
                elif sha:
                    console.print(
                        f"[dim]No failed runs found for commit {safe_rich(sha)}[/dim]"
                    )
                else:
                    console.print("[dim]No failed runs found[/dim]")
                sys.exit(0)

            # Fetch jobs for the failed run
            jobs = client.list_run_jobs(owner, repo_name, failed_run.id)
            failed_jobs = [j for j in jobs if j.conclusion == "failure"]

            if output.format_type == "json":
                output_data: dict[str, Any] = {
                    "run_id": failed_run.id,
                    "run_number": failed_run.run_number,
                    "workflow": terminal_safe(extract_workflow_name(failed_run.path)),
                    "head_sha": terminal_safe(failed_run.head_sha),
                    "head_branch": terminal_safe(failed_run.head_branch or ""),
                    "event": terminal_safe(failed_run.event),
                    "jobs": [
                        {
                            "id": j.id,
                            "name": terminal_safe(j.name),
                            "status": terminal_safe(j.status),
                            "conclusion": (
                                terminal_safe(j.conclusion) if j.conclusion else None
                            ),
                        }
                        for j in jobs
                    ],
                    "failed_jobs": [terminal_safe(j.name) for j in failed_jobs],
                }
                # Add log snippets if requested
                if logs and failed_jobs:
                    logs_dict: dict[str, list[str] | str] = {}
                    for j in failed_jobs:
                        try:
                            job_logs = client.get_job_logs(owner, repo_name, j.id)
                            # First 50 lines
                            lines = job_logs.split("\n")[:50]
                            logs_dict[terminal_safe(j.name)] = [
                                terminal_safe(line) for line in lines
                            ]
                        except CLI_ERRORS:
                            logs_dict[terminal_safe(j.name)] = "(log fetch failed)"
                    output_data["logs"] = logs_dict
                click.echo(json.dumps(output_data, indent=2))

            elif output.format_type == "simple":
                wf_name = extract_workflow_name(failed_run.path)
                click.echo(
                    f"{terminal_safe(wf_name)} #{failed_run.run_number} "
                    f"({terminal_safe(failed_run.head_sha[:8])})"
                )
                for j in failed_jobs:
                    click.echo(f"  ✗ {terminal_safe(j.name)}")
                    if logs:
                        try:
                            job_logs = client.get_job_logs(owner, repo_name, j.id)
                            lines = job_logs.split("\n")[:50]
                            for line in lines:
                                click.echo(f"    {terminal_safe(line)}")
                        except CLI_ERRORS:
                            click.echo("    (log fetch failed)")

            elif output.format_type == "csv":
                out = io.StringIO()
                writer = csv.writer(out)
                writer.writerow(
                    [
                        "run_id",
                        "run_number",
                        "workflow",
                        "head_sha",
                        "job_id",
                        "job_name",
                        "job_conclusion",
                    ]
                )
                wf_name = extract_workflow_name(failed_run.path)
                for j in failed_jobs:
                    writer.writerow(
                        [
                            failed_run.id,
                            failed_run.run_number,
                            csv_safe(wf_name),
                            csv_safe(failed_run.head_sha[:8]),
                            j.id,
                            csv_safe(j.name),
                            csv_safe(j.conclusion or ""),
                        ]
                    )
                click.echo(out.getvalue().rstrip())

            else:  # table (default)
                wf_name = extract_workflow_name(failed_run.path)
                console.print(
                    f"[bold red]Failed:[/bold red] {safe_rich(wf_name)} "
                    f"#{failed_run.run_number}"
                )
                console.print(
                    f"[dim]Commit: {safe_rich(failed_run.head_sha[:8])} "
                    f"({safe_rich(failed_run.head_branch or 'unknown')})[/dim]"
                )
                console.print()

                if not failed_jobs:
                    console.print("[yellow]No failed jobs found[/yellow]")
                else:
                    console.print("[bold]Failed Jobs:[/bold]")
                    for j in failed_jobs:
                        console.print(f"  [red]✗ {safe_rich(j.name)}[/red]")

                        if logs:
                            try:
                                job_logs = client.get_job_logs(owner, repo_name, j.id)
                                lines = job_logs.split("\n")[:50]
                                console.print("[dim]  Log (first 50 lines):[/dim]")
                                for line in lines:
                                    console.print(f"    {safe_rich(line)}")
                            except CLI_ERRORS:
                                console.print("[dim]  (Could not fetch logs)[/dim]")
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
                owner,
                repo_name,
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
@click.argument("run_ref")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--errors-only", "-e", is_flag=True, help="Show only failed jobs/steps")
@click.option("--by-number", is_flag=True, help="Force interpretation as run_number")
@click.option("--by-id", is_flag=True, help="Force interpretation as run_id")
@click.pass_context
def runs_get(
    ctx: click.Context,
    run_ref: str,
    repo: str,
    errors_only: bool,
    by_number: bool,
    by_id: bool,
) -> None:
    """Get workflow run details with jobs and steps.

    RUN_REF can be either a run_number (small sequential number like 223)
    or a run_id (Gitea's internal ID). Small numbers (< 10000) are first
    checked as run_numbers. Use --by-number or --by-id to override.

    Examples:
        teax runs get 223 -r owner/repo           # Uses run_number
        teax runs get 12345 -r owner/repo         # Uses run_id
        teax runs get 42 -r owner/repo --by-id    # Force as run_id
        teax runs get 15000 --by-number           # Force as run_number
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            run_id = resolve_run_id(
                client,
                owner,
                repo_name,
                run_ref,
                force_number=by_number,
                force_id=by_id,
            )
            jobs = client.list_run_jobs(owner, repo_name, run_id)
            output.print_jobs(jobs, errors_only=errors_only)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("jobs")
@click.argument("run_ref")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--errors-only", "-e", is_flag=True, help="Show only failed jobs")
@click.option("--by-number", is_flag=True, help="Force interpretation as run_number")
@click.option("--by-id", is_flag=True, help="Force interpretation as run_id")
@click.pass_context
def runs_jobs(
    ctx: click.Context,
    run_ref: str,
    repo: str,
    errors_only: bool,
    by_number: bool,
    by_id: bool,
) -> None:
    """List jobs for a workflow run.

    RUN_REF can be either a run_number (small sequential number like 223)
    or a run_id (Gitea's internal ID). Small numbers (< 10000) are first
    checked as run_numbers. Use --by-number or --by-id to override.

    Examples:
        teax runs jobs 223 -r owner/repo           # Uses run_number
        teax runs jobs 12345 -r owner/repo         # Uses run_id
        teax runs jobs 42 -r owner/repo --by-id    # Force as run_id
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            run_id = resolve_run_id(
                client,
                owner,
                repo_name,
                run_ref,
                force_number=by_number,
                force_id=by_id,
            )
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

    return "\n".join(lines)


@runs.command("logs")
@click.argument("job_id", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--tail", "-t", type=int, help="Show last N lines")
@click.option("--head", "-H", type=int, help="Show first N lines")
@click.option("--grep", "-g", help="Filter lines matching pattern (regex)")
@click.option("--context", "-C", type=int, default=0, help="Context lines around grep")
@click.option("--strip-ansi", is_flag=True, help="Strip all escape sequences")
@click.option(
    "--raw", is_flag=True, help="Output exact server bytes (no filtering/sanitization)"
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
    if raw and (strip_ansi or tail is not None or head is not None or grep or context):
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
@click.argument("run_ref")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--by-number", is_flag=True, help="Force interpretation as run_number")
@click.option("--by-id", is_flag=True, help="Force interpretation as run_id")
@click.pass_context
def runs_rerun(
    ctx: click.Context, run_ref: str, repo: str, by_number: bool, by_id: bool
) -> None:
    """Rerun a workflow (via dispatch).

    RUN_REF can be either a run_number (small sequential number like 223)
    or a run_id (Gitea's internal ID). Small numbers (< 10000) are first
    checked as run_numbers. Use --by-number or --by-id to override.

    Note: Uses workflow dispatch as a workaround since Gitea's native
    rerun API is not yet available. Limitations:
    - Only works for workflows with workflow_dispatch trigger
    - Original inputs not preserved
    - Original event context (PR number, etc.) lost

    Examples:
        teax runs rerun 223 -r owner/repo           # Uses run_number
        teax runs rerun 12345 -r owner/repo         # Uses run_id
        teax runs rerun 42 -r owner/repo --by-id    # Force as run_id
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            run_id = resolve_run_id(
                client,
                owner,
                repo_name,
                run_ref,
                force_number=by_number,
                force_id=by_id,
            )
            # Get run info first to show what we're rerunning
            run = client.get_run(owner, repo_name, run_id)
            workflow_name = extract_workflow_name(run.path)

            client.rerun_workflow(owner, repo_name, run_id)

            console.print(
                "[yellow]Note:[/yellow] Using workflow dispatch "
                "(native rerun API not available)"
            )
            output.print_mutation(
                "dispatched",
                f"{terminal_safe(workflow_name)} on {terminal_safe(run.head_branch)}",
            )
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@runs.command("delete")
@click.argument("run_ref")
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--by-number", is_flag=True, help="Force interpretation as run_number")
@click.option("--by-id", is_flag=True, help="Force interpretation as run_id")
@click.pass_context
def runs_delete(
    ctx: click.Context,
    run_ref: str,
    repo: str,
    yes: bool,
    by_number: bool,
    by_id: bool,
) -> None:
    """Delete a workflow run.

    RUN_REF can be either a run_number (small sequential number like 223)
    or a run_id (Gitea's internal ID). Small numbers (< 10000) are first
    checked as run_numbers. Use --by-number or --by-id to override.

    Examples:
        teax runs delete 223 -r owner/repo           # Uses run_number
        teax runs delete 12345 -r owner/repo         # Uses run_id
        teax runs delete 42 -r owner/repo --by-id    # Force as run_id
        teax runs delete 42 -r owner/repo -y         # Skip confirmation
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Resolve and fetch run details first for confirmation
            run_id = resolve_run_id(
                client,
                owner,
                repo_name,
                run_ref,
                force_number=by_number,
                force_id=by_id,
            )
            run = client.get_run(owner, repo_name, run_id)

            # Confirm with details after resolution
            if not yes:
                wf_name = extract_workflow_name(run.path)
                sha = run.head_sha[:8] if run.head_sha else "unknown"
                confirm_msg = (
                    f"Delete run #{run.run_number} "
                    f"({terminal_safe(wf_name)}, {terminal_safe(sha)})?"
                )
                if not click.confirm(confirm_msg):
                    console.print("[yellow]Cancelled[/yellow]")
                    return

            client.delete_run(owner, repo_name, run_id)
            output.print_mutation("deleted", f"run #{run.run_number}")
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


# --- Token Commands ---


@main.group()
def token() -> None:
    """Manage API access tokens."""
    pass


@token.command("create")
@click.argument("name")
@click.option(
    "--scopes",
    "-s",
    help="Comma-separated scopes (e.g., write:repository,write:package)",
)
@click.option(
    "--password-env",
    "-p",
    help="Environment variable containing password (default: prompt)",
)
@click.pass_context
def token_create(
    ctx: click.Context,
    name: str,
    scopes: str | None,
    password_env: str | None,
) -> None:
    """Create a new API access token.

    Creates a new access token for the current user. Requires password
    authentication (Gitea does not allow creating tokens via token auth).

    The token value is only shown once after creation - store it securely.

    Common scopes:
        - read:user - Read user info
        - write:repository - Read/write repos
        - write:package - Read/write packages
        - write:issue - Read/write issues
        - write:admin - Administrative access
        - all - All permissions (default if no scopes specified)

    Examples:
        teax token create my-ci-token --scopes write:repository,write:package
        teax token create my-token --password-env MY_PASSWORD
        teax token create my-token  # Prompts for password
    """
    output: OutputFormat = ctx.obj["output"]

    # Get password from environment or prompt
    if password_env:
        password = os.environ.get(password_env)
        if not password:
            err_console.print(
                f"[red]Error:[/red] Environment variable "
                f"{safe_rich(password_env)} not set or empty"
            )
            sys.exit(1)
    else:
        password = click.prompt("Password", hide_input=True)
        if not password:
            err_console.print("[red]Error:[/red] Password cannot be empty")
            sys.exit(1)

    # Parse scopes
    scope_list: list[str] | None = None
    if scopes:
        scope_list = [s.strip() for s in scopes.split(",") if s.strip()]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Get username from login config
            username = client._login.user
            if not username:
                err_console.print(
                    "[red]Error:[/red] No username in tea config. "
                    "Run 'tea login add' to configure."
                )
                sys.exit(1)

            token_obj = client.create_access_token(
                username=username,
                password=password,
                name=name,
                scopes=scope_list,
            )

            if output.format_type == "json":
                token_data = {
                    "id": token_obj.id,
                    "name": terminal_safe(token_obj.name),
                    "token": terminal_safe(token_obj.sha1),
                    "scopes": [terminal_safe(s) for s in token_obj.scopes],
                }
                click.echo(json.dumps(token_data, indent=2))
            elif output.format_type == "simple":
                # Just output the token for scripting
                click.echo(terminal_safe(token_obj.sha1))
            else:  # table or csv
                console.print(f"[green]✓[/green] Created token: {safe_rich(name)}")
                console.print()
                console.print(f"[bold]Token:[/bold] {safe_rich(token_obj.sha1)}")
                console.print()
                console.print(
                    "[yellow]Warning:[/yellow] This token is only shown once. "
                    "Store it securely."
                )
                if token_obj.scopes:
                    scopes_str = ", ".join(safe_rich(s) for s in token_obj.scopes)
                    console.print(f"[dim]Scopes: {scopes_str}[/dim]")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            err_console.print(
                "[red]Error:[/red] Authentication failed. Check username and password."
            )
        elif e.response.status_code == 422:
            err_console.print(
                f"[red]Error:[/red] Token name '{safe_rich(name)}' already exists."
            )
        else:
            err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


# --- Milestone Commands ---


@main.group()
def milestone() -> None:
    """Manage Gitea milestones for sprint tracking."""
    pass


@milestone.command("list")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.option(
    "--state",
    type=click.Choice(["open", "closed", "all"]),
    default="all",
    help="Filter by state (default: all)",
)
@click.pass_context
def milestone_list(
    ctx: click.Context,
    repo: str,
    state: str,
) -> None:
    """List milestones in a repository.

    Examples:
        teax milestone list -r owner/repo
        teax milestone list -r owner/repo --state open
        teax milestone list -r owner/repo --output json
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            milestones = client.list_milestones(owner, repo_name, state=state)
            output.print_milestones(milestones)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@milestone.command("create")
@click.argument("title")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.option(
    "-d",
    "--description",
    default="",
    help="Milestone description",
)
@click.option(
    "--due-date",
    help="Due date in YYYY-MM-DD format",
)
@click.option(
    "--if-not-exists",
    is_flag=True,
    help="Don't error if milestone already exists",
)
@click.pass_context
def milestone_create(
    ctx: click.Context,
    title: str,
    repo: str,
    description: str,
    due_date: str | None,
    if_not_exists: bool,
) -> None:
    """Create a new milestone.

    Examples:
        teax milestone create "Sprint 50" -r owner/repo
        teax milestone create "Sprint 50" -r owner/repo --due-date 2026-03-01
        teax milestone create "Sprint 50" -r owner/repo -d "Goals" --if-not-exists
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    # Parse and validate due date
    due_on: str | None = None
    if due_date:
        try:
            from datetime import datetime

            parsed = datetime.strptime(due_date, "%Y-%m-%d")
            due_on = parsed.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            err_console.print(
                f"[red]Error:[/red] Invalid date format: {safe_rich(due_date)}. "
                "Use YYYY-MM-DD."
            )
            sys.exit(1)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Check if milestone exists when --if-not-exists is used
            if if_not_exists:
                try:
                    milestone_id = client.resolve_milestone(owner, repo_name, title)
                    ms = client.get_milestone(owner, repo_name, milestone_id)
                    if output.format_type == "json":
                        click.echo(
                            json.dumps(
                                {
                                    "id": ms.id,
                                    "title": terminal_safe(ms.title),
                                    "state": terminal_safe(ms.state),
                                    "created": False,
                                },
                                indent=2,
                            )
                        )
                    elif output.format_type == "simple":
                        click.echo(str(ms.id))
                    else:
                        console.print(
                            f"[dim]Milestone already exists:[/dim] "
                            f"{safe_rich(ms.title)} (ID: {ms.id})"
                        )
                    return
                except (ValueError, httpx.HTTPStatusError):
                    pass  # Milestone doesn't exist, proceed to create

            ms = client.create_milestone(
                owner,
                repo_name,
                title,
                description=description,
                due_on=due_on,
            )

            if output.format_type == "json":
                click.echo(
                    json.dumps(
                        {
                            "id": ms.id,
                            "title": terminal_safe(ms.title),
                            "state": terminal_safe(ms.state),
                            "created": True,
                        },
                        indent=2,
                    )
                )
            elif output.format_type == "simple":
                click.echo(str(ms.id))
            else:
                console.print(
                    f"[green]✓[/green] Created milestone: "
                    f"{safe_rich(ms.title)} (ID: {ms.id})"
                )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            err_console.print(
                f"[red]Error:[/red] Milestone '{safe_rich(title)}' already exists. "
                "Use --if-not-exists to skip."
            )
        else:
            err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)
    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@milestone.command("close")
@click.argument("milestone_ref")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.pass_context
def milestone_close(
    ctx: click.Context,
    milestone_ref: str,
    repo: str,
) -> None:
    """Close a milestone.

    MILESTONE_REF can be an ID or title.

    Examples:
        teax milestone close "Sprint 50" -r owner/repo
        teax milestone close 5 -r owner/repo
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            milestone_id = client.resolve_milestone(owner, repo_name, milestone_ref)
            ms = client.update_milestone(owner, repo_name, milestone_id, state="closed")

            if output.format_type == "json":
                click.echo(
                    json.dumps(
                        {
                            "id": ms.id,
                            "title": terminal_safe(ms.title),
                            "state": terminal_safe(ms.state),
                        },
                        indent=2,
                    )
                )
            elif output.format_type == "simple":
                click.echo(terminal_safe(ms.state))
            else:
                console.print(
                    f"[green]✓[/green] Closed milestone: {safe_rich(ms.title)}"
                )

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@milestone.command("open")
@click.argument("milestone_ref")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.pass_context
def milestone_open(
    ctx: click.Context,
    milestone_ref: str,
    repo: str,
) -> None:
    """Reopen a closed milestone.

    MILESTONE_REF can be an ID or title.

    Examples:
        teax milestone open "Sprint 50" -r owner/repo
        teax milestone open 5 -r owner/repo
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            milestone_id = client.resolve_milestone(owner, repo_name, milestone_ref)
            ms = client.update_milestone(owner, repo_name, milestone_id, state="open")

            if output.format_type == "json":
                click.echo(
                    json.dumps(
                        {
                            "id": ms.id,
                            "title": terminal_safe(ms.title),
                            "state": terminal_safe(ms.state),
                        },
                        indent=2,
                    )
                )
            elif output.format_type == "simple":
                click.echo(terminal_safe(ms.state))
            else:
                console.print(
                    f"[green]✓[/green] Reopened milestone: {safe_rich(ms.title)}"
                )

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


@milestone.command("edit")
@click.argument("milestone_ref")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.option(
    "-t",
    "--title",
    help="New milestone title",
)
@click.option(
    "-d",
    "--description",
    help="New milestone description",
)
@click.option(
    "--due-date",
    help="New due date (YYYY-MM-DD) or empty string to clear",
)
@click.pass_context
def milestone_edit(
    ctx: click.Context,
    milestone_ref: str,
    repo: str,
    title: str | None,
    description: str | None,
    due_date: str | None,
) -> None:
    """Edit a milestone.

    MILESTONE_REF can be an ID or title.

    Examples:
        teax milestone edit "Sprint 50" -r owner/repo -t "Sprint 50 (Extended)"
        teax milestone edit 5 -r owner/repo --due-date 2026-03-15
        teax milestone edit "Sprint 50" -r owner/repo --due-date ""  # Clear due date
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    if title is None and description is None and due_date is None:
        err_console.print(
            "[red]Error:[/red] At least one of --title, --description, "
            "or --due-date is required."
        )
        sys.exit(1)

    # Parse and validate due date
    due_on: str | None = None
    if due_date is not None:
        if due_date == "":
            due_on = ""  # Empty string clears the due date
        else:
            try:
                from datetime import datetime

                parsed = datetime.strptime(due_date, "%Y-%m-%d")
                due_on = parsed.strftime("%Y-%m-%dT00:00:00Z")
            except ValueError:
                err_console.print(
                    f"[red]Error:[/red] Invalid date format: {safe_rich(due_date)}. "
                    "Use YYYY-MM-DD or empty string to clear."
                )
                sys.exit(1)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            milestone_id = client.resolve_milestone(owner, repo_name, milestone_ref)
            ms = client.update_milestone(
                owner,
                repo_name,
                milestone_id,
                title=title,
                description=description,
                due_on=due_on,
            )

            if output.format_type == "json":
                click.echo(
                    json.dumps(
                        {
                            "id": ms.id,
                            "title": terminal_safe(ms.title),
                            "state": terminal_safe(ms.state),
                            "description": terminal_safe(ms.description),
                            "due_on": ms.due_on.isoformat() if ms.due_on else None,
                        },
                        indent=2,
                    )
                )
            elif output.format_type == "simple":
                click.echo(str(ms.id))
            else:
                console.print(
                    f"[green]✓[/green] Updated milestone: {safe_rich(ms.title)}"
                )

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


def _get_milestone_lifecycle_state(ms: Any) -> str:
    """Determine lifecycle state of a milestone.

    Returns:
        One of: "completed", "in_progress", "planned"
    """
    from datetime import datetime

    today_utc = datetime.now(UTC).date()

    if ms.state == "closed":
        return "completed"
    elif ms.created_at:
        # Normalize to UTC before comparing to handle timezone differences
        created_utc = ms.created_at.astimezone(UTC).date()
        if created_utc <= today_utc:
            return "in_progress"
    return "planned"


@milestone.command("state")
@click.argument("milestone_ref")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.pass_context
def milestone_state(
    ctx: click.Context,
    milestone_ref: str,
    repo: str,
) -> None:
    """Get lifecycle state of a milestone.

    Outputs one of: completed, in_progress, planned, not_found

    State determination:
    - completed: milestone is closed
    - in_progress: milestone is open and created_at <= today
    - planned: milestone is open and created_at > today

    MILESTONE_REF can be an ID or title.

    Examples:
        teax milestone state "Sprint 50" -r owner/repo
        teax milestone state 5 -r owner/repo --output simple
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            try:
                milestone_id = client.resolve_milestone(owner, repo_name, milestone_ref)
                ms = client.get_milestone(owner, repo_name, milestone_id)
            except ValueError:
                # Milestone not found
                if output.format_type == "json":
                    data = {
                        "milestone": terminal_safe(milestone_ref),
                        "state": "not_found",
                    }
                    click.echo(json.dumps(data, indent=2))
                else:
                    click.echo("not_found")
                return

            lifecycle_state = _get_milestone_lifecycle_state(ms)

            if output.format_type == "json":
                created = ms.created_at.isoformat() if ms.created_at else None
                click.echo(
                    json.dumps(
                        {
                            "id": ms.id,
                            "title": terminal_safe(ms.title),
                            "milestone_state": terminal_safe(ms.state),
                            "lifecycle_state": lifecycle_state,
                            "created_at": created,
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(lifecycle_state)

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


def _extract_sprint_number(title: str) -> int | None:
    """Extract sprint number from milestone title.

    Matches patterns like "Sprint 50", "sprint-50", "Sprint #50".

    Returns:
        Sprint number or None if not a sprint milestone.
    """
    match = re.match(r"sprint[\s#-]*(\d+)", title.lower())
    if match:
        return int(match.group(1))
    return None


@milestone.command("current")
@click.option(
    "-r",
    "--repo",
    required=True,
    help="Repository in owner/repo format",
)
@click.pass_context
def milestone_current(
    ctx: click.Context,
    repo: str,
) -> None:
    """Get the current in-progress sprint milestone.

    Finds the lowest-numbered sprint that is in_progress (open and started).
    Falls back to the lowest open sprint if none are in_progress.

    Outputs nothing if no sprint milestones exist.

    Examples:
        teax milestone current -r owner/repo
        CURRENT=$(teax milestone current -r owner/repo --output simple)
    """
    owner, repo_name = parse_repo(repo)
    output: OutputFormat = ctx.obj["output"]

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            milestones = client.list_milestones(owner, repo_name, state="open")

            # Filter to sprint milestones and extract numbers
            sprints: list[tuple[int, Any]] = []  # (sprint_number, milestone)
            for ms in milestones:
                num = _extract_sprint_number(ms.title)
                if num is not None:
                    sprints.append((num, ms))

            if not sprints:
                if output.format_type == "json":
                    click.echo(json.dumps({"current": None}, indent=2))
                # simple/table: output nothing
                return

            # Sort by sprint number
            sprints.sort(key=lambda x: x[0])

            # Find lowest in_progress sprint
            current: Any = None
            for _num, ms in sprints:
                state = _get_milestone_lifecycle_state(ms)
                if state == "in_progress":
                    current = ms
                    break

            # Fallback to lowest open sprint
            if current is None:
                current = sprints[0][1]

            if output.format_type == "json":
                lifecycle = _get_milestone_lifecycle_state(current)
                data = {
                    "current": {
                        "id": current.id,
                        "title": terminal_safe(current.title),
                        "sprint_number": _extract_sprint_number(current.title),
                        "lifecycle_state": lifecycle,
                    }
                }
                click.echo(json.dumps(data, indent=2))
            elif output.format_type == "simple":
                click.echo(terminal_safe(current.title))
            else:
                lifecycle = _get_milestone_lifecycle_state(current)
                state_style = "green" if lifecycle == "in_progress" else "yellow"
                console.print(
                    f"Current sprint: [bold]{safe_rich(current.title)}[/bold] "
                    f"[{state_style}]({lifecycle})[/{state_style}]"
                )

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {safe_rich(str(e))}")
        sys.exit(1)


if __name__ == "__main__":
    main()
