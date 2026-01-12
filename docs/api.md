# teax API Reference

Using teax as a Python library for programmatic Gitea access.

## Installation

```bash
cd ~/work/teax
poetry install
```

## Quick Start

```python
from teax.api import GiteaClient

# Uses default tea login
with GiteaClient() as client:
    # List dependencies
    deps = client.list_dependencies("owner", "repo", 25)
    for dep in deps:
        print(f"#{dep.number}: {dep.title} ({dep.state})")

    # Add a label
    client.add_issue_labels("owner", "repo", 25, ["prio/p1"])
```

## GiteaClient

The main API client class.

### Constructor

```python
GiteaClient(
    login: TeaLogin | None = None,
    login_name: str | None = None
)
```

**Parameters**:
- `login`: Pre-loaded TeaLogin object (optional)
- `login_name`: Name of tea login to use (optional)

If neither provided, uses the default tea login.

**Example**:
```python
# Default login
client = GiteaClient()

# Specific login by name
client = GiteaClient(login_name="backup.example.com")

# Pre-loaded login
from teax.config import get_login_by_name
login = get_login_by_name("gitea.example.com")
client = GiteaClient(login=login)
```

### Context Manager

Always use as a context manager to ensure proper cleanup:

```python
with GiteaClient() as client:
    # ... use client
# Connection automatically closed
```

### Properties

#### `base_url`
```python
@property
def base_url(self) -> str
```
Returns the Gitea instance URL.

## Issue Operations

### get_issue

```python
def get_issue(self, owner: str, repo: str, index: int) -> Issue
```

Get an issue by number.

**Parameters**:
- `owner`: Repository owner
- `repo`: Repository name
- `index`: Issue number

**Returns**: `Issue` object

**Example**:
```python
issue = client.get_issue("homelab", "myproject", 25)
print(f"{issue.title} ({issue.state})")
print(f"Labels: {[l.name for l in issue.labels]}")
```

### edit_issue

```python
def edit_issue(
    self,
    owner: str,
    repo: str,
    index: int,
    *,
    title: str | None = None,
    body: str | None = None,
    assignees: list[str] | None = None,
    milestone: int | None = None,
) -> Issue
```

Edit an existing issue.

**Parameters**:
- `owner`: Repository owner
- `repo`: Repository name
- `index`: Issue number
- `title`: New title (optional)
- `body`: New body (optional)
- `assignees`: List of usernames (optional)
- `milestone`: Milestone ID, 0 to clear (optional)

**Returns**: Updated `Issue` object

**Example**:
```python
# Update title and assignees
issue = client.edit_issue(
    "homelab", "myproject", 25,
    title="Updated title",
    assignees=["alice", "bob"]
)

# Clear milestone
issue = client.edit_issue(
    "homelab", "myproject", 25,
    milestone=0
)
```

## Label Operations

### get_issue_labels

```python
def get_issue_labels(self, owner: str, repo: str, index: int) -> list[Label]
```

Get labels on an issue.

**Example**:
```python
labels = client.get_issue_labels("homelab", "myproject", 25)
for label in labels:
    print(f"{label.name} (#{label.color})")
```

### add_issue_labels

```python
def add_issue_labels(
    self, owner: str, repo: str, index: int, labels: list[str]
) -> list[Label]
```

Add labels to an issue. Labels must already exist in the repository.

**Example**:
```python
labels = client.add_issue_labels(
    "homelab", "myproject", 25,
    ["epic/diagnostics", "prio/p1"]
)
```

### remove_issue_label

```python
def remove_issue_label(
    self, owner: str, repo: str, index: int, label: str
) -> None
```

Remove a single label from an issue.

**Example**:
```python
client.remove_issue_label("homelab", "myproject", 25, "needs-triage")
```

### set_issue_labels

```python
def set_issue_labels(
    self, owner: str, repo: str, index: int, labels: list[str]
) -> list[Label]
```

Replace all labels on an issue.

**Example**:
```python
# Replace all labels
labels = client.set_issue_labels(
    "homelab", "myproject", 25,
    ["type/feature", "prio/p2"]
)
```

### list_repo_labels

```python
def list_repo_labels(self, owner: str, repo: str) -> list[Label]
```

List all labels in a repository.

**Example**:
```python
labels = client.list_repo_labels("homelab", "myproject")
for label in labels:
    print(f"{label.name}: {label.description}")
```

## Dependency Operations

### list_dependencies

```python
def list_dependencies(
    self, owner: str, repo: str, index: int
) -> list[Dependency]
```

List issues that this issue depends on (blockers).

**Example**:
```python
deps = client.list_dependencies("homelab", "myproject", 25)
for dep in deps:
    print(f"Blocked by #{dep.number}: {dep.title}")
```

### list_blocks

```python
def list_blocks(self, owner: str, repo: str, index: int) -> list[Dependency]
```

List issues that this issue blocks.

**Example**:
```python
blocks = client.list_blocks("homelab", "myproject", 17)
for b in blocks:
    print(f"Blocks #{b.number}: {b.title}")
```

### add_dependency

```python
def add_dependency(
    self,
    owner: str,
    repo: str,
    index: int,
    depends_on_owner: str,
    depends_on_repo: str,
    depends_on_index: int,
) -> None
```

Add a dependency (issue depends on another).

