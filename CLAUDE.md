# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

teax is a Gitea CLI companion that fills feature gaps in the official `tea` CLI (v0.9.2). It provides issue editing and dependency management that tea doesn't support.

**Key principle**: Complement tea, don't replace it. Features tea already does are out of scope.

## Development Commands

```bash
# Via justfile (preferred)
just check          # All quality checks: lint, typecheck, test
just test           # Run pytest with coverage
just test -k "test_name"  # Run specific test
just lint           # Run ruff
just typecheck      # Run mypy
just format         # Auto-format code

# Run CLI during development
just run --help
just run deps list 25 --repo owner/repo
```

## Architecture

```
src/teax/
├── cli.py      # Click commands - OutputFormat class handles table/csv/simple output
├── api.py      # GiteaClient - httpx-based API client (context manager pattern)
├── config.py   # Reads tea's ~/.config/tea/config.yml for auth
└── models.py   # Pydantic models for API responses
```

### Data Flow

1. CLI commands parse args and get `login_name` from context
2. `GiteaClient` loads credentials from tea config (or specific login via `--login`)
3. API methods make httpx calls and return Pydantic models
4. `OutputFormat` renders results as Rich tables, simple text, or CSV

### GiteaClient Usage

```python
# Context manager ensures cleanup
with GiteaClient() as client:  # Uses default tea login
    deps = client.list_dependencies("owner", "repo", 25)

# Or with specific login
with GiteaClient(login_name="backup.example.com") as client:
    labels = client.get_issue_labels("owner", "repo", 25)
```

## Testing

- `tests/test_config.py` - Config parsing with `tmp_path` fixtures
- `tests/test_cli.py` - CLI tests using Click's `CliRunner` for isolation

```bash
# With coverage report
poetry run pytest --cov=teax --cov-report=html
```

## Scope

### In Scope (MVP)
- `teax deps list|add|rm` - Dependency management
- `teax issue edit` - Labels, assignees, milestone, title
- `teax issue labels` - List issue labels

### Out of Scope
- Anything tea already does (issue create, list, PR ops, label CRUD)
- Project boards, wikis, webhooks
- Cross-repo operations

## Adding a New Command

1. Add API method to `api.py` (follow existing patterns - returns Pydantic models)
2. Add Click command to `cli.py` (use `@click.pass_context`, catch exceptions with Rich error output)
3. Add tests for both layers
4. Update README.md with usage examples
5. Run `just check` before committing

## Error Handling

- API errors: `httpx.HTTPStatusError` (CLI catches and displays with Rich)
- Config errors: `FileNotFoundError` or `ValueError` with helpful messages
- Label resolution: `_resolve_label_ids()` raises `ValueError` if label not found
