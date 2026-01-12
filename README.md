# teax

Gitea CLI companion for tea feature gaps.

## Overview

`teax` complements the official [tea CLI](https://gitea.com/gitea/tea) by providing commands that tea doesn't support:

- **Issue editing**: Modify labels, assignees, milestones on existing issues
- **Dependency management**: Set and manage issue blockers/blocked-by relationships
- **Bulk operations**: Apply changes to multiple issues (coming soon)

Uses tea's configuration for authentication - no additional setup required.

## Installation

```bash
# Clone the repository
git clone https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/teax.git
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
teax deps list 25 --repo homelab/myproject

# Add dependency: issue 25 depends on issue 17
teax deps add 25 --repo homelab/myproject --on 17

# Add blocker: issue 17 blocks issue 25
teax deps add 17 --repo homelab/myproject --blocks 25

# Remove dependency
teax deps rm 25 --repo homelab/myproject --on 17
```

### Issue Editing

```bash
# Add labels
teax issue edit 25 --repo homelab/myproject --add-labels "epic/diagnostics,prio/p1"

# Remove labels
teax issue edit 25 --repo homelab/myproject --rm-labels "needs-triage"

# Replace all labels
teax issue edit 25 --repo homelab/myproject --set-labels "type/feature,prio/p2"

# Set assignees
teax issue edit 25 --repo homelab/myproject --assignees "user1,user2"

# Set milestone (by ID)
teax issue edit 25 --repo homelab/myproject --milestone 5

# List labels on an issue
teax issue labels 25 --repo homelab/myproject
```

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

## Development

```bash
# Install dev dependencies
poetry install

# Run tests
poetry run pytest

# Run linting
poetry run ruff check .

# Run type checking
poetry run mypy src/

# Format code
poetry run ruff format .
```

## Feature Gap Analysis (tea v0.9.2)

| Feature | tea Support | teax Scope |
|---------|-------------|------------|
| Issue create | Full | Out of scope |
| Issue list/view | Full | Out of scope |
| Issue edit | Missing | **Primary** |
| Issue dependencies | Missing | **Primary** |
| Issue bulk ops | Missing | Phase 2 |
| Label CRUD | Full | Out of scope |
| Label assign | Missing | Via issue edit |
| Milestone CRUD | Full | Out of scope |
| Milestone assign | Missing | Via issue edit |
| PR operations | Full | Out of scope |

## Related Documentation

- [ADR-0006: teax Design Decision](https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/dev-manual/src/branch/main/docs/adr/ADR-0006-teax-gitea-cli-companion.md)
- [ADR-0005: Epic-Style Tracking](https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/dev-manual/src/branch/main/docs/adr/ADR-0005-gitea-epic-tracking.md)
- [Gitea API Documentation](https://docs.gitea.com/api/)

## License

MIT
