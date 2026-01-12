# teax Implementation Plan v2

**Created:** 2026-01-12
**Status:** Active Development
**Source:** Fresh Codex review 2026-01-12

---

## Executive Summary

This plan addresses remaining quality improvements: 1 bug (base URL subpath), security hardening (SecretStr), test coverage improvements (CLI at 40%), and code cleanup. All Phase 2 features (bulk ops, epic helpers) are complete. Focus is now on polish and production readiness.

---

## Issue Summary

| # | Priority | Issue | File(s) | Effort |
|---|----------|-------|---------|--------|
| 9 | CRITICAL | Base URL subpath handling | api.py | Medium |
| 10 | IMPORTANT | Pre-validate milestone in bulk | cli.py | Low |
| 11 | IMPORTANT | SecretStr for token | models.py, api.py | Low |
| 16 | IMPORTANT | CLI test coverage to 80% | test_cli.py | High |
| 12 | NICE-TO-HAVE | Pagination efficiency | api.py | Medium |
| 13 | NICE-TO-HAVE | Deduplicate epic children | cli.py | Low |
| 14 | NICE-TO-HAVE | Input validation (color, repo) | cli.py | Low |
| 15 | NICE-TO-HAVE | Reduce label fetches in epic_create | cli.py | Low |
| 17 | NICE-TO-HAVE | Epic command e2e tests | test_cli.py | Medium |
| 18 | NICE-TO-HAVE | Milestone lookup by name | api.py, cli.py | Medium |
| 19 | NICE-TO-HAVE | Remove unused DependencyRequest | models.py | Low |

---

## Phase 1: Critical Bug Fix

### Issue 9: Base URL subpath handling for non-root Gitea

**References:** Gitea #9, docs/ISSUES.md #9

**Problem:** If Gitea is hosted at a subpath (e.g., `https://example.com/gitea/`), the current implementation may construct incorrect API URLs.

**Solution:** Ensure base URL handling preserves subpaths when constructing API endpoints.

**Acceptance Criteria:**
- [x] API calls work with `url: https://example.com/gitea/`
- [x] Trailing slashes handled correctly
- [x] Test added for subpath URL handling

**Implementation:**
1. Review URL construction in `GiteaClient.__init__` (api.py:37-38)
2. Ensure `/api/v1/...` is appended correctly to subpaths
3. Add test case for subpath URL handling
4. Run `just check`

---

## Phase 2: Important Improvements

### Issue 10: Pre-validate milestone in bulk command

**References:** Gitea #10, docs/ISSUES.md #10

**Problem:** Bulk command applies changes sequentially. If milestone is invalid, some issues may be updated before failure, causing partial changes.

**Solution:** Validate milestone exists before starting bulk operation.

**Acceptance Criteria:**
- [x] Invalid milestone ID fails fast before any changes
- [x] Clear error message provided
- [x] Test covers this case

**Implementation:**
1. Add milestone validation at start of `issue_bulk` command
2. Fetch milestone by ID to verify it exists
3. Fail with clear error if not found
4. Add test for invalid milestone handling

---

### Issue 11: Use SecretStr for token to prevent leakage

**References:** Gitea #11, docs/ISSUES.md #11

**Problem:** Token stored as plain `str` in `TeaLogin` model. Could leak in error messages, logs, or repr output.

**Solution:** Use Pydantic's `SecretStr` for the token field.

**Acceptance Criteria:**
- [x] Token uses SecretStr in TeaLogin model
- [x] Token value not visible in repr/str output
- [x] API client updated to call `.get_secret_value()`
- [x] Tests updated for SecretStr handling

**Implementation:**
1. Change `token: str` to `token: SecretStr` in models.py
2. Update api.py line 40: `self._login.token.get_secret_value()`
3. Update test fixtures to use SecretStr
4. Run `just check`

---

### Issue 16: Increase CLI test coverage to 80%

**References:** docs/ISSUES.md #16

**Problem:** CLI module at 40% coverage. Major execution paths untested.

**Solution:** Add integration tests with respx mocking.

**Acceptance Criteria:**
- [x] cli.py coverage reaches 80%+ (97% achieved)
- [x] deps_list, deps_add, deps_rm tested with mock API
- [x] issue_edit tested with mock API
- [x] issue_bulk tested with mock API (success path)
- [x] Error handling paths covered

**Implementation:**
1. Add fixture for mocked GiteaClient in tests
2. Add tests for deps commands with respx mocking
3. Add tests for issue edit command
4. Add tests for bulk command execution
5. Run `just check`, verify coverage

---

## Phase 3: Nice-to-Haves

### Issue 12: Improve pagination efficiency

**References:** Gitea #12, docs/ISSUES.md #12

**Problem:** Pagination always makes an extra request for an empty page to detect end. This wastes an API call per paginated operation.

**Solution:** Check if returned items < limit to detect last page.

**Acceptance Criteria:**
- [x] No extra empty-page request when items < limit
- [x] Still works correctly when items == limit (needs next page check)
- [x] Tests verify reduced API calls

