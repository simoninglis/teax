# teax Implementation Plan v3

**Created:** 2026-01-15
**Status:** Active Development
**Source:** Fresh Codex review 2026-01-15

---

## Executive Summary

This plan addresses security hardening (HTTP token exposure), developer experience fixes (broken version automation, flaky tests), and input validation gaps. Four new critical/important issues identified, plus cleanup of existing backlog.

---

## Issue Summary

| # | Priority | Issue | File(s) | Effort |
|---|----------|-------|---------|--------|
| 21 | CRITICAL | Fail closed on HTTP URLs | api.py | Medium |
| 22 | IMPORTANT | Fix version bump automation | justfile, README | Low |
| 23 | IMPORTANT | Fix hardcoded version test | test_cli.py | Low |
| 24 | IMPORTANT | Validate parse_repo empty segments | cli.py, test_cli.py | Low |
| 20 | p2 | Add --body flag to issue edit | cli.py | Low |
| 19 | p3 | Remove unused DependencyRequest | models.py | Low |
| 9 | p1 | Fix base URL subpath handling | api.py | Medium |

---

## Phase 1: Critical Security

### Issue 21: Fail closed on HTTP URLs

**References:** docs/ISSUES.md #21

**Problem:** API tokens sent over plain HTTP with only a warning, risking credential disclosure.

**Solution:** Raise `ValueError` by default for `http://` URLs, require `TEAX_ALLOW_INSECURE_HTTP=1` to proceed.

**Acceptance Criteria:**
- [x] HTTP URLs raise error by default
- [x] `TEAX_ALLOW_INSECURE_HTTP=1` allows proceeding with warning
- [x] Clear error message explaining the risk
- [x] Tests for both paths

**Implementation:**
1. Modify `GiteaClient.__init__` to check scheme after normalization
2. Raise `ValueError` if `http://` and env var not set
3. Emit warning if env var is set (existing behavior)
4. Add tests for both code paths

---

## Phase 2: Important Fixes

### Issue 22: Fix version bump automation

**References:** docs/ISSUES.md #22

**Problem:** `just bump` tries to edit `__init__.py` which now uses dynamic versioning.

**Solution:** Remove sed command from justfile, update README.

**Acceptance Criteria:**
- [x] `just bump patch` correctly bumps version
- [x] README documentation updated
- [x] No attempt to edit `__init__.py`

**Implementation:**
1. Edit `justfile` bump recipe - remove sed command
2. Update README.md "Releasing" section
3. Test `just bump patch` works correctly

---

### Issue 23: Fix hardcoded version test

**References:** docs/ISSUES.md #23

**Problem:** `test_main_version` asserts `"0.1.0"` which breaks on version bumps.

**Solution:** Use regex or dynamic version comparison.

**Acceptance Criteria:**
- [x] Test passes regardless of current version
- [x] Validates version format is valid SemVer

**Implementation:**
1. Change assertion to regex: `r"teax, version \d+\.\d+\.\d+"`
2. Optionally compare against `importlib.metadata.version("teax")`

---

### Issue 24: Validate parse_repo empty segments

**References:** docs/ISSUES.md #24

**Problem:** `"owner/"` and `"/repo"` pass validation with empty strings.

**Solution:** Add non-empty validation after split.

**Acceptance Criteria:**
- [x] `parse_repo("owner/")` raises BadParameter
- [x] `parse_repo("/repo")` raises BadParameter
- [x] Tests added for edge cases

**Implementation:**
1. Add validation: `if not owner or not repo_name: raise BadParameter`
2. Add test cases for empty owner and empty repo

---

### Issue 20: Add --body flag to issue edit

**References:** docs/ISSUES.md #20

**Problem:** `--body` option missing from CLI despite API support.

**Solution:** Add `--body` option to `issue_edit` command.

**Acceptance Criteria:**
- [x] `teax issue edit 25 --repo o/r --body "text"` updates body
- [x] Tests added

**Implementation:**
1. Add `@click.option("--body", help="Set new body text")`
2. Pass to `client.edit_issue(..., body=body)`
3. Add to changes_made list
4. Add tests

---

## Phase 3: Cleanup

### Issue 19: Remove unused DependencyRequest

**References:** docs/ISSUES.md #19

**Problem:** `DependencyRequest` model never used.

**Solution:** Delete the class.

**Acceptance Criteria:**
- [x] DependencyRequest removed
- [x] Tests still pass

**Implementation:**
1. Remove `DependencyRequest` class from models.py
2. Run tests to verify no regressions

**Note:** Already completed - DependencyRequest never existed or was previously removed.

---

### Issue 9: Fix base URL subpath handling

**References:** docs/ISSUES.md #9

**Problem:** Non-root Gitea installations (e.g., `/gitea/`) may not work correctly.

**Solution:** Improve URL normalization logic.

**Acceptance Criteria:**
- [ ] URLs like `https://host/gitea/` work correctly
- [ ] Tests for subpath scenarios

**Implementation:**
1. Review and fix `_normalize_base_url()`
2. Add tests for subpath URLs

---

## Quality Gates

Before marking plan complete:
1. Tests pass: `just test`
2. Linting clean: `just lint`
3. Types check: `just typecheck`
4. Coverage maintained: ≥94%
5. All acceptance criteria checked

---

## Execution Order

Dependencies and recommended sequence:

1. ✅ **Issue 23** - Fix version test (Low, unblocks CI confidence)
2. ✅ **Issue 22** - Fix bump automation (Low, developer experience)
3. ✅ **Issue 24** - Validate parse_repo (Low, prevents confusing errors)
4. ✅ **Issue 21** - HTTP fail-closed (Medium, security critical)
5. ✅ **Issue 20** - Add --body flag (Low, feature request)
6. ✅ **Issue 19** - Remove DependencyRequest (Low, cleanup - already done)
7. **Issue 9** - Fix base URL subpath (Medium, edge case)

---

## References

- docs/ISSUES.md - Canonical issue tracker
- archive/ - Previous plan versions
- Gitea: https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/teax/issues