**Parameters**:
- `owner`, `repo`, `index`: The dependent issue
- `depends_on_*`: The issue being depended on

**Example**:
```python
# Issue 25 depends on issue 17
client.add_dependency(
    "homelab", "myproject", 25,
    "homelab", "myproject", 17
)
```

### remove_dependency

```python
def remove_dependency(
    self,
    owner: str,
    repo: str,
    index: int,
    depends_on_owner: str,
    depends_on_repo: str,
    depends_on_index: int,
) -> None
```

Remove a dependency.

**Example**:
```python
client.remove_dependency(
    "homelab", "myproject", 25,
    "homelab", "myproject", 17
)
```

## Models

### Issue

```python
class Issue(BaseModel):
    id: int
    number: int
    title: str
    state: str  # "open" or "closed"
    labels: list[Label]
    assignees: list[User]
    milestone: Milestone | None
```

### Label

```python
class Label(BaseModel):
    id: int
    name: str
    color: str  # Hex color without #
    description: str
```

### User

```python
class User(BaseModel):
    id: int
    login: str
    full_name: str
```

### Milestone

```python
class Milestone(BaseModel):
    id: int
    title: str
    state: str  # "open" or "closed"
```

### Dependency

```python
class Dependency(BaseModel):
    id: int
    number: int
    title: str
    state: str
    repository: Repository
```

### Repository

```python
class Repository(BaseModel):
    id: int
    name: str
    full_name: str  # "owner/repo"
    owner: str
```

## Milestone Operations

### list_milestones

```python
def list_milestones(
    self, owner: str, repo: str, state: str = "all"
) -> list[Milestone]
```

List all milestones in a repository.

**Parameters**:
- `owner`: Repository owner
- `repo`: Repository name
- `state`: Filter by state: 'open', 'closed', or 'all' (default)

**Example**:
```python
milestones = client.list_milestones("homelab", "myproject")
for ms in milestones:
    print(f"{ms.title} ({ms.state})")

# Only open milestones
open_milestones = client.list_milestones("homelab", "myproject", state="open")
```

### resolve_milestone

```python
def resolve_milestone(
    self, owner: str, repo: str, milestone_ref: str
) -> int
```

Resolve a milestone reference (ID or title) to its numeric ID.

**Parameters**:
- `owner`: Repository owner
- `repo`: Repository name
- `milestone_ref`: Milestone ID (e.g., "5") or title (e.g., "Sprint 1")

**Returns**: Milestone ID

**Raises**:
- `ValueError`: If milestone not found by name
- `httpx.HTTPStatusError`: If milestone not found by ID (404)

**Example**:
```python
# Resolve by name
milestone_id = client.resolve_milestone("homelab", "myproject", "Sprint 1")

# Resolve by ID (validates it exists)
milestone_id = client.resolve_milestone("homelab", "myproject", "5")

# Use with edit_issue
issue = client.edit_issue(
    "homelab", "myproject", 25,
    milestone=client.resolve_milestone("homelab", "myproject", "Sprint 1")
)
```

## Configuration

### load_tea_config

```python
from teax.config import load_tea_config

config = load_tea_config()
for login in config.logins:
    print(f"{login.name}: {login.url}")
```

### get_default_login

```python
from teax.config import get_default_login

login = get_default_login()
print(f"Using: {login.name} ({login.url})")
```

### get_login_by_name

```python
from teax.config import get_login_by_name

login = get_login_by_name("backup.example.com")
```

## Error Handling

### API Errors

```python
import httpx

try:
    issue = client.get_issue("owner", "repo", 999)
except httpx.HTTPStatusError as e:
    print(f"HTTP {e.response.status_code}: {e.response.text}")
```

### Config Errors

```python
from teax.config import load_tea_config

try:
    config = load_tea_config()
except FileNotFoundError:
    print("tea not configured - run: tea login add")
```

### Label Not Found

```python
try:
    client.add_issue_labels("owner", "repo", 25, ["nonexistent"])
except ValueError as e:
    print(f"Label error: {e}")
```

## Complete Example

```python
"""Example: Set up an epic with child issues."""

from teax.api import GiteaClient

OWNER = "homelab"
REPO = "myproject"

with GiteaClient() as client:
    # Epic issue (already created via tea)
    EPIC = 24
    CHILDREN = [17, 18, 19, 20, 21]

    # Label the epic
    client.set_issue_labels(OWNER, REPO, EPIC, [
        "type/epic",
        "epic/interactive-diagnostics",
        "prio/p1"
    ])

    # Label child issues
    for child in CHILDREN:
        client.add_issue_labels(OWNER, REPO, child, [
            "epic/interactive-diagnostics"
        ])

    # Set up dependency chain: 20 depends on 21 depends on 17
    client.add_dependency(OWNER, REPO, 21, OWNER, REPO, 17)
    client.add_dependency(OWNER, REPO, 20, OWNER, REPO, 21)
    client.add_dependency(OWNER, REPO, 20, OWNER, REPO, 17)

    # Verify
    deps = client.list_dependencies(OWNER, REPO, 20)
    print(f"Issue #20 depends on: {[d.number for d in deps]}")
```

## Related

- [Usage Guide](usage.md) - CLI usage
- [Gitea API Docs](https://docs.gitea.com/api/) - Official API reference
