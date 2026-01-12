---
paths: tests/**/*.py
---

# Testing Rules

## HTTP Mocking with respx

Use `respx` to mock httpx requests. For paginated API methods, use `side_effect` with multiple responses:

```python
@respx.mock
def test_paginated_method(client: GiteaClient):
    route = respx.get("https://example.com/api/v1/repos/owner/repo/labels")
    route.side_effect = [
        httpx.Response(200, json=[{"id": 1, "name": "bug"}]),  # Page 1
        httpx.Response(200, json=[]),  # Empty page signals end
    ]

    labels = client.list_repo_labels("owner", "repo")
    assert route.call_count == 2  # Verify pagination occurred
```

## CLI Testing

Use Click's `CliRunner` for CLI tests - provides isolation and captures output:

```python
from click.testing import CliRunner
from teax.cli import main

def test_command(runner: CliRunner):
    result = runner.invoke(main, ["deps", "list", "25", "--repo", "owner/repo"])
    assert result.exit_code == 0
```

## Test File Organisation

- `tests/test_config.py` - Config parsing with `tmp_path` fixtures
- `tests/test_cli.py` - CLI tests using CliRunner
- `tests/test_api.py` - API client tests with respx mocking
