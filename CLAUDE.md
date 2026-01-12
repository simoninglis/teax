# teax

Gitea CLI companion tool that fills feature gaps in the official `tea` CLI.

## Purpose

Provide issue editing and dependency management that tea v0.9.2 doesn't support:
- Edit existing issues (labels, assignees, milestones)
- Manage issue dependencies (blockers/blocked-by)
- Bulk operations (Phase 2)

**Key principle**: Complement tea, don't replace it. Use tea for everything it does well.

## Architecture

```
src/teax/
├── __init__.py     # Version
├── cli.py          # Click command definitions
├── config.py       # Read tea's ~/.config/tea/config.yml
├── api.py          # Gitea API client (httpx)
└── models.py       # Pydantic models for API responses
```

## Tech Stack

- **CLI Framework**: click
- **HTTP Client**: httpx
- **Output Formatting**: Rich (tables)
- **Validation**: Pydantic
- **Config**: PyYAML (read tea config)

## Development Workflow

```bash
# Run tests
poetry run pytest

# Quality checks
poetry run ruff check .
poetry run mypy src/

# Run CLI during development
poetry run teax --help
```

## Key Design Decisions

1. **Read tea config** - No separate auth, reuse tea's tokens from `~/.config/tea/config.yml`
2. **Match tea conventions** - Same flags where applicable (`--repo`, `--login`, `--output`)
3. **Safe by default** - Would add confirmation prompts for destructive ops (Phase 2)

## API Patterns

### Common Operations

```python
from teax.api import GiteaClient

with GiteaClient() as client:
    # Uses default tea login
    deps = client.list_dependencies("owner", "repo", 25)
    client.add_dependency("owner", "repo", 25, "owner", "repo", 17)
```

### Error Handling

- API errors raise `httpx.HTTPStatusError`
- Config errors raise `FileNotFoundError` or `ValueError`
- CLI catches and displays user-friendly messages

## Testing

- `tests/test_config.py` - Config parsing with fixtures
- `tests/test_cli.py` - CLI commands using Click's CliRunner

## Scope Boundaries

### In Scope (MVP)
- `teax deps list|add|rm`
- `teax issue edit --add-labels|--rm-labels|--set-labels|--assignees|--milestone`
- `teax issue labels`

### Phase 2
- `teax issue bulk`
- `teax epic create|status|add`

### Out of Scope
- Anything tea already does (issue create, list, PR ops, label CRUD, etc.)

## Related

- [ADR-0006](../dev-manual/docs/adr/ADR-0006-teax-gitea-cli-companion.md) - Design decision
- [ADR-0005](../dev-manual/docs/adr/ADR-0005-gitea-epic-tracking.md) - Epic tracking workflow this enables
