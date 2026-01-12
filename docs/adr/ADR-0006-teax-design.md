# ADR-0006: teax - Gitea CLI Companion Tool

**Status**: Accepted
**Date**: 2026-01-12
**Context**: tea CLI has feature gaps that require direct API calls; need a consistent companion tool

> **Note**: This is a project-local copy. The canonical version is in dev-manual:
> `~/work/dev-manual/docs/adr/ADR-0006-teax-gitea-cli-companion.md`

## Context

### Problem Statement

The official Gitea CLI (`tea` v0.9.2) lacks several features needed for effective issue management:

1. **No issue editing** - Cannot update labels, assignees, or milestones on existing issues
2. **No dependency management** - Cannot set blockers/blocked-by relationships
3. **No bulk operations** - Cannot apply changes to multiple issues at once

Currently, these operations require:
- Direct API calls with curl (error-prone, requires token management)
- Web UI (breaks CLI workflow, not scriptable)

### Requirements

1. Complement `tea`, not replace it - use `tea` for what it does well
2. Consistent interface that feels like `tea`
3. Support the gaps identified in ADR-0005 (epic tracking workflow)
4. Scriptable for automation
5. Respect existing `tea` configuration (logins, defaults)

## Decision

Build `teax` (tea extended) - a lightweight Python CLI that:

1. Reads tea's configuration (`~/.config/tea/config.yml`) for authentication
2. Provides commands for tea's feature gaps
3. Uses consistent naming conventions matching tea's style
4. Outputs in formats compatible with tea (table, csv, simple)

### Commands Implemented

#### Dependency Management
```bash
teax deps list <issue>                    # List dependencies
teax deps add <issue> --on <blocker>      # Issue depends on blocker
teax deps add <issue> --blocks <other>    # Issue blocks other
teax deps rm <issue> --on <blocker>       # Remove dependency
```

#### Issue Editing
```bash
teax issue edit <issue> --add-labels "label1,label2"
teax issue edit <issue> --rm-labels "label1"
teax issue edit <issue> --set-labels "label1,label2"
teax issue edit <issue> --assignees "user1,user2"
teax issue edit <issue> --milestone "5"
teax issue edit <issue> --title "New title"
teax issue labels <issue>
```

### Tech Stack

- **Language**: Python 3.11+
- **CLI Framework**: click
- **HTTP Client**: httpx
- **Output**: Rich (tables)
- **Validation**: Pydantic

### Key Principles

1. **Complementary** - Never duplicate tea functionality
2. **Familiar** - Match tea's conventions and flags where possible
3. **Scriptable** - Exit codes, parseable output, quiet mode (future)
4. **Safe** - Dry-run for destructive operations (future)

## Consequences

### Positive

- Eliminates need for raw curl commands
- Scriptable dependency and label management
- Enables ADR-0005 workflow automation
- Reuses tea's authentication
- Consistent with existing tooling patterns

### Negative

- Another tool to maintain
- Must track Gitea API changes
- Potential confusion about tea vs teax scope

### Mitigations

- Clear documentation on when to use each tool
- Minimal scope - only implement what tea can't do
- Consider contributing features upstream to tea

## Feature Gap Analysis (tea v0.9.2)

| Feature | tea Support | teax Scope |
|---------|-------------|------------|
| Issue create | Full | Out of scope |
| Issue list/view | Full | Out of scope |
| Issue edit | Missing | **Primary** |
| Issue dependencies | Missing | **Primary** |
| Issue bulk ops | Missing | Phase 2 |
| Label CRUD | Full | Out of scope |
| Label assign | Missing | Via issue edit |
| Milestone CRUD | Full | Out of scope |
| Milestone assign | Missing | Via issue edit |
| PR operations | Full | Out of scope |
| Project boards | Missing | Future maybe |

## Related Decisions

- [ADR-0005](~/work/dev-manual/docs/adr/ADR-0005-gitea-epic-tracking.md): Epic-style tracking (defines workflow teax enables)

## References

- tea CLI: https://gitea.com/gitea/tea
- Gitea API: https://docs.gitea.com/api/
- tea config location: `~/.config/tea/config.yml`
