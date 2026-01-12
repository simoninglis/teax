# teax Usage Guide

Complete guide to using teax for Gitea issue management.

## Prerequisites

1. **tea CLI installed and configured**
   ```bash
   # Install tea (if not already)
   # See: https://gitea.com/gitea/tea

   # Add a login
   tea login add
   ```

2. **teax installed**
   ```bash
   cd ~/work/teax
   poetry install
   ```

## Global Options

All commands support these options:

```bash
teax --help                    # Show help
teax --version                 # Show version
teax --login NAME ...          # Use specific tea login
teax --output FORMAT ...       # Output format: table, simple, csv
```

## Dependency Management

### List Dependencies

Show what an issue depends on and what it blocks:

```bash
teax deps list 25 --repo homelab/myproject
```

**Output (table format)**:
```
              Issue #25 depends on
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ #  ┃ Title                   ┃ State ┃ Repository       ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 17 │ Fix ArrClient returns   │ open  │ homelab/myproject│
│ 21 │ Enhanced queue display  │ open  │ homelab/myproject│
└────┴─────────────────────────┴───────┴──────────────────┘
```

**Simple format** (for scripting):
```bash
teax deps list 25 --repo homelab/myproject --output simple
# Output:
# #17
# #21
```

**CSV format**:
```bash
teax deps list 25 --repo homelab/myproject --output csv
# Output:
# number,title,state,repository
# 17,Fix ArrClient returns,open,homelab/myproject
# 21,Enhanced queue display,open,homelab/myproject
```

### Add Dependencies

**Issue depends on another** (25 depends on 17):
```bash
teax deps add 25 --repo homelab/myproject --on 17
# Added: #25 now depends on #17
```

**Issue blocks another** (17 blocks 25):
```bash
teax deps add 17 --repo homelab/myproject --blocks 25
# Added: #17 now blocks #25
```

### Remove Dependencies

```bash
teax deps rm 25 --repo homelab/myproject --on 17
# Removed: #25 no longer depends on #17

teax deps rm 17 --repo homelab/myproject --blocks 25
# Removed: #17 no longer blocks #25
```

## Issue Editing

### Labels

**Add labels**:
```bash
teax issue edit 25 --repo homelab/myproject --add-labels "epic/diagnostics,prio/p1"
# Updated issue #25:
#   - labels added: epic/diagnostics, prio/p1
```

**Remove labels**:
```bash
teax issue edit 25 --repo homelab/myproject --rm-labels "needs-triage"
# Updated issue #25:
#   - labels removed: needs-triage
```

**Replace all labels**:
```bash
teax issue edit 25 --repo homelab/myproject --set-labels "type/feature,prio/p2"
# Updated issue #25:
#   - labels set to: type/feature, prio/p2
```

**List current labels**:
```bash
teax issue labels 25 --repo homelab/myproject
```

### Assignees

```bash
teax issue edit 25 --repo homelab/myproject --assignees "alice,bob"
# Updated issue #25:
#   - assignees: alice, bob
```

### Milestone

```bash
# Set milestone (by ID)
teax issue edit 25 --repo homelab/myproject --milestone 5

# Clear milestone
teax issue edit 25 --repo homelab/myproject --milestone ""
```

### Title

```bash
teax issue edit 25 --repo homelab/myproject --title "New improved title"
```

### Combined Changes

Multiple changes in one command:
```bash
teax issue edit 25 --repo homelab/myproject \
    --add-labels "prio/p0" \
    --assignees "alice" \
    --title "URGENT: Fix critical bug"
# Updated issue #25:
#   - labels added: prio/p0
#   - assignees: alice
#   - title: URGENT: Fix critical bug
```

## Workflow Examples

### Setting Up an Epic (per ADR-0005)

```bash
# 1. Create the epic issue with tea
tea issues create --title "Epic: Interactive Diagnostics" \
    --description "Parent issue for diagnostic commands"
# Returns: Created issue #24

# 2. Add epic labels with teax
teax issue edit 24 --repo homelab/myproject \
    --set-labels "type/epic,epic/interactive-diagnostics,prio/p1"

# 3. Label child issues
teax issue edit 17 --repo homelab/myproject \
    --add-labels "epic/interactive-diagnostics"
teax issue edit 18 --repo homelab/myproject \
    --add-labels "epic/interactive-diagnostics"

# 4. Set up dependencies
teax deps add 20 --repo homelab/myproject --on 17
teax deps add 21 --repo homelab/myproject --on 17
teax deps add 20 --repo homelab/myproject --on 21
```

### Triaging New Issues

```bash
# Add initial labels
teax issue edit 30 --repo homelab/myproject \
    --add-labels "type/bugfix,prio/p2,area/cli" \
    --rm-labels "needs-triage"

# Assign to developer
teax issue edit 30 --repo homelab/myproject --assignees "alice"

# Add to milestone
teax issue edit 30 --repo homelab/myproject --milestone 3
```

### Bulk Sprint Planning (Manual)

```bash
# Add sprint label to multiple issues
for issue in 17 18 19 20; do
    teax issue edit $issue --repo homelab/myproject --add-labels "sprint/current"
done
```

## Using Multiple Gitea Instances

If you have multiple Gitea logins configured in tea:

```bash
# List available logins
tea login list

# Use specific login
teax --login backup.example.com deps list 25 --repo org/repo
```

## Scripting with teax

### Get Dependencies as List

```bash
# Get just issue numbers
teax deps list 25 --repo homelab/myproject --output simple | tr -d '#'
# Output: 17\n21

# Use in a loop
for dep in $(teax deps list 25 --repo homelab/myproject --output simple | tr -d '#'); do
    echo "Processing dependency: $dep"
done
```

### Check for Blockers

```bash
# Check if issue has dependencies
deps=$(teax deps list 25 --repo homelab/myproject --output simple)
if [ -n "$deps" ]; then
    echo "Issue 25 is blocked by: $deps"
fi
```

## Error Handling

### Common Errors

**Login not found**:
```
Error: tea config not found at ~/.config/tea/config.yml. Please configure tea first: tea login add
```
Solution: Run `tea login add` to configure authentication.

**Label not found**:
```
Error: Label 'nonexistent' not found in repository
```
Solution: Create the label first using Gitea web UI or `tea labels create`.

**Issue not found**:
```
Error: 404 Client Error: Not Found for url: .../issues/999
```
Solution: Verify the issue number and repository.

### Debug Mode

For troubleshooting, check the actual API responses:

```bash
# Enable verbose output (coming in Phase 2)
# For now, use Python directly:
python -c "
from teax.api import GiteaClient
with GiteaClient() as c:
    print(c.list_dependencies('owner', 'repo', 25))
"
```

## Related Documentation

- [API Reference](api.md) - Using teax as a Python library
- [ADR-0005: Epic Tracking](~/work/dev-manual/docs/adr/ADR-0005-gitea-epic-tracking.md) - Label taxonomy and workflow
- [ADR-0006: teax Design](adr/ADR-0006-teax-design.md) - Design decisions
