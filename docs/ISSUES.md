# teax Issue Tracker

Canonical issue list for teax development. Primary tracking in Gitea.

**Gitea:** https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/teax/issues

---

## Open Issues

| Gitea # | Title | Priority | Status |
|---------|-------|----------|--------|
| 25 | Add batch issue view command for Claude Code integration | p2 | Open |
| 17 | Add end-to-end tests for epic commands | p3 | Open |
| 15 | Reduce redundant label fetches in epic_create | p3 | Open |
| 12 | Improve pagination efficiency | p3 | Open |

---

### 25. Add batch issue view command for Claude Code integration

**Status:** Open (created 2026-01-16)

**Problem:** No way to fetch details for multiple issues at once. Claude Code and other automation tools need to call `teax issue view` multiple times to understand several issues.

**Solution:** Add `teax issue batch <spec> --repo owner/repo` command that fetches and displays multiple issues in one operation.

**Acceptance Criteria:**
- [ ] Command accepts issue spec (1-5,10,12 format)
- [ ] Output includes: number, title, state, labels, assignees, milestone, body
- [ ] Supports --output table|csv|json
- [ ] JSON output ideal for programmatic consumption
- [ ] Body truncated to ~200 chars for table/csv, full for json

**Files affected:**
- src/teax/cli.py
- src/teax/api.py (may need get_issues method)
- tests/test_cli.py

---

### 17. Add end-to-end tests for epic commands

**Status:** Open

**Problem:** Epic commands (`epic create`, `epic status`, `epic add`) lack integration tests that exercise the full flow with mocked API responses.

**Solution:** Add comprehensive CLI tests for epic commands with respx mocking.

**Acceptance Criteria:**
- [ ] Tests for `epic create` with various options
- [ ] Tests for `epic status` progress display
- [ ] Tests for `epic add` with existing/new children
- [ ] Error handling tests for each command

**Files affected:**
- tests/test_cli.py

---

### 15. Reduce redundant label fetches in epic_create

**Status:** Open

**Problem:** `epic_create` calls `list_repo_labels()` and then also fetches labels through `_resolve_label_ids()`, causing redundant API calls.

**Solution:** Use the label cache populated by `list_repo_labels()` in subsequent operations.

**Acceptance Criteria:**
- [ ] Only one API call to fetch labels per operation
- [ ] Label cache is properly utilized

**Files affected:**
- src/teax/cli.py (epic_create command)

---

### 12. Improve pagination efficiency

**Status:** Open

**Problem:** Pagination loops make an extra request to get an empty page before terminating.

**Solution:** Check `len(items) < limit` to detect last page and break early (already partially implemented, but verify all pagination sites).

**Acceptance Criteria:**
- [ ] All pagination loops exit without extra empty-page request
- [ ] Tests verify efficient pagination

**Files affected:**
- src/teax/api.py

---

## Recently Closed (2026-01-16)

| Gitea # | Title | Priority | Resolution |
|---------|-------|----------|------------|
| 21 | Fail closed on HTTP URLs (token over plain HTTP) | CRITICAL | Fixed - blocks HTTP by default |
| 22 | Fix version bump automation for metadata-based versioning | IMPORTANT | Fixed - justfile simplified |
| 23 | Fix hardcoded version string in CLI test | IMPORTANT | Fixed - uses SemVer regex |
| 24 | Validate parse_repo rejects empty owner/repo segments | IMPORTANT | Fixed - validates non-empty |
| 20 | Add --body flag to issue edit command | p2 | Fixed |
| 19 | Remove unused DependencyRequest model | p3 | N/A - model never existed |
| 9 | Fix base URL subpath handling for non-root Gitea | p1 | Fixed - _normalize_base_url handles subpaths |
| 10 | Pre-validate milestone in bulk command | p2 | Fixed - validates before changes |
| 13 | Deduplicate child issues in epic commands | p3 | Fixed - sorted(set(children)) |
| 14 | Improve input validation for color and repo | p3 | Fixed - hex validation, extra slash rejection |

---

## Closed Issues

### Phase 3 Security Hardening (v0.1.3)

- HTTP URL blocking with explicit opt-in
- URL scheme validation on TeaLogin
- Config file error handling (PermissionError, etc.)
- Path traversal prevention via _seg()
- trust_env=False to prevent proxy token leakage

### Phase 2 Features (v0.1.0-v0.1.2)

| Gitea # | Title |
|---------|-------|
| 18 | Implement milestone lookup by name |
| 16 | Increase CLI test coverage to 80% (achieved 96%) |
| 11 | Use SecretStr for token |
| 1-8 | Bulk operations and epic helpers |

---

## Nice-to-Have (Not Yet in Gitea)

These items identified in reviews may be added as issues later:

- **Async/parallel API calls**: Use httpx async client for batch operations
- **JSON output for existing commands**: Add --output json to issue view, deps list
- **Issue list command**: List issues (tea has this but output parsing is annoying)
