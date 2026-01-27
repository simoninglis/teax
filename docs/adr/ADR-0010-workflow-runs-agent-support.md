# ADR-0010: Workflow Runs and LLM Agent Support

**Status**: Accepted
**Date**: 2026-01-27
**Context**: LLM agents (Claude Code, Codex) need efficient CI/CD debugging; extends ADR-0007 Phase 2

## Context

### Problem Statement

LLM agents working with CI/CD currently face significant friction:

1. **No run visibility**: Can't answer "did CI pass?" without raw API calls
2. **Log verbosity**: Full workflow logs can be 50,000+ tokens, mostly noise
3. **Manual debugging**: Agents use verbose `curl` commands to check run status
4. **No rerun capability**: Must manually navigate web UI to retry failed builds

Real feedback from a build agent:
> "Currently I'm using raw curl calls to the API to check run status and fetch logs, which is quite verbose."

### Design Goals for Agent-Friendly CLI

Based on Codex analysis, high-value features for LLM agents:

1. **Fast failure localisation**: Show what failed without noise
2. **Targeted log retrieval**: `--tail`, `--grep`, `--context` to extract relevant sections
3. **Explicit truncation**: Always indicate when output is truncated
4. **Stable JSON schema**: Consistent, parseable output for machine consumption
5. **Token efficiency**: Summaries and filters to reduce context usage

### API Availability (Gitea 1.25.1)

| Endpoint | Available | Notes |
|----------|-----------|-------|
| `GET /repos/{owner}/{repo}/actions/runs` | ✅ | List runs with full metadata |
| `GET /repos/{owner}/{repo}/actions/runs/{run}/jobs` | ✅ | Jobs for a run |
| `GET /repos/{owner}/{repo}/actions/jobs/{job_id}` | ✅ | Job details with steps |
| `GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs` | ✅ | Job logs (plain text) |
| `DELETE /repos/{owner}/{repo}/actions/runs/{run}` | ✅ | Delete run |
| `POST /repos/{owner}/{repo}/actions/runs/{run}/rerun` | ❌ | PR #35382 pending |
| `POST /repos/{owner}/{repo}/actions/runs/{run}/cancel` | ❌ | PR #35382 pending |
| Step-level logs | ❌ | Only job-level available |

## Decision

### Phase 1: Workflow Runs (Core)

```bash
# Quick health check - "is CI green?"
teax runs status -r owner/repo
# Output: ci.yml: ✓ success (#42) | deploy.yml: ✗ failure (#38, 2h ago)

# List runs
teax runs list -r owner/repo
teax runs list -r owner/repo --workflow ci.yml
teax runs list -r owner/repo --status failure --limit 5
teax runs list -r owner/repo --branch main

# Get run details - "what failed?"
teax runs get <run_id> -r owner/repo
teax runs get <run_id> -r owner/repo --errors-only  # Just failed jobs/steps

# List jobs for a run
teax runs jobs <run_id> -r owner/repo

# Get logs - "why did it fail?"
teax runs logs <job_id> -r owner/repo
teax runs logs <job_id> -r owner/repo --tail 100
teax runs logs <job_id> -r owner/repo --head 50
teax runs logs <job_id> -r owner/repo --grep "Error|FAILED" --context 5
teax runs logs <job_id> -r owner/repo --strip-ansi

# Rerun via dispatch (workaround until native API available)
teax runs rerun <run_id> -r owner/repo
# Warns: "Using workflow dispatch. Original inputs/context not preserved."

# Delete run
teax runs delete <run_id> -r owner/repo -y
```

### Phase 2: Package Linking (Minor)

```bash
# Link package to repository (for discoverability)
teax pkg link <name> --owner <owner> --type <type> --repo owner/repo

# Unlink package from repository
teax pkg unlink <name> --owner <owner> --type <type>

# Get latest version
teax pkg latest <name> --owner <owner> --type <type>
```

Note: Package labeling/metadata is NOT supported by Gitea's API.

### Models

