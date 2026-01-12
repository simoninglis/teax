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

## Code Style

- Use type hints throughout
- Follow existing patterns in each module
- Use Pydantic models for API responses
- Use Rich for formatted CLI output
