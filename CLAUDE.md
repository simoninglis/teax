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
# Quick commands via justfile
just test          # Run tests
just lint          # Run ruff
just typecheck     # Run mypy
just check         # All quality checks

# Or directly with poetry
poetry run pytest
poetry run ruff check .
poetry run mypy src/

# Run CLI during development
poetry run teax --help
```

## Key Design Decisions

1. **Read tea config** - No separate auth, reuse tea's tokens from `~/.config/tea/config.yml`
2. **Match tea conventions** - Same flags where applicable (`--repo`, `--login`, `--output`)
3. **Safe by default** - Confirmation prompts for destructive ops (Phase 2)

See [ADR-0006](docs/adr/ADR-0006-teax-design.md) for full design rationale.

## Code Standards

Follow dev-manual patterns:
- **Python**: Type hints required, dataclasses for models, f-strings
- **Testing**: pytest with fixtures, 80%+ coverage target
- **Linting**: ruff + mypy strict mode
- **Git**: Conventional commits (`feat:`, `fix:`, `docs:`)

References:
- [Python Best Practices](~/work/dev-manual/docs/python/best-practices.md)
- [Code Quality Tools](~/work/dev-manual/docs/python/code-quality.md)
- [Testing Patterns](~/work/dev-manual/docs/development/testing-patterns.md)

## API Patterns

### GiteaClient Usage

```python
from teax.api import GiteaClient

# Context manager ensures cleanup
with GiteaClient() as client:
    # Uses default tea login
    deps = client.list_dependencies("owner", "repo", 25)
    client.add_dependency("owner", "repo", 25, "owner", "repo", 17)

# Or with specific login
with GiteaClient(login_name="backup.example.com") as client:
    labels = client.get_issue_labels("owner", "repo", 25)
```

### Error Handling

- API errors: `httpx.HTTPStatusError` (includes status code, response)
- Config errors: `FileNotFoundError` or `ValueError` with helpful messages
- CLI: Catches exceptions and displays user-friendly Rich-formatted errors

## Testing

### Test Organisation
- `tests/test_config.py` - Config parsing with tmp_path fixtures
- `tests/test_cli.py` - CLI commands using Click's CliRunner

### Running Tests
```bash
# All tests with coverage
just test

# Specific test file
poetry run pytest tests/test_cli.py -v

# With coverage report
poetry run pytest --cov=teax --cov-report=html
```

### Adding Tests
Follow existing patterns:
- Use fixtures for setup
- Test happy paths and error cases
- CLI tests use `CliRunner` for isolation

## Scope Boundaries

### In Scope (MVP) - Current
- `teax deps list|add|rm` - Dependency management
- `teax issue edit` - Labels, assignees, milestone, title
- `teax issue labels` - List issue labels

### Phase 2 - Planned
- `teax issue bulk` - Bulk operations on multiple issues
- `teax epic create|status|add` - Epic management helpers

### Out of Scope
- Anything tea already does (issue create, list, PR ops, label CRUD, etc.)
- Project boards, wikis, webhooks
- Cross-repo operations (keep simple)

## Common Tasks

### Adding a New Command

1. Add API method to `api.py` if needed
2. Add Click command to `cli.py`
3. Add tests for both API and CLI
4. Update README.md with usage
5. Run `just check` before committing

### Updating Dependencies

```bash
poetry add <package>           # Add runtime dependency
poetry add --group dev <pkg>   # Add dev dependency
poetry update                  # Update all
poetry lock                    # Regenerate lock file
```

### Debugging API Calls

```python
# Enable httpx debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Or inspect response
response = client._client.get("/api/v1/...")
print(response.status_code, response.json())
```

## Related Documentation

### Project Documentation
- [docs/usage.md](docs/usage.md) - User guide and examples
- [docs/api.md](docs/api.md) - API reference
- [docs/adr/](docs/adr/) - Architecture Decision Records

### Dev-Manual References
- [ADR-0006: teax Design](~/work/dev-manual/docs/adr/ADR-0006-teax-gitea-cli-companion.md) - Original design decision
- [ADR-0005: Epic Tracking](~/work/dev-manual/docs/adr/ADR-0005-gitea-epic-tracking.md) - Workflow this enables
- [Project Brief](~/work/dev-manual/docs/project-briefs/teax-gitea-companion.md) - Implementation plan

### External References
- [Gitea API Docs](https://docs.gitea.com/api/) - Official API reference
- [tea CLI](https://gitea.com/gitea/tea) - Official Gitea CLI
- [Click Documentation](https://click.palletsprojects.com/) - CLI framework

## Notes for Claude

### When Adding Features
- Check if tea already supports it first (out of scope if so)
- Follow existing patterns in `cli.py` for command structure
- Use Rich for output formatting (tables, colors)
- Add `--help` examples in docstrings

### When Fixing Bugs
- Write a failing test first
- Check if issue is in API or CLI layer
- Verify against actual Gitea instance when possible

### Quality Gates
Before committing:
```bash
just check  # Must pass: ruff, mypy, pytest
```

### Git Workflow
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`
- Reference issues: `feat: add bulk labels (#5)`
- Keep commits focused and atomic
