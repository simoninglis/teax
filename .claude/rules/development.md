# Development Workflow Rules

## Adding a New Command

1. Add API method to `api.py` (follow existing patterns - returns Pydantic models)
2. Add Click command to `cli.py` (use `@click.pass_context`, catch exceptions with Rich error output)
3. Add tests for both layers
4. Update README.md with usage examples
5. Run `just check` before committing

## Error Handling Pattern

CLI uses `CLI_ERRORS` tuple constant (defined at top of cli.py) to catch:
- `httpx.HTTPStatusError` - API errors
- `httpx.RequestError` - Network errors
- `ValueError` - Validation errors (e.g., label not found)
- `FileNotFoundError` - Missing tea config

Config errors wrapped with helpful messages in `config.py`.
Label resolution: `_resolve_label_ids()` raises `ValueError` if label not found.

### Security: Preventing Secret Leakage

Config error messages must NOT expose secrets. Use `from None` to suppress exception chains:

```python
# WRONG - may expose token in YAML/validation error
except yaml.YAMLError as e:
    raise ValueError(f"Invalid YAML: {e}") from e

# CORRECT - sanitized error, no secret leakage
except yaml.YAMLError:
    raise ValueError(f"Invalid YAML in config at {path}") from None
```

## Rich Output Safety

**All user-controlled strings displayed via Rich must be escaped** to prevent markup injection:

```python
from rich.markup import escape

# WRONG - user data can inject Rich markup
console.print(f"Title: {issue.title}")
err_console.print(f"[red]Error:[/red] {e}")

# CORRECT - escaped user data
console.print(f"Title: {escape(issue.title)}")
err_console.print(f"[red]Error:[/red] {escape(str(e))}")
```

Apply escaping to:
- All `table.add_row()` cells with user data
- All f-strings in `console.print()` containing variables
- All error messages (exceptions can contain user data)
- API response fields (titles, labels, descriptions, colors)

## Caching Pattern

Caches should implement **refresh-on-miss** to handle stale data:

```python
# Check cache, retry once with fresh fetch if missing
if name not in cache:
    cache = fetch_all()  # Populate cache
if name not in cache:
    cache = fetch_all()  # Retry with fresh fetch
    if name not in cache:
        raise ValueError(f"'{name}' not found")
```

This handles cases where items are created after cache was populated.

## Code Style

- Use type hints throughout
- Follow existing patterns in each module
- Use Pydantic models for API responses
- Use Rich for formatted CLI output
