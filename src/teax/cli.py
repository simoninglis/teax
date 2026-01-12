"""teax CLI - Gitea companion for tea feature gaps."""

import sys
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from teax import __version__
from teax.api import GiteaClient

console = Console()
err_console = Console(stderr=True)


def parse_repo(repo: str) -> tuple[str, str]:
    """Parse owner/repo string into components."""
    if "/" not in repo:
        raise click.BadParameter(
            f"Repository must be in 'owner/repo' format, got: {repo}"
        )
    parts = repo.split("/", 1)
    return parts[0], parts[1]


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
            click.echo("number,title,state,repository")
            for d in deps:
                click.echo(f"{d.number},{d.title},{d.state},{d.repository.full_name}")
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
            click.echo("name,color,description")
            for label in labels:
                click.echo(f"{label.name},{label.color},{label.description}")
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
@click.option(
    "--login", "-l", "login_name", help="Use specific tea login"
)
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
    except Exception as e:
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
                client.add_dependency(
                    owner, repo_name, blocks, owner, repo_name, issue
                )
                console.print(
                    f"[green]Added:[/green] #{issue} now blocks #{blocks}"
                )
    except Exception as e:
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

    owner, repo_name = parse_repo(repo)

    try:
        with GiteaClient(login_name=ctx.obj["login_name"]) as client:
            if depends_on is not None:
                client.remove_dependency(
                    owner, repo_name, issue, owner, repo_name, depends_on
                )
                msg = f"#{issue} no longer depends on #{depends_on}"
                console.print(f"[yellow]Removed:[/yellow] {msg}")
            if blocks is not None:
                client.remove_dependency(
                    owner, repo_name, blocks, owner, repo_name, issue
                )
                console.print(
                    f"[yellow]Removed:[/yellow] #{issue} no longer blocks #{blocks}"
                )
    except Exception as e:
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
@click.option("--milestone", help="Set milestone (name or ID, empty to clear)")
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
        teax issue edit 25 --repo homelab/myproject --milestone "v1.0"
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

    except Exception as e:
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
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
