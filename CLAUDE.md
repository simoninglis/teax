# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Purpose

teax is a Gitea CLI companion that fills feature gaps in `tea` CLI (v0.9.2). It provides issue editing and dependency management that tea doesn't support.

**Key principle**: Complement tea, don't replace it. Features tea already does are out of scope.

## Quick Start

```bash
# Quality checks (preferred workflow)
just check              # All: lint, typecheck, test
just test               # Run pytest with coverage
just test -k "name"     # Run specific test

# Development
just run --help
just run deps list 25 --repo owner/repo
```

## Scope

**In Scope:**
- `teax deps list|add|rm` - Dependency management
- `teax issue view|edit|labels|bulk` - Issue operations (view works around tea v0.9.2 bugs)
- `teax epic create|status|add` - Epic management

**Out of Scope:** Anything tea does (issue create, list, PR ops, label CRUD)

## Architecture

See [docs/architecture.md](docs/architecture.md) for module structure and data flow.

```
src/teax/
├── cli.py      # Click commands, OutputFormat
├── api.py      # GiteaClient (context manager)
├── config.py   # Reads tea's config
└── models.py   # Pydantic models
```

## Development

- Adding commands: See `.claude/rules/development.md`
- Testing patterns: See `.claude/rules/testing.md`
- Full API docs: See `docs/api.md`

### Code Review with Codex

Use `codex exec` for iterative security hardening:

```bash
codex exec "Conduct a comprehensive code review of teax...
- Security: Terminal/CSV injection, path traversal, token leakage
- Error handling: Exception messages sanitized
Please provide grade (A, A-, B+, etc.) and critical issues."
```

Iterate fixes until achieving target grade (aim for A).

### Security Checklist

When adding output or error messages, verify:
- [ ] User/server strings pass through `safe_rich()` for Rich output
- [ ] User/server strings pass through `terminal_safe()` for plain output
- [ ] CSV string fields pass through `csv_safe()`
- [ ] Click BadParameter messages sanitise user input via `terminal_safe()`
- [ ] Config error messages don't expose token values
- [ ] API paths use `_seg()` for owner/repo to prevent traversal

### Pagination Pattern

All API pagination loops MUST:
1. Accept `max_pages: int = 100` parameter to prevent DoS
2. Use `while page <= max_pages:` (not `while True:`)
3. Emit `warnings.warn()` when ceiling is reached with item count
4. Break early when `len(items) < limit` (last page detection)

Example:
```python
truncated = False
while page <= max_pages:
    # ... fetch and process ...
    if len(items) < limit:
        break
    page += 1
else:
    truncated = True
if truncated:
    warnings.warn(f"List truncated at {max_pages} pages ({len(results)} items)...")
```

### Publishing to Gitea PyPI

Poetry requires explicit configuration for Gitea package registry:

```bash
# Configure repository URL (use org name, not username)
poetry config repositories.gitea https://prod-vm-gitea.../api/packages/homelab-teams/pypi

# Configure credentials (__token__ as username, API token as password)
poetry config http-basic.gitea __token__ <token>

# If SSL cert issues, temporarily disable (not recommended for production)
poetry config certificates.gitea.cert false

# Build and publish
poetry build && poetry publish --repository gitea
```

Common errors:
- `reqPackageAccess`: Token lacks `write:package` scope
- `Error connecting to repository`: Usually SSL cert verification issue

## tea CLI Reference

When creating Gitea issues programmatically:
```bash
# tea uses -d for description, not --body
tea issue create --repo owner/repo --title "Title" --description "Body" --labels "label1,label2"
```

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/usage.md](docs/usage.md) | CLI usage guide |
| [docs/api.md](docs/api.md) | Python API reference |
| [docs/architecture.md](docs/architecture.md) | System design |
| [docs/adr/](docs/adr/) | Architecture decisions |
| [plan.md](plan.md) | Current implementation plan |
