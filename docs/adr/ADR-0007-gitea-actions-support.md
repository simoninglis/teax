# ADR-0007: Gitea Actions Support

**Status**: Implementing
**Date**: 2026-01-26
**Context**: Gitea Actions management not supported by tea CLI; teax could fill this gap

## Context

### Problem Statement

Gitea Actions (CI/CD) management currently requires:
- Web UI navigation (breaks CLI workflow)
- Direct API calls with curl (error-prone)
- CLI-only token generation via `gitea actions generate-runner-token` (requires server access)

The `tea` CLI (v0.9.2) has no support for Actions management. Gitea's API (v1.19+, improved in v1.24.0) provides comprehensive endpoints for:
- Runner management (list, get, delete)
- Registration token generation
- Workflow run/job status
- Secrets and variables management

### Use Cases

1. **Runner provisioning**: Generate registration tokens for automated runner deployment (Kubernetes, Docker Compose)
2. **Runner inventory**: List and audit runners across repos/orgs
3. **CI/CD monitoring**: Check workflow run status from CLI
4. **Secrets management**: Manage repository secrets without web UI

### API Availability

Gitea provides Actions endpoints at three levels:

| Level | Runners | Tokens | Runs/Jobs | Secrets | Variables |
|-------|---------|--------|-----------|---------|-----------|
| Admin/Global | ✅ | ✅ | ✅ | ❌ | ❌ |
| Organisation | ✅ | ✅ | ✅ | ❌ | ❌ |
| Repository | ✅ | ✅ | ✅ | ✅ | ✅ |

## Decision

Extend teax with Gitea Actions support in two phases.

### Phase 1: Runner & Token Management (Core)

```bash
# Runner management
teax runners list -r owner/repo          # List repo runners
teax runners list --org myorg            # List org runners
teax runners list --global               # List global runners (admin)
teax runners get <id> -r owner/repo      # Get runner details
teax runners delete <id> -r owner/repo   # Remove runner

# Registration tokens
teax runners token -r owner/repo         # Get/create registration token
teax runners token --org myorg
teax runners token --global
```

### Phase 2: Workflow Status & Secrets

```bash
# Workflow runs
teax runs list -r owner/repo             # List workflow runs
teax runs list -r owner/repo --status failure
teax jobs list -r owner/repo             # List workflow jobs

# Secrets management
teax secrets list -r owner/repo
teax secrets set SECRET_NAME -r owner/repo   # Prompts for value
teax secrets delete SECRET_NAME -r owner/repo

# Variables management
teax vars list -r owner/repo
teax vars set VAR_NAME value -r owner/repo
teax vars get VAR_NAME -r owner/repo
teax vars delete VAR_NAME -r owner/repo
```

### Command Design Principles

1. **Scope flag pattern**: Use `-r/--repo`, `--org`, `--global` to specify target level
2. **Default to repo level**: Match existing teax behaviour
3. **Consistent with tea**: Use familiar flag names and output formats
4. **Security first**: Never echo secrets, prompt for sensitive values

### API Endpoints Used

#### Phase 1
| Command | Endpoint |
|---------|----------|
| `runners list` | `GET /repos/{owner}/{repo}/actions/runners` |
| `runners get` | `GET /repos/{owner}/{repo}/actions/runners/{id}` |
| `runners delete` | `DELETE /repos/{owner}/{repo}/actions/runners/{id}` |
| `runners token` | `POST /repos/{owner}/{repo}/actions/runners/registration-token` |

#### Phase 2
| Command | Endpoint |
|---------|----------|
| `runs list` | `GET /repos/{owner}/{repo}/actions/runs` |
| `jobs list` | `GET /repos/{owner}/{repo}/actions/jobs` |
| `secrets list` | `GET /repos/{owner}/{repo}/actions/secrets` |
| `secrets set` | `PUT /repos/{owner}/{repo}/actions/secrets/{name}` |
| `secrets delete` | `DELETE /repos/{owner}/{repo}/actions/secrets/{name}` |
| `vars *` | `/repos/{owner}/{repo}/actions/variables/*` |

### Models Required

```python
class Runner(BaseModel):
    id: int
    name: str
    status: str  # online, offline, idle, active
    busy: bool
    labels: list[str]

class WorkflowRun(BaseModel):
    id: int
    name: str
    status: str  # pending, running, success, failure
    conclusion: str | None
    created_at: datetime
    updated_at: datetime

class Secret(BaseModel):
    name: str
    created_at: datetime

class Variable(BaseModel):
    name: str
    value: str
```

## Consequences

### Positive

- Enables CLI-based runner provisioning and automation
- Completes Actions management story for teax users
- Useful for CI/CD debugging without leaving terminal
- Secrets management without web UI exposure

### Negative

- Increased scope and maintenance burden
- Secrets handling requires careful security review
- Admin/global endpoints require elevated permissions

### Mitigations

- Phase implementation to manage scope
- Security review before secrets commands ship
- Clear documentation on permission requirements
- Consider `--dry-run` for destructive operations

## Alternatives Considered

### 1. Wait for tea to add Actions support
- **Rejected**: No indication tea will add this; Gitea team focused elsewhere

### 2. Separate tool (e.g., `gitea-actions-cli`)
- **Rejected**: Fragments tooling; teax already handles API auth

### 3. Only token generation
- **Rejected**: Incomplete solution; full runner management more useful

## Implementation Notes

### Permission Requirements

| Scope | Required Permission |
|-------|---------------------|
| Repository | `write` access to repo |
| Organisation | Org owner or admin |
| Global | Site admin |

### Security Considerations

1. **Token output**: Registration tokens should be displayed only once, with warning
2. **Secrets input**: Use `getpass` or similar to avoid shell history
3. **Audit logging**: Consider logging secret operations (not values)

## References

- [Gitea API Documentation](https://docs.gitea.com/api/)
- [Gitea Actions Overview](https://docs.gitea.com/usage/actions/overview)
- [Act Runner Documentation](https://docs.gitea.com/usage/actions/act-runner)
- [Gitea 1.24.0 Release Notes](https://blog.gitea.com/release-of-1.24.0/) - Runner API improvements
