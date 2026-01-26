# ADR-0008: Package Management

**Status**: Implemented
**Date**: 2026-01-26
**Context**: Gitea package registry management not supported by tea CLI; teax could fill this gap

## Context

### Problem Statement

Gitea's package registry (v1.17+) provides hosting for multiple package types:
- PyPI (Python)
- Container (Docker images)
- Generic (arbitrary files)
- npm, Cargo, Maven, etc.

Currently, managing packages requires:
- Web UI navigation for listing and deletion
- Direct API calls for automation
- No CLI support in tea (v0.9.2)

### Use Cases

1. **Package inventory**: List packages owned by a user or organisation
2. **Version inspection**: View all versions of a package
3. **Cleanup**: Delete old versions to save storage
4. **Automation**: Prune old versions in CI/CD pipelines

### Key Constraint: PyPI Deletion

Gitea does not support deleting PyPI packages via API (Issue #22303). This is a deliberate limitation - PyPI packages are immutable by design. teax must handle this gracefully with clear error messages.

## Decision

Add `teax pkg` command group for package management operations.

### Command Structure

```bash
# List packages (owner-scoped)
teax pkg list --owner homelab-teams
teax pkg list --owner homelab-teams --type pypi

# Get package versions
teax pkg info mypackage --owner homelab-teams --type generic

# Delete specific version (NOT supported for PyPI)
teax pkg delete mypackage --owner homelab-teams --type generic --version 1.0.0

# Prune old versions (dry-run by default)
teax pkg prune myimage --owner homelab-teams --type container --keep 3
teax pkg prune myimage --owner homelab-teams --type container --keep 3 --execute
```

### Design Principles

1. **Owner-scoped operations**: Packages belong to owners (users/orgs), not repositories
2. **Explicit type required**: Package type must be specified for info/delete/prune operations
3. **PyPI deletion blocked early**: Clear error message before any API call attempt
4. **Dry-run by default**: Prune shows preview unless `--execute` is passed
5. **Confirmation for delete**: Requires `--yes` flag or interactive confirmation

### API Endpoints Used

Package API uses `/api/packages/` (NOT `/api/v1/packages/`):

| Command | Endpoint |
|---------|----------|
| `pkg list` | `GET /api/packages/{owner}` |
| `pkg info` | `GET /api/packages/{owner}/{type}/{name}` |
| `pkg delete` | `DELETE /api/packages/{owner}/{type}/{name}/{version}` |

### Models

```python
class Package(BaseModel):
    id: int
    owner: User
    name: str
    type: str  # pypi, container, generic, npm, etc.
    version: str
    created_at: str
    html_url: str = ""

class PackageVersion(BaseModel):
    id: int
    version: str
    created_at: str
    html_url: str = ""
```

## Consequences

### Positive

- Enables CLI-based package management for Gitea registries
- Automates version cleanup (disk space savings)
- Consistent with teax patterns and output formats
- Clear handling of PyPI limitation

### Negative

- Adds maintenance burden for package API changes
- Owner scope may confuse users expecting repo scope
- PyPI limitation may frustrate some users

### Mitigations

- Clear documentation of scope and limitations
- Helpful error messages pointing to web UI for PyPI deletion
- Dry-run mode prevents accidental data loss

## Alternatives Considered

### 1. Wait for tea to add package support
- **Rejected**: No indication this is planned

### 2. Only support container packages
- **Rejected**: Generic and other types equally useful

### 3. Attempt PyPI deletion anyway
- **Rejected**: Would fail with confusing error; better to fail early with guidance

## Implementation Notes

### Security Considerations

1. **Path encoding**: All owner, type, name, version values pass through `_seg()` for safe URL construction
2. **Output sanitization**: Use `safe_rich()`, `terminal_safe()`, `csv_safe()` for all output
3. **Pagination limits**: `max_pages=100` ceiling prevents DoS

### Example Workflow

```bash
# List all packages for an org
teax pkg list --owner homelab-teams

# Check versions of a container image
teax pkg info myapp --owner homelab-teams --type container

# Preview what would be pruned (keep latest 3)
teax pkg prune myapp --owner homelab-teams --type container --keep 3

# Execute pruning
teax pkg prune myapp --owner homelab-teams --type container --keep 3 --execute
```

## References

- [Gitea Package Registry Documentation](https://docs.gitea.com/usage/packages/overview)
- [Gitea Issue #22303](https://github.com/go-gitea/gitea/issues/22303) - PyPI deletion limitation
- [Gitea API - Packages](https://docs.gitea.com/api/1.20/#tag/package)