```python
class WorkflowRun(BaseModel):
    """Gitea Actions workflow run."""
    id: int
    run_number: int
    run_attempt: int
    status: str  # queued, in_progress, completed, waiting
    conclusion: str | None  # success, failure, cancelled, skipped
    head_sha: str
    head_branch: str
    event: str  # push, pull_request, workflow_dispatch
    display_title: str
    path: str  # workflow file path
    started_at: str | None
    completed_at: str | None
    html_url: str
    actor: User | None
    repository_id: int

class WorkflowJob(BaseModel):
    """Gitea Actions workflow job."""
    id: int
    run_id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None  # success, failure, cancelled, skipped
    started_at: str | None
    completed_at: str | None
    runner_id: int | None
    runner_name: str | None
    steps: list[WorkflowStep]

class WorkflowStep(BaseModel):
    """Gitea Actions workflow step."""
    number: int
    name: str
    status: str
    conclusion: str | None
    started_at: str | None
    completed_at: str | None
```

### API Methods

```python
class GiteaClient:
    # Workflow runs
    def list_runs(self, owner: str, repo: str, *,
                  workflow: str | None = None,
                  branch: str | None = None,
                  status: str | None = None,
                  max_pages: int = 10) -> list[WorkflowRun]: ...

    def get_run(self, owner: str, repo: str, run_id: int) -> WorkflowRun: ...

    def delete_run(self, owner: str, repo: str, run_id: int) -> None: ...

    def list_run_jobs(self, owner: str, repo: str, run_id: int) -> list[WorkflowJob]: ...

    def get_job(self, owner: str, repo: str, job_id: int) -> WorkflowJob: ...

    def get_job_logs(self, owner: str, repo: str, job_id: int) -> str: ...

    # Rerun workaround
    def rerun_workflow(self, owner: str, repo: str, run_id: int) -> None:
        """Rerun a workflow via dispatch. Falls back since native rerun not available."""
        ...

    # Package linking
    def link_package(self, owner: str, pkg_type: str, name: str, repo: str) -> None: ...

    def unlink_package(self, owner: str, pkg_type: str, name: str) -> None: ...

    def get_latest_package(self, owner: str, pkg_type: str, name: str) -> Package: ...
```

### Output Formats

All commands support `--output table|simple|csv|json`.

JSON output uses stable schema with explicit truncation indicators:

```json
{
  "runs": [...],
  "truncated": true,
  "total_count": 150,
  "returned_count": 10
}
```

Log output with `--grep` includes match metadata:

```json
{
  "job_id": 123,
  "matches": 5,
  "truncated": false,
  "lines": [
    {"line_number": 42, "content": "Error: test failed"}
  ]
}
```

### Rerun Implementation

Since Gitea's native rerun API (PR #35382) is not yet merged:

1. Fetch run details to get `path` (workflow) and `head_branch` (ref)
2. Call existing `dispatch_workflow()` with extracted values
3. Print warning about limitations

```python
def rerun_workflow(self, owner: str, repo: str, run_id: int) -> None:
    # Get run details
    run = self.get_run(owner, repo, run_id)

    # Extract workflow ID from path (e.g., ".github/workflows/ci.yml" -> "ci.yml")
    workflow_id = run.path.split("/")[-1]

    # Dispatch on same branch
    self.dispatch_workflow(owner, repo, workflow_id, run.head_branch)
```

Limitations (documented in output):
- Only works for workflows with `workflow_dispatch` trigger
- Original inputs not preserved
- PR/push context lost

## Consequences

### Positive

- Enables CLI-based CI/CD debugging for LLM agents
- Reduces token usage with filtering and summaries
- Provides workaround for missing rerun API
- Consistent with existing teax patterns

### Negative

- Rerun workaround has limitations
- Log grep is client-side (must fetch full log first)
- Step-level logs not available until Gitea adds API

### Mitigations

- Clear warnings when using dispatch-based rerun
- Document API limitations
- Future-proof: native rerun can replace dispatch when available

## Alternatives Considered

### 1. Wait for Gitea PR #35382
- **Rejected**: Unknown merge timeline; agents need this now

### 2. Only basic run listing
- **Rejected**: Log retrieval is the highest-value feature for debugging

### 3. Server-side log filtering
- **Rejected**: Gitea API doesn't support it; client-side grep acceptable for local network

## References

- [ADR-0007: Gitea Actions Support](ADR-0007-gitea-actions-support.md)
- [Gitea PR #35382: Workflow run management API](https://github.com/go-gitea/gitea/pull/35382)
- [Gitea Issue #35176: Step-level log API](https://github.com/go-gitea/gitea/issues/35176)
- [Codex recommendations for agent-friendly CLI design](internal discussion)
