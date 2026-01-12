# teax Issue Tracker

Canonical issue list for teax development. Issues are now tracked in Gitea.

---

## Open Issues (Gitea #9-#19)

Quality improvements from codex reviews. All issues tracked in Gitea.

| Gitea # | Title | Priority | Labels |
|---------|-------|----------|--------|
| 9 | Fix base URL subpath handling for non-root Gitea | p1 | type/bug |
| 10 | Pre-validate milestone in bulk command | p2 | type/bug |
| 11 | Use SecretStr for token to prevent leakage | p2 | type/enhancement |
| 12 | Improve pagination efficiency | p3 | type/enhancement |
| 13 | Deduplicate child issues in epic commands | p3 | type/enhancement |
| 14 | Improve input validation for color and repo | p3 | type/enhancement |
| 15 | Reduce redundant label fetches in epic_create | p3 | type/enhancement |
| 16 | Increase CLI test coverage to 80% | p2 | type/test |
| 17 | Add end-to-end tests for epic commands | p3 | type/test |
| 18 | Implement milestone lookup by name | p3 | type/enhancement |
| 19 | Remove unused DependencyRequest model | p3 | type/cleanup |

### 16. Increase CLI test coverage to 80%

**Status:** Open

**Problem:** CLI module at 40% coverage. Many command execution paths untested, including actual bulk operations with API mocking, epic create/status/add with API mocking, and error handling paths.

**Solution:** Add integration tests using respx mocking for CLI commands.

**Acceptance Criteria:**
- [ ] cli.py coverage reaches 80%+
- [ ] Bulk command execution tested with mock API
- [ ] Epic commands tested with mock API
- [ ] Error handling paths covered

**Files affected:**
- tests/test_cli.py

---

### 17. Add end-to-end tests for epic commands

**Status:** Open

**Problem:** Epic command tests only verify help output and helper functions. Actual command execution (`epic_create`, `epic_status`, `epic_add`) not tested with mocked API responses.

**Solution:** Add tests using CliRunner + respx to test full command execution.

**Acceptance Criteria:**
- [ ] epic create tested with label creation and issue creation mocks
- [ ] epic status tested with issue fetch and child issue state checks
- [ ] epic add tested with body update and label application

**Files affected:**
- tests/test_cli.py

---

### 18. Implement milestone lookup by name

**Status:** Open

**Problem:** In `issue_edit` (cli.py:397-400), milestone only accepts numeric IDs. Passing a name shows a warning about lookup not being implemented.

**Solution:** Add milestone list API method, cache results, and resolve names to IDs.

**Acceptance Criteria:**
- [ ] `--milestone "Sprint 1"` works (resolves to ID)
- [ ] Error message if milestone name not found
- [ ] Numeric IDs still work

**Files affected:**
- src/teax/api.py (add list_milestones method)
- src/teax/cli.py (resolve milestone names)

---

### 19. Remove unused DependencyRequest model

**Status:** Open

**Problem:** `DependencyRequest` in models.py (lines 79-84) is defined but never used. Dependency operations construct JSON directly.

**Solution:** Remove the unused model to reduce dead code.

**Acceptance Criteria:**
- [ ] DependencyRequest removed from models.py
- [ ] Tests still pass

**Files affected:**
- src/teax/models.py

---

## Closed Issues

### Phase 2 Features (Gitea #1-#8) - COMPLETED

Epic #1: Phase 2 - Bulk Operations and Epic Helpers (closed)

| Gitea # | Title | Status |
|---------|-------|--------|
| 1 | Epic: Phase 2 - Bulk Operations and Epic Helpers | Closed |
| 2 | Issue range parsing utility | Closed |
| 3 | Bulk command with label support | Closed |
| 4 | Bulk command with assignee/milestone support | Closed |
| 5 | Confirmation prompt with --yes flag | Closed |
| 6 | Epic create command | Closed |
| 7 | Epic status command | Closed |
| 8 | Epic add command | Closed |

### Phase 1 Bug Fixes - COMPLETED

| # | Title | Status |
|---|-------|--------|
| 9 | Low test coverage for API client | Closed (95% coverage achieved) |
| 10 | CSV output doesn't escape special characters | Closed |
| 11 | deps rm allows both --on and --blocks | Closed |
| 12 | README doesn't document TEAX_INSECURE | Closed |
| 13 | Missing test for get_login_by_name | Closed |
| 14 | Label ID resolution makes redundant API calls | Closed (caching implemented) |

---

## Issue Tracking

All issues are now tracked in Gitea:
- https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/teax/issues
