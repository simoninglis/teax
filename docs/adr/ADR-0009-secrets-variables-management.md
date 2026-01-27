# ADR-0009: Secrets and Variables Management

## Status
Accepted

## Date
2026-01-27

## Context

Gitea Actions supports secrets and variables at user, organisation, and repository scopes. These are used in workflows via `${{ secrets.NAME }}` and `${{ vars.NAME }}`.

The `tea` CLI (v0.9.2) has no support for managing secrets or variables. Users must use the web UI or direct API calls.

Investigation confirmed full API support in Gitea 1.25.1:
- Secrets: write-only (values never returned for security)
- Variables: full CRUD with readable values

## Decision

Add `teax secrets` and `teax vars` command groups for managing Actions secrets and variables.

### API Endpoints

**Secrets** (write-only by design):
- `GET .../actions/secrets` - List names only
- `PUT .../actions/secrets/{name}` - Create/update with `{"data": "value"}`
- `DELETE .../actions/secrets/{name}` - Delete

**Variables** (full CRUD):
- `GET .../actions/variables` - List with values
- `GET .../actions/variables/{name}` - Get single
- `POST .../actions/variables/{name}` - Create with `{"value": "value"}`
- `PUT .../actions/variables/{name}` - Update
- `DELETE .../actions/variables/{name}` - Delete

All support repo (`repos/{owner}/{repo}/...`), org (`orgs/{org}/...`), and user (`user/...`) scopes.

### Commands

```bash
# Secrets
teax secrets list --repo owner/repo
teax secrets set SECRET_NAME --repo owner/repo      # prompts or stdin
teax secrets delete SECRET_NAME --repo owner/repo

# Variables
teax vars list --repo owner/repo
teax vars get VAR_NAME --repo owner/repo
teax vars set VAR_NAME --value "value" --repo owner/repo
teax vars delete VAR_NAME --repo owner/repo
```

### Security Considerations

1. **Secret values**: Never logged, displayed, or returned by API
2. **Input methods for secrets**:
   - Interactive prompt (default, hidden input)
   - Stdin pipe (`echo "value" | teax secrets set NAME -r o/r`)
   - Environment variable (`--from-env VAR_NAME`)
3. **No `--value` flag for secrets**: Prevents accidental shell history exposure

## Consequences

### Positive
- Enables CI/CD automation for secret/variable management
- Complements existing runner management commands
- Enables "desired state" reconciliation workflows

### Negative
- Secret values cannot be verified after creation (API limitation)
- Users must trust their source-of-truth for secret values

## Implementation Notes

- Reuse scope validation pattern from runners commands
- Add `Secret` and `Variable` Pydantic models
- Follow existing OutputFormat patterns for list/table/json/csv output
