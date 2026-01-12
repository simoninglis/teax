"""teax CLI - Gitea companion for tea feature gaps."""

import csv
import io
import sys
from typing import Any

import click
import httpx
from rich.console import Console
from rich.table import Table

from teax import __version__
from teax.api import GiteaClient

console = Console()
err_console = Console(stderr=True)

# Exception types caught by CLI commands
CLI_ERRORS = (
    httpx.HTTPStatusError,
    httpx.RequestError,
    ValueError,
    FileNotFoundError,
)


def parse_repo(repo: str) -> tuple[str, str]:
    """Parse owner/repo string into components."""
    if "/" not in repo:
        raise click.BadParameter(
            f"Repository must be in 'owner/repo' format, got: {repo}"
        )
    parts = repo.split("/", 1)
    return parts[0], parts[1]


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
        click.BadParameter: If spec is invalid
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
                raise click.BadParameter(f"Invalid range format: {part}")
            try:
                start = int(range_parts[0].strip())
                end = int(range_parts[1].strip())
            except ValueError as e:
                raise click.BadParameter(f"Invalid number in range: {part}") from e
            if start > end:
                raise click.BadParameter(f"Range start must be <= end: {part}")
            result.update(range(start, end + 1))
        else:
            # Handle single number
            try:
                result.add(int(part))
            except ValueError as e:
                raise click.BadParameter(f"Invalid issue number: {part}") from e

    if not result:
        raise click.BadParameter("No valid issue numbers in specification")

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
                writer.writerow([d.number, d.title, d.state, d.repository.full_name])
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
                    d.title,
                    f"[{state_style}]{d.state}[/{state_style}]",
                    d.repository.full_name,
                )
            console.print(table)

    def print_labels(self, labels: list[Any]) -> None:
        """Print label list."""
        if self.format_type == "simple":
            for label in labels:
                click.echo(label.name)
        elif self.format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["name", "color", "description"])
            for label in labels:
                writer.writerow([label.name, label.color, label.description])
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
                table.add_row(label.name, f"#{label.color}", label.description)
            console.print(table)


# --- Main CLI Group ---


@click.group()
@click.version_option(__version__, prog_name="teax")
@click.option("--login", "-l", "login_name", help="Use specific tea login")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["table", "simple", "csv"]),
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
        err_console.print(f"[red]Error:[/red] {e}")
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
        err_console.print(f"[red]Error:[/red] {e}")
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
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# --- Issue Group ---


@main.group()
def issue() -> None:
    """Edit issues (labels, assignees, milestones)."""
    pass


