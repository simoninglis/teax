# teax

Gitea CLI companion for tea feature gaps.

## Overview

`teax` complements the official [tea CLI](https://gitea.com/gitea/tea) by providing commands that tea doesn't support:

- **Issue editing**: Modify labels, assignees, milestones on existing issues
- **Dependency management**: Set and manage issue blockers/blocked-by relationships
- **Bulk operations**: Apply changes to multiple issues at once
- **Epic management**: Create and track parent issues with child issue checklists

Uses tea's configuration for authentication - no additional setup required.

## Installation

### From Gitea PyPI Registry

```bash
# Using uv (recommended)
UV_INDEX_URL=https://prod-vm-gitea.internal.kellgari.com.au/api/packages/homelab-teams/pypi/simple \
  uv pip install teax

# Using pip
pip install teax \
  --index-url https://prod-vm-gitea.internal.kellgari.com.au/api/packages/homelab-teams/pypi/simple

# Using pipx (isolated environment)
pipx install teax \
  --pip-args="--index-url https://prod-vm-gitea.internal.kellgari.com.au/api/packages/homelab-teams/pypi/simple"
```

For self-hosted Gitea with custom CA certificates:

```bash
# uv with custom CA
UV_INDEX_URL=https://prod-vm-gitea.internal.kellgari.com.au/api/packages/homelab-teams/pypi/simple \
  SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
  uv pip install teax

# pip/pipx with custom CA
PIP_CERT=/etc/ssl/certs/ca-certificates.crt pipx install teax \
  --pip-args="--index-url https://prod-vm-gitea.internal.kellgari.com.au/api/packages/homelab-teams/pypi/simple"
```

### Development Installation

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

### Issue Viewing

```bash
# View issue details (body, labels, assignees, milestone)
teax issue view 25 --repo homelab/myproject

# View issue with comments
teax issue view 25 --repo homelab/myproject --comments
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

# Set milestone (by ID or name)
teax issue edit 25 --repo homelab/myproject --milestone 5
teax issue edit 25 --repo homelab/myproject --milestone "Sprint 1"

# Clear milestone
teax issue edit 25 --repo homelab/myproject --milestone ""

# List labels on an issue
teax issue labels 25 --repo homelab/myproject
```

### Bulk Operations

```bash
# Add labels to multiple issues
teax issue bulk 17-23 --repo homelab/myproject --add-labels "sprint/week1"

# Set assignees on a range of issues
teax issue bulk "17,18,25-30" --repo homelab/myproject --assignees "user1"

# Set milestone on multiple issues (by ID or name)
teax issue bulk 17-20 --repo homelab/myproject --milestone 5
teax issue bulk 17-20 --repo homelab/myproject --milestone "Sprint 1"

# Skip confirmation prompt
teax issue bulk 17-23 --repo homelab/myproject --add-labels "done" --yes
```

### Epic Management

```bash
# Create a new epic with child issues
teax epic create auth --repo homelab/myproject --title "Auth System" -c 17 -c 18

# Add issues to an existing epic
teax epic add 25 17 18 19 --repo homelab/myproject

# Show epic progress
teax epic status 25 --repo homelab/myproject
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
just install

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

## Publishing (Maintainers)

```bash
# One-time setup: configure Poetry repository for Gitea PyPI
just setup-publish
# Then configure credentials (see output for options)

# Show current version
just version

# Bump version (updates pyproject.toml and src/teax/__init__.py)
just bump patch     # 0.1.0 → 0.1.1
just bump minor     # 0.1.0 → 0.2.0
just bump major     # 0.1.0 → 1.0.0

# Build package
just build

# Publish to Gitea PyPI
just publish

# Full release workflow (check → bump → commit → tag → publish)
just release patch
# Then: git push origin main --tags
```

## Feature Gap Analysis (tea v0.9.2)

| Feature | tea Support | teax Scope |
|---------|-------------|------------|
| Issue create | Full | Out of scope |
| Issue list | Full | Out of scope |
| Issue view | Buggy¹ | **Implemented** |
| Issue edit | Missing | **Implemented** |
| Issue dependencies | Missing | **Implemented** |
| Issue bulk ops | Missing | **Implemented** |
| Epic management | Missing | **Implemented** |
| Label CRUD | Full | Out of scope |
| Label assign | Missing | Via issue edit |
| Milestone CRUD | Full | Out of scope |
| Milestone assign | Missing | Via issue edit |
| PR operations | Full | Out of scope |

¹ tea's issue view breaks with `--fields` or `--comments` flags, returning a list instead of issue details.

## Related Documentation

- [ADR-0006: teax Design Decision](https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/dev-manual/src/branch/main/docs/adr/ADR-0006-teax-gitea-cli-companion.md)
- [ADR-0005: Epic-Style Tracking](https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/dev-manual/src/branch/main/docs/adr/ADR-0005-gitea-epic-tracking.md)
- [Gitea API Documentation](https://docs.gitea.com/api/)

## License

MIT
