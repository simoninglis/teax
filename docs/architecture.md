# teax Architecture

## Module Structure

```
src/teax/
├── cli.py      # Click commands - OutputFormat class handles table/csv/simple output
├── api.py      # GiteaClient - httpx-based API client (context manager pattern)
├── config.py   # Reads tea's ~/.config/tea/config.yml for auth
└── models.py   # Pydantic models for API responses
```

## Data Flow

1. CLI commands parse args and get `login_name` from context
2. `GiteaClient` loads credentials from tea config (or specific login via `--login`)
3. API methods make httpx calls and return Pydantic models
4. `OutputFormat` renders results as Rich tables, simple text, or CSV

## GiteaClient Usage

```python
# Context manager ensures cleanup
with GiteaClient() as client:  # Uses default tea login
    deps = client.list_dependencies("owner", "repo", 25)

# Or with specific login
with GiteaClient(login_name="backup.example.com") as client:
    labels = client.get_issue_labels("owner", "repo", 25)
```

## Key Design Decisions

- **Complement tea, not replace** - Only implements features tea lacks
- **Context manager pattern** - Ensures httpx client cleanup
- **Label caching** - Per-repo cache to avoid redundant API calls
- **Pydantic validation** - Type-safe API responses

## Security Architecture

teax implements defense-in-depth security measures:

### Output Sanitisation

All user-controlled and server-returned strings are sanitised before display:

| Function | Purpose | Usage |
|----------|---------|-------|
| `terminal_safe()` | Strips terminal escape sequences (CSI, OSC, DCS, etc.) | All terminal output |
| `safe_rich()` | Combines `terminal_safe()` + Rich markup escaping | Rich console output |
| `csv_safe()` | Strips escapes + neutralises formula injection (`=+−@`) | CSV output |

### Transport Security

- **`trust_env=False`**: httpx ignores proxy env vars to prevent token leakage
- **`TEAX_CA_BUNDLE`**: Custom CA certificate support for self-hosted instances
- **Path encoding**: `_seg()` URL-encodes path segments to prevent traversal attacks

### Error Handling

`CLI_ERRORS` tuple catches all expected exceptions for graceful error display:
- `httpx.HTTPStatusError` - API errors
- `httpx.RequestError` - Network errors
- `ValueError` - Validation errors (e.g., label not found)
- `FileNotFoundError` - Missing tea config
- `ValidationError` - Pydantic model validation failures
- `KeyError` - Unexpected API response format

### DoS Prevention

- `MAX_BULK_ISSUES = 10000` caps issue range expansion
- Range size validated before memory allocation

## Related

- [ADR-0006](adr/ADR-0006-teax-design.md) - Design decision record
- [API Reference](api.md) - Full API documentation
