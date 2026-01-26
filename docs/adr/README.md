# Architecture Decision Records

ADRs for the teax project.

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-0006](ADR-0006-teax-design.md) | teax Design Decision | Accepted | 2026-01-12 |
| [ADR-0007](ADR-0007-gitea-actions-support.md) | Gitea Actions Support | Implementing | 2026-01-26 |
| [ADR-0008](ADR-0008-package-management.md) | Package Management | Implemented | 2026-01-26 |

## Related ADRs (in dev-manual)

These ADRs in the dev-manual repository provide context for teax:

- [ADR-0005: Epic-Style Tracking](~/work/dev-manual/docs/adr/ADR-0005-gitea-epic-tracking.md) - Defines the workflow that teax enables
- [ADR-0006: teax Design](~/work/dev-manual/docs/adr/ADR-0006-teax-gitea-cli-companion.md) - Original design decision (canonical)

## Creating New ADRs

Use the template format:

```markdown
# ADR-XXXX: Title

**Status**: Proposed | Accepted | Deprecated | Superseded
**Date**: YYYY-MM-DD
**Context**: Brief context statement

## Context

[Detailed problem description]

## Decision

[What we decided and why]

## Consequences

### Positive
- [Benefit 1]

### Negative
- [Drawback 1]

### Mitigations
- [How we address drawbacks]
```