**Implementation:**
1. In `_resolve_label_ids` and `list_repo_labels`, check `len(items) < limit`
2. If fewer items than limit, pagination is done
3. Update tests to verify correct call counts

---

### Issue 13: Deduplicate child issues in epic commands

**References:** Gitea #13, docs/ISSUES.md #13

**Problem:** `epic_create` and `epic_add` don't deduplicate child issue numbers. Duplicate children could be added to checklist.

**Solution:** Deduplicate and sort child issue numbers before processing.

**Acceptance Criteria:**
- [ ] Duplicate child issues filtered out
- [ ] Warning shown if duplicates removed
- [ ] Test covers duplicate handling

**Implementation:**
1. In `epic_create`, convert `children` tuple to sorted set
2. In `epic_add`, deduplicate `children` parameter
3. Show warning if duplicates found
4. Add test case

---

### Issue 14: Improve input validation for color and repo parameters

**References:** Gitea #14, docs/ISSUES.md #14

**Problem:** No validation for hex color format in `epic_create`. No validation that repo contains `/` before command execution.

**Solution:** Add early validation for color format and repo format.

**Acceptance Criteria:**
- [ ] Invalid hex color rejected with clear error
- [ ] Repo without `/` rejected early
- [ ] Tests cover validation

**Implementation:**
1. Add color validation in `epic_create` (regex: `^[0-9a-fA-F]{6}$`)
2. Repo validation already handled by `parse_repo`, ensure called early
3. Add tests for invalid inputs

---

### Issue 15: Reduce redundant label fetches in epic_create

**References:** Gitea #15, docs/ISSUES.md #15

**Problem:** `epic_create` calls `list_repo_labels()` to check if label exists, then the label cache in `_resolve_label_ids` also fetches labels. Double fetch on first operation.

**Solution:** Use the label cache for existence checking.

**Acceptance Criteria:**
- [ ] Only one label fetch per repo in epic_create flow
- [ ] Label existence check uses cache

**Implementation:**
1. In `epic_create`, use `_resolve_label_ids` for label existence check
2. Catch ValueError to detect missing label
3. Create label only if not found
4. Cache will be populated for subsequent operations

---

### Issue 17: Add end-to-end tests for epic commands

**References:** docs/ISSUES.md #17

**Problem:** Epic commands only have help/helper tests. Full execution paths untested.

**Solution:** Add CliRunner + respx tests for epic commands.

**Acceptance Criteria:**
- [ ] epic create tested end-to-end
- [ ] epic status tested end-to-end
- [ ] epic add tested end-to-end

**Implementation:**
1. Add respx mock fixtures for epic API calls
2. Test epic create: label check, label create, issue create, child labeling
3. Test epic status: issue fetch, child issue fetch, output verification
4. Test epic add: issue fetch, body update, child labeling

---

### Issue 18: Implement milestone lookup by name

**References:** docs/ISSUES.md #18

**Problem:** `--milestone` only accepts numeric IDs. Warning shown for name lookup.

**Solution:** Add milestone list API and name resolution.

**Acceptance Criteria:**
- [ ] `--milestone "Sprint 1"` resolves to ID
- [ ] Error if milestone name not found
- [ ] Numeric IDs still work

**Implementation:**
1. Add `list_milestones(owner, repo)` to api.py
2. Add milestone name cache similar to label cache
3. In cli.py, try int() first, then name lookup
4. Add tests for name resolution

---

### Issue 19: Remove unused DependencyRequest model

**References:** docs/ISSUES.md #19

**Problem:** `DependencyRequest` model defined but never used.

**Solution:** Remove dead code.

**Acceptance Criteria:**
- [x] DependencyRequest removed
- [x] Tests pass

**Implementation:**
1. Remove DependencyRequest class from models.py
2. Run `just check`

---

## Quality Gates

Before marking plan complete:
1. Tests pass: `just test`
2. Linting clean: `just lint`
3. Types check: `just typecheck`
4. All gates: `just check`
5. Coverage maintained: ≥55% (target 80%+ for cli.py)

---

## Execution Order

Implementation sequence considering dependencies:

1. ✅ **Issue 9** - Base URL subpath handling (Phase 1) - critical bug
2. ✅ **Issue 19** - Remove unused model (Phase 3) - quick cleanup
3. ✅ **Issue 11** - SecretStr for token (Phase 2) - security hardening
4. ✅ **Issue 10** - Pre-validate milestone in bulk (Phase 2) - bug prevention
5. ✅ **Issue 16** - CLI test coverage (Phase 2) - foundation for other tests
6. ✅ **Issue 12** - Pagination efficiency (Phase 3) - optimization
7. ⏳ **Issue 13** - Deduplicate epic children (Phase 3) - UX improvement
8. **Issue 14** - Input validation (Phase 3) - robustness
9. **Issue 15** - Reduce label fetches (Phase 3) - optimization
10. **Issue 17** - Epic e2e tests (Phase 3) - test coverage
11. **Issue 18** - Milestone lookup by name (Phase 3) - feature enhancement

---

## References

- docs/ISSUES.md - Canonical issue tracker
- archive/ - Previous plan versions
- Gitea issues #9-#15 - External issue tracking
