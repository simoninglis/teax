# teax

![teax - Gitea CLI companion](https://simoninglis.com/images/teax-og.jpg)

[![CI](https://github.com/simoninglis/teax/actions/workflows/ci.yml/badge.svg)](https://github.com/simoninglis/teax/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Gitea CLI companion for tea feature gaps.

## Overview

`teax` complements the official [tea CLI](https://gitea.com/gitea/tea) by providing commands that tea doesn't support:

- **Issue lifecycle**: Create, view, close, reopen, and comment on issues
- **Issue editing**: Modify labels, assignees, milestones on existing issues
- **Dependency management**: Set and manage issue blockers/blocked-by relationships
- **Bulk operations**: Apply changes to multiple issues at once
- **Sprint management**: View sprint status, ready queue, and plan sprints
- **Epic management**: Create and track parent issues with child issue checklists
- **Runner management**: List, inspect, and manage Gitea Actions runners
- **Workflow runs**: View workflow run status, jobs, logs, and trigger reruns
- **Secrets & Variables**: Manage repository/org/user secrets and variables
- **Package management**: Link/unlink packages to repositories

Uses tea's configuration for authentication - no additional setup required.

## Installation

```bash
# Using pip
pip install git+https://github.com/simoninglis/teax.git

# Using uv
uv pip install git+https://github.com/simoninglis/teax.git

# Using pipx (isolated environment)
pipx install git+https://github.com/simoninglis/teax.git
```

### Development Installation

```bash
# Clone the repository
git clone https://github.com/simoninglis/teax.git
cd teax

# Install with Poetry
poetry install

# Verify installation
poetry run teax --version
```

## Prerequisites

- Python 3.11+
- tea CLI installed and configured (`tea login add`)

## Usage

### Dependencies

```bash
# List dependencies for an issue
teax deps list 25 --repo owner/repo

# Add dependency: issue 25 depends on issue 17
teax deps add 25 --repo owner/repo --on 17

# Add blocker: issue 17 blocks issue 25
teax deps add 17 --repo owner/repo --blocks 25

# Remove dependency
teax deps rm 25 --repo owner/repo --on 17
```

### Issue Lifecycle

```bash
# Create a new issue
teax issue create -r owner/repo --title "Bug: login broken"
teax issue create -r owner/repo -t "Feature request" -b "Description here"
teax issue create -r owner/repo -t "Task" --labels "bug,urgent" --assignees "user1"

# List issues with filtering
teax issue list -r owner/repo --state open
teax issue list -r owner/repo --label ready --no-label "sprint/*"
teax -o json issue list -r owner/repo

# View issue details (body, labels, assignees, milestone)
teax issue view 25 --repo owner/repo
teax issue view 25 --repo owner/repo --comments

# Close issues
teax issue close 42 -r owner/repo
teax issue close 42,43,44 -r owner/repo -y  # Multiple with confirmation skip

# Reopen issues
teax issue reopen 42 -r owner/repo

# Add a comment
teax issue comment 42 -r owner/repo -m "This is my comment"

# Edit a comment (ID shown in view --comments)
teax issue comment-edit 12345 -r owner/repo -m "Updated text"

# Delete a comment
teax issue comment-delete 12345 -r owner/repo
teax issue comment-delete 12345 -r owner/repo -y  # Skip confirmation
```

### Issue Editing

```bash
# Add labels
teax issue edit 25 --repo owner/repo --add-labels "epic/diagnostics,prio/p1"

# Remove labels
teax issue edit 25 --repo owner/repo --rm-labels "needs-triage"

# Replace all labels
teax issue edit 25 --repo owner/repo --set-labels "type/feature,prio/p2"

# Set assignees
teax issue edit 25 --repo owner/repo --assignees "user1,user2"

# Set milestone (by ID or name)
teax issue edit 25 --repo owner/repo --milestone 5
teax issue edit 25 --repo owner/repo --milestone "Sprint 1"

# Clear milestone
teax issue edit 25 --repo owner/repo --milestone ""

# List labels on an issue
teax issue labels 25 --repo owner/repo
```

### Bulk Operations

```bash
# Add labels to multiple issues
teax issue bulk 17-23 --repo owner/repo --add-labels "sprint/week1"

# Set assignees on a range of issues
teax issue bulk "17,18,25-30" --repo owner/repo --assignees "user1"

# Set milestone on multiple issues (by ID or name)
teax issue bulk 17-20 --repo owner/repo --milestone 5

# Skip confirmation prompt
teax issue bulk 17-23 --repo owner/repo --add-labels "done" --yes
```

### Epic Management

```bash
# Create a new epic with child issues
teax epic create auth --repo owner/repo --title "Auth System" -c 17 -c 18

# Add issues to an existing epic
teax epic add 25 17 18 19 --repo owner/repo

# Show epic progress
teax epic status 25 --repo owner/repo
```

### Sprint Management

```bash
# View sprint overview (current sprint, ready queue, backlog)
teax sprint status --repo owner/repo

# List issues ready for sprint (have "ready" label, no sprint label)
teax sprint ready --repo owner/repo

# List issues in a specific sprint
teax sprint issues 28 --repo owner/repo
teax sprint issues 28 --repo owner/repo --state open

# Plan a sprint (assign issues to sprint label)
teax sprint plan 29 --repo owner/repo --issues 17-23,25
teax sprint plan 29 --repo owner/repo --issues 17-23 --confirm  # Execute

# Ensure a label exists (idempotent)
teax label ensure sprint/29 --repo owner/repo
teax label ensure ready --repo owner/repo --color 00ff00
```

### Runner Management

Manage Gitea Actions runners across repos, orgs, or globally (admin).

```bash
# List runners for a repository
teax runners list --repo owner/repo

# List runners for an organisation
teax runners list --org myorg

# List global runners (admin only)
teax runners list --global

# Get runner details
teax runners get 42 --repo owner/repo

# Delete a runner (prompts for confirmation)
teax runners delete 42 --repo owner/repo
teax runners delete 42 --repo owner/repo -y  # Skip confirmation

# Get registration token for adding new runners
teax runners token --repo owner/repo
teax -o simple runners token --repo owner/repo  # For scripting
```

### Workflow Runs

View and manage Gitea Actions workflow runs.

```bash
# Quick status of recent runs
teax runs status --repo owner/repo

# List all runs with filtering
teax runs list --repo owner/repo --status failure --limit 10

# Get run details
teax runs get 42 --repo owner/repo

# List jobs for a run
teax runs jobs 42 --repo owner/repo
teax runs jobs 42 --repo owner/repo --errors-only

# View job logs with filtering
teax runs logs 123 --repo owner/repo --tail 100
teax runs logs 123 --repo owner/repo --grep "Error" --context 5

# Rerun a failed workflow
teax runs rerun 42 --repo owner/repo

# Delete old runs
teax runs delete 42 --repo owner/repo -y
```

### Secrets & Variables

Manage secrets and variables at repository, organisation, or user level.

```bash
# List secrets
teax secrets list --repo owner/repo
teax secrets list --org myorg
teax secrets list --user

# Set a secret
teax secrets set MY_SECRET "secret-value" --repo owner/repo

# Delete a secret
teax secrets delete MY_SECRET --repo owner/repo

# Variables work the same way
teax vars list --repo owner/repo
teax vars set MY_VAR "value" --repo owner/repo
teax vars delete MY_VAR --repo owner/repo
```

### Package Management

Link packages to repositories for better organisation.

```bash
# Link a package to a repository
teax pkg link mypackage --owner myorg --type pypi --repo myproject

# Unlink a package
teax pkg unlink mypackage --owner myorg --type container

# Get latest version
teax pkg latest mypackage --owner myorg --type pypi
```

### Token Management

Create API access tokens programmatically (requires password).

```bash
# Create a token (prompts for password)
teax token create my-ci-token --scopes write:repository,write:package

# Create token with password from environment variable
teax token create my-token --password-env MY_PASSWORD

# Get token value only (for scripting)
teax -o simple token create my-token --scopes write:repository -p MY_PASSWORD
```

Note: Token creation requires Basic authentication (username + password), not token auth. This is a Gitea API requirement.

### Global Options

```bash
# Use specific tea login
teax --login backup.example.com deps list 25 --repo owner/repo

# Change output format
teax --output simple deps list 25 --repo owner/repo
teax --output csv deps list 25 --repo owner/repo
```

## Configuration

teax reads authentication from tea's config file at `~/.config/tea/config.yml`:

```yaml
logins:
  - name: gitea.example.com
    url: https://gitea.example.com
    token: <your-api-token>
    default: true
    user: username
```

If you haven't configured tea yet:

```bash
tea login add
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TEAX_CA_BUNDLE` | Path to custom CA certificate bundle (e.g., `/path/to/ca.pem`). Use for self-hosted Gitea with custom certificates. |
| `TEAX_INSECURE` | Set to `1` to skip SSL certificate verification entirely (not recommended). |

Examples:

```bash
# Use a custom CA certificate bundle
TEAX_CA_BUNDLE=/etc/ssl/certs/my-ca.pem teax deps list 25 --repo owner/repo

# Skip SSL verification (not recommended)
TEAX_INSECURE=1 teax deps list 25 --repo owner/repo
```

## Development

```bash
# Install dev dependencies
poetry install

# Run all quality checks (lint, typecheck, test)
just check

# Run individual checks
just test           # Run pytest
just lint           # Run ruff linting
just typecheck      # Run mypy

# Format code
just format

# Run CLI during development
just run --help
just run deps list 25 --repo owner/repo
```

## Feature Gap Analysis (tea v0.9.2)

| Feature | tea Support | teax Scope |
|---------|-------------|------------|
| Issue create | Supported | **Implemented** (semantic clarity) |
| Issue list | Supported | **Implemented** (with filtering) |
| Issue view | Buggy¹ | **Implemented** |
| Issue close/reopen | Supported | **Implemented** (semantic clarity) |
| Issue comments | Missing | **Implemented** |
| Issue edit | Missing | **Implemented** |
| Issue dependencies | Missing | **Implemented** |
| Issue bulk ops | Missing | **Implemented** |
| Sprint management | Missing | **Implemented** |
| Epic management | Missing | **Implemented** |
| Runner management | Missing | **Implemented** |
| Workflow runs | Missing | **Implemented** |
| Secrets/Variables | Missing | **Implemented** |
| Package linking | Missing | **Implemented** |
| Token creation | Missing | **Implemented** |
| Label CRUD | Full | Out of scope |
| Label ensure | Missing | **Implemented** |
| Milestone CRUD | Full | Out of scope |
| Milestone assign | Missing | Via issue edit |
| PR operations | Full | Out of scope |

¹ tea's issue view breaks with `--fields` or `--comments` flags, returning a list instead of issue details.

**Note:** While tea supports some issue operations, teax provides all issue commands for semantic clarity: use `tea` for authentication, repos, and PRs; use `teax` for all issue operations.

## See Also

- [Blog: Why I built teax](https://simoninglis.com/posts/teax)

## License

MIT - see [LICENSE](LICENSE) for details.