@issue.command("edit")
@click.argument("issue_num", type=int)
@click.option("--repo", "-r", required=True, help="Repository (owner/repo)")
@click.option("--add-labels", help="Labels to add (comma-separated)")
@click.option("--rm-labels", help="Labels to remove (comma-separated)")
@click.option("--set-labels", help="Replace all labels (comma-separated)")
@click.option("--assignees", help="Set assignees (comma-separated usernames)")
@click.option("--milestone", help="Set milestone (ID, empty to clear)")
@click.option("--title", help="Set new title")
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
) -> None:
    """Edit an existing issue.

    Examples:
        teax issue edit 25 --repo homelab/myproject --add-labels "epic/foo,prio/p1"
        teax issue edit 25 --repo homelab/myproject --rm-labels "needs-triage"
        teax issue edit 25 --repo homelab/myproject --assignees "user1,user2"
        teax issue edit 25 --repo homelab/myproject --milestone 5
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

            if assignees is not None:
                usernames = [u.strip() for u in assignees.split(",") if u.strip()]
                edit_kwargs["assignees"] = usernames
                changes_made.append(f"assignees: {', '.join(usernames)}")

            if milestone is not None:
                if milestone == "" or milestone.lower() == "none":
                    edit_kwargs["milestone"] = 0
                    changes_made.append("milestone: cleared")
                else:
                    # Try to parse as int, otherwise would need to look up by name
                    try:
                        edit_kwargs["milestone"] = int(milestone)
                        changes_made.append(f"milestone: {milestone}")
                    except ValueError:
                        err_console.print(
                            "[yellow]Warning:[/yellow] Milestone lookup by name "
                            "not yet implemented. Use milestone ID instead."
                        )

            if edit_kwargs:
                client.edit_issue(owner, repo_name, issue_num, **edit_kwargs)

            if changes_made:
                console.print(f"[green]Updated issue #{issue_num}:[/green]")
                for change in changes_made:
                    console.print(f"  - {change}")
            else:
                console.print("[yellow]No changes specified[/yellow]")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {e}")
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
        err_console.print(f"[red]Error:[/red] {e}")
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
    console.print(f"\n[bold]Bulk edit {len(issue_nums)} issues in {repo}[/bold]")
    console.print(f"Issues: {', '.join(f'#{n}' for n in issue_nums[:10])}", end="")
    if len(issue_nums) > 10:
        console.print(f" ... and {len(issue_nums) - 10} more")
    else:
        console.print()
    console.print("\n[bold]Changes:[/bold]")
    for change in changes:
        console.print(f"  • {change}")
    console.print()

    # Confirm unless --yes
    if not yes:
        if not click.confirm("Proceed with changes?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    success_count = 0
    error_count = 0
    errors: list[tuple[int, str]] = []

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
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
                            edit_kwargs["milestone"] = int(milestone)

                    if edit_kwargs:
                        client.edit_issue(owner, repo_name, issue_num, **edit_kwargs)

                    console.print(f"  [green]✓[/green] #{issue_num}")
                    success_count += 1

                except CLI_ERRORS as e:
                    console.print(f"  [red]✗[/red] #{issue_num}: {e}")
                    errors.append((issue_num, str(e)))
                    error_count += 1

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {e}")
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

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Check if epic label exists, create if not
            existing_labels = client.list_repo_labels(owner, repo_name)
            label_names = {label.name: label.id for label in existing_labels}

            if epic_label not in label_names:
                console.print(f"Creating label [cyan]{epic_label}[/cyan]...")
                created_label = client.create_label(
                    owner, repo_name, epic_label, color, f"Epic: {name}"
                )
                label_names[epic_label] = created_label.id
                console.print(f"  [green]✓[/green] Created label #{created_label.id}")

            # Build the epic body with checklist if there are children
            body_lines = [f"# {epic_title}", "", "## Child Issues", ""]
            if children:
                for child_num in children:
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
            console.print(f"Creating epic issue [cyan]{epic_title}[/cyan]...")
            issue = client.create_issue(
                owner, repo_name, epic_title, body, labels=issue_labels
            )
            console.print(f"  [green]✓[/green] Created issue #{issue.number}")

            # Apply epic label to child issues
            if children:
                console.print(f"Applying [cyan]{epic_label}[/cyan] to child issues...")
                for child_num in children:
                    try:
                        client.add_issue_labels(
                            owner, repo_name, child_num, [epic_label]
                        )
                        console.print(f"  [green]✓[/green] #{child_num}")
                    except CLI_ERRORS as e:
                        console.print(f"  [red]✗[/red] #{child_num}: {e}")

            # Print summary
            console.print()
            console.print("[bold]Epic created successfully![/bold]")
            console.print(f"  Issue: #{issue.number}")
            console.print(f"  Label: {epic_label}")
            if children:
                console.print(f"  Children: {len(children)} issues labeled")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {e}")
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

            # Parse child issues from body
            child_nums = _parse_epic_children(epic_issue.body or "")

            if not child_nums:
                console.print(f"[bold]Epic #{issue}:[/bold] {epic_issue.title}")
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
            console.print(f"\n[bold]Epic #{issue}:[/bold] {epic_issue.title}")
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
                    console.print(f"  [green]✓[/green] #{num} {title}")

            if open_issues:
                console.print(f"\n[yellow]Open ({len(open_issues)}):[/yellow]")
                for num, title in open_issues:
                    console.print(f"  [ ] #{num} {title}")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {e}")
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

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            # Fetch the epic issue
            epic = client.get_issue(owner, repo_name, epic_issue)

            # Find the epic label from the issue's labels
            epic_label = None
            for label in epic.labels:
                if label.name.startswith("epic/"):
                    epic_label = label.name
                    break

            if not epic_label:
                console.print(
                    f"[yellow]Warning:[/yellow] No epic/* label found on #{epic_issue}"
                )

            # Update the epic body with new children
            new_body = _append_children_to_body(epic.body, list(children))
            client.edit_issue(owner, repo_name, epic_issue, body=new_body)
            console.print(f"[green]✓[/green] Updated epic #{epic_issue} body")

            # Apply epic label to child issues
            if epic_label:
                console.print(f"Applying [cyan]{epic_label}[/cyan] to child issues...")
                for child_num in children:
                    try:
                        client.add_issue_labels(
                            owner, repo_name, child_num, [epic_label]
                        )
                        console.print(f"  [green]✓[/green] #{child_num}")
                    except CLI_ERRORS as e:
                        console.print(f"  [red]✗[/red] #{child_num}: {e}")

            # Print summary
            console.print()
            count = len(children)
            console.print(f"[bold]Added {count} issues to epic #{epic_issue}[/bold]")

    except CLI_ERRORS as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
