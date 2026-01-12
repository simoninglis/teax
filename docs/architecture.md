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

## Related

- [ADR-0006](adr/ADR-0006-teax-design.md) - Design decision record
- [API Reference](api.md) - Full API documentation
