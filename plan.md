# teax Implementation Plan v4

**Created:** 2026-01-16
**Status:** Active Development
**Source:** Fresh Codex review 2026-01-16, Issue #25 focus

---

## Executive Summary

This plan focuses on implementing the batch issue view command (#25) requested for Claude Code integration, followed by maintenance items (epic tests, optimization). The codebase is in excellent shape (Grade A, 96% coverage) after recent security hardening.

---

## Issue Summary

| # | Priority | Issue | File(s) | Effort |
|---|----------|-------|---------|--------|
| 25 | IMPORTANT | Add batch issue view command | cli.py, api.py | Medium |
| 17 | NICE-TO-HAVE | Add end-to-end tests for epic commands | test_cli.py | Medium |
| 15 | NICE-TO-HAVE | Reduce redundant label fetches | cli.py | Low |
| 12 | NICE-TO-HAVE | Improve pagination efficiency | api.py | Low |

---

## Phase 1: Feature Development

### Issue 25: Add batch issue view command for Claude Code integration

**References:** docs/ISSUES.md #25, Gitea #25

**Problem:** No way to fetch details for multiple issues at once. Claude Code and other automation tools need to call `teax issue view` multiple times.

**Solution:** Add `teax issue batch <spec> --repo owner/repo` command with JSON output support.

**Acceptance Criteria:**
- [x] Command accepts issue spec (1-5,10,12 format) using existing `parse_issue_spec()`
- [x] Output includes: number, title, state, labels, assignees, milestone, body
- [x] Supports --output table|csv|json (extend OutputFormat class)
- [x] JSON output includes full body, table/csv truncates to ~200 chars
- [x] Error handling for individual issue fetch failures (continue with others)
- [x] Tests with respx mocking (12 tests added)

**Implementation:**
1. Add `get_issues()` method to GiteaClient (batch fetch with error handling per issue)
2. Add JSON support to OutputFormat class with `print_issues()` method
3. Add `issue batch` command to cli.py using parse_issue_spec
4. Add comprehensive tests for batch command
5. Update README with batch command examples

**Files affected:**
- src/teax/api.py - add get_issues() method
- src/teax/cli.py - add issue batch command, extend OutputFormat
- tests/test_cli.py - add batch command tests
- tests/test_api.py - add get_issues tests
- README.md - document new command

---

## Phase 2: Test Coverage

### Issue 17: Add end-to-end tests for epic commands

**References:** docs/ISSUES.md #17, Gitea #17

**Problem:** Epic commands lack integration tests exercising the full flow.

**Solution:** Add comprehensive CLI tests with respx mocking for all epic commands.

**Acceptance Criteria:**
- [x] Tests for `epic create` basic and with children (6 tests)
- [x] Tests for `epic status` with open/closed children (4 tests)
- [x] Tests for `epic add` with new and existing children (6 tests)
- [x] Error handling tests (label not found, issue not found) (already covered)

**Implementation:**
1. Add test fixtures for epic-related API responses
2. Add test_epic_create_* tests covering various scenarios
3. Add test_epic_status_* tests for progress display
4. Add test_epic_add_* tests for adding children

**Files affected:**
- tests/test_cli.py

---

## Phase 3: Optimization (Nice-to-Haves)

### Issue 15: Reduce redundant label fetches in epic_create

**References:** docs/ISSUES.md #15, Gitea #15

**Problem:** `epic_create` calls `list_repo_labels()` then `_resolve_label_ids()` separately.

**Solution:** The label cache from `list_repo_labels()` should be used by subsequent operations. Verify and optimize if needed.

**Acceptance Criteria:**
- [x] Only one label fetch API call per epic create operation (cache used)
- [x] Label cache properly utilized (5 tests verify: test_list_repo_labels_populates_cache, test_label_cache_avoids_redundant_calls, test_label_cache_per_repo, test_label_cache_cleared_on_close, test_label_cache_updated_on_create_label)

**Implementation:**
1. Trace API calls in epic_create flow
2. Ensure list_repo_labels populates cache before add_issue_labels
3. Verify with test that only expected API calls are made

**Files affected:**
- src/teax/cli.py

---

### Issue 12: Improve pagination efficiency

**References:** docs/ISSUES.md #12, Gitea #12

**Problem:** Pagination may make extra empty-page request.

**Solution:** Verify all pagination sites use `len(items) < limit` early exit.

**Acceptance Criteria:**
- [ ] All pagination loops exit without extra request
- [ ] Tests verify call counts

**Implementation:**
1. Audit all pagination loops in api.py
2. Ensure `if len(items) < limit: break` before incrementing page
3. Add tests verifying pagination call counts

**Files affected:**
- src/teax/api.py
- tests/test_api.py

---

## Quality Gates

Before marking plan complete:
1. Tests pass: `just test`
2. Linting clean: `just lint`
3. Types check: `just typecheck`
4. Coverage maintained: ≥94%

---

## Execution Order

1. ✅ **Issue 25** - Add batch issue view command (Phase 1) - PRIMARY FOCUS
2. ✅ **Issue 17** - Add epic command tests (Phase 2) - Already covered
3. ✅ **Issue 15** - Optimize label fetches (Phase 3) - Already optimized
4. **Issue 12** - Optimize pagination (Phase 3)

---

## References

- docs/ISSUES.md - Canonical issue tracker
- archive/ - Previous plan versions (v1-v3)
- Gitea #25 - Batch issue view feature request
