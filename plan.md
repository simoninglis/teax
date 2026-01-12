# teax Implementation Plan v1

**Created:** 2026-01-12
**Status:** Active Development
**Source:** Fresh Codex review 2026-01-12

---

## Executive Summary

This plan addresses code quality issues discovered during review (low test coverage, minor bugs, documentation gaps) and outlines Phase 2 feature implementation (bulk operations and epic helpers). Priority given to fixing bugs and improving test coverage before adding new features.

---

## Issue Summary

| # | Priority | Issue | File(s) | Effort |
|---|----------|-------|---------|--------|
| 11 | CRITICAL | deps rm allows both --on and --blocks | cli.py | Low |
| 10 | IMPORTANT | CSV output doesn't escape special chars | cli.py | Low |
| 12 | IMPORTANT | README missing TEAX_INSECURE docs | README.md | Low |
| 13 | IMPORTANT | Missing get_login_by_name test | test_config.py | Low |
| 9 | IMPORTANT | Low test coverage for API client | test_api.py (new) | High |
| 14 | NICE-TO-HAVE | Label ID resolution redundant calls | api.py | Medium |
| 2 | IMPORTANT | Issue range parsing utility (Gitea) | cli.py | Medium |
| 3 | IMPORTANT | Bulk command with label support (Gitea) | cli.py | Medium |
| 4 | IMPORTANT | Bulk command with assignee/milestone (Gitea) | cli.py | Low |
| 5 | NICE-TO-HAVE | Confirmation prompt --yes flag (Gitea) | cli.py | Low |
| 6 | IMPORTANT | Epic create command (Gitea) | cli.py | High |
| 7 | NICE-TO-HAVE | Epic status command (Gitea) | cli.py | Medium |
| 8 | NICE-TO-HAVE | Epic add command (Gitea) | cli.py | Medium |

---

## Phase 1: Critical Bug Fixes

### Issue 11: deps rm allows both --on and --blocks simultaneously

**References:** docs/ISSUES.md #11

**Problem:** The `deps_rm` command uses `if/if` instead of `if/elif`, allowing both flags to be processed when only one should be allowed.

**Solution:** Change second `if` to `elif` for consistency with `deps_add`.

**Acceptance Criteria:**
- [x] `deps rm` with both flags raises UsageError
- [x] Test added for this case

**Implementation:**
1. Edit `cli.py` line 240: change `if blocks is not None:` to `elif blocks is not None:`
2. Add test in `test_cli.py` mirroring `test_deps_add_rejects_both_on_and_blocks`
3. Run `just check`

---

## Phase 2: Important Improvements

### Issue 10: CSV output doesn't escape special characters

**References:** docs/ISSUES.md #10

**Problem:** CSV output could break if titles contain commas or quotes.

**Solution:** Use Python's csv module for proper escaping.

**Acceptance Criteria:**
- [x] Titles with commas are properly quoted
- [x] CSV output parseable by standard tools

**Implementation:**
1. Import `csv` and `io` modules
2. Refactor `print_deps` and `print_labels` CSV branches to use csv.writer
3. Add test with comma-containing title

---

### Issue 12: README missing TEAX_INSECURE documentation

**References:** docs/ISSUES.md #12

**Problem:** New environment variable not documented.

**Solution:** Add section to README.md.

**Acceptance Criteria:**
- [ ] README documents TEAX_INSECURE=1 usage
- [ ] Explains self-hosted CA use case

**Implementation:**
1. Add "Environment Variables" section to README after "Configuration"
2. Document TEAX_INSECURE with example

---

### Issue 13: Missing get_login_by_name test

**References:** docs/ISSUES.md #13

**Problem:** Config function untested.

**Solution:** Add tests to test_config.py.

**Acceptance Criteria:**
- [ ] Test for successful lookup
- [ ] Test for error when not found

**Implementation:**
1. Add `test_get_login_by_name` using sample_config fixture
2. Add `test_get_login_by_name_not_found` testing error case
3. Run `just check`

---

### Issue 9: Low test coverage for API client

**References:** docs/ISSUES.md #9

**Problem:** API client at 23% coverage, all HTTP methods untested.

**Solution:** Add tests using respx or httpx mocking.

**Acceptance Criteria:**
- [ ] Tests for issue operations
- [ ] Tests for label operations
- [ ] Tests for dependency operations
- [ ] Tests for error handling
- [ ] api.py coverage reaches 80%+

**Implementation:**
1. Add `respx` to dev dependencies
2. Create `tests/test_api.py`
3. Add fixtures for mock responses
4. Test each API method category
5. Test error scenarios (404, 401, network)

---

### Issue 2: Issue range parsing utility (Gitea #2)

**References:** Gitea #2, docs/ISSUES.md Phase 2

**Problem:** No way to specify multiple issues for bulk operations.

**Solution:** Add `parse_issue_spec()` function supporting ranges and lists.

**Acceptance Criteria:**
- [ ] Handles single: `17` → `[17]`
- [ ] Handles range: `17-23` → `[17..23]`
- [ ] Handles list: `17,18,19` → `[17,18,19]`
- [ ] Handles mixed: `17-19,25` → `[17,18,19,25]`
- [ ] Unit tests cover all cases

**Implementation:**
1. Add `parse_issue_spec()` to cli.py
2. Split on comma, then handle ranges
3. Return sorted, deduplicated list
4. Add comprehensive tests

---

### Issue 3: Bulk command with label support (Gitea #3)

**References:** Gitea #3, docs/ISSUES.md Phase 2

**Problem:** Cannot apply label changes to multiple issues at once.

**Solution:** Add `teax issue bulk` command.

**Acceptance Criteria:**
- [ ] `--issues` accepts range spec
- [ ] `--add-labels`, `--rm-labels`, `--set-labels` work
- [ ] Shows progress and summary
- [ ] Non-zero exit on failures

**Implementation:**
1. Add `bulk` command to issue group
2. Use `parse_issue_spec()` from #2
3. Iterate and apply changes
4. Collect errors, report summary

---

### Issue 4: Bulk command with assignee/milestone (Gitea #4)

**References:** Gitea #4, docs/ISSUES.md Phase 2

**Problem:** Bulk command needs assignee/milestone support.

**Solution:** Extend bulk command from #3.

**Acceptance Criteria:**
- [ ] `--assignees` sets assignees on all issues
- [ ] `--milestone` sets milestone
- [ ] Can combine with label options

**Implementation:**
1. Add `--assignees` and `--milestone` options to bulk
2. Include in edit loop
3. Add tests

---

### Issue 6: Epic create command (Gitea #6)

**References:** Gitea #6, docs/ISSUES.md Phase 2

**Problem:** Creating epics manually is tedious.

**Solution:** Add `teax epic create` following ADR-0005 template.

**Acceptance Criteria:**
- [ ] Creates epic issue with template body
- [ ] Creates `epic/{name}` label if needed
- [ ] Applies labels to epic and child issues

**Implementation:**
1. Add `epic` command group
2. Add `create` subcommand
3. Generate body from template
4. Create issue via API
5. Apply labels using bulk logic

---

## Phase 3: Nice-to-Haves

### Issue 14: Label ID resolution redundant calls

**References:** docs/ISSUES.md #14

**Problem:** Fetches all labels on every operation.

**Solution:** Cache within GiteaClient session.

**Acceptance Criteria:**
- [ ] Labels cached per repo
- [ ] Cache invalidated on close

**Implementation:**
1. Add `_label_cache: dict[str, dict[str, int]]` to GiteaClient
2. Check cache before API call
3. Clear in `close()`

---

### Issue 5: Confirmation prompt --yes flag (Gitea #5)

**References:** Gitea #5

**Problem:** Bulk operations should confirm before executing.

**Solution:** Add confirmation prompt with `--yes` skip.

**Acceptance Criteria:**
- [ ] Shows preview of changes
- [ ] Prompts for confirmation
- [ ] `--yes` skips prompt

**Implementation:**
1. Add `--yes/-y` flag to bulk
2. Show issue list and changes
3. Use click.confirm()

---

### Issue 7: Epic status command (Gitea #7)

**References:** Gitea #7

**Problem:** No way to see epic progress.

**Solution:** Add `teax epic status` command.

**Acceptance Criteria:**
- [ ] Parses child issues from body
- [ ] Shows progress percentage
- [ ] Lists open/closed issues

**Implementation:**
1. Add `status` subcommand
2. Parse checklist with regex
3. Fetch child issue states
4. Display progress

---

### Issue 8: Epic add command (Gitea #8)

**References:** Gitea #8

**Problem:** Cannot add issues to existing epic.

**Solution:** Add `teax epic add` command.

**Acceptance Criteria:**
- [ ] Appends to checklist
- [ ] Applies epic label to new issues

**Implementation:**
1. Add `add` subcommand
2. Parse existing body
3. Append new issues
4. Update via API

---

## Quality Gates

Before marking plan complete:
1. Tests pass: `just test`
2. Linting clean: `just lint`
3. Types check: `just typecheck`
4. All gates: `just check`
5. Coverage maintained: ≥39% (improve toward 80%)

---

## Execution Order

Implementation sequence considering dependencies:

1. ✅ **Issue 11** - deps rm bug fix (Phase 1) - no dependencies
2. ✅ **Issue 10** - CSV escaping (Phase 2) - no dependencies
3. **Issue 12** - README TEAX_INSECURE (Phase 2) - no dependencies
4. **Issue 13** - get_login_by_name test (Phase 2) - no dependencies
5. **Issue 9** - API client tests (Phase 2) - no dependencies
6. **Issue 2** - Range parsing utility (Phase 2) - foundation for bulk
7. **Issue 3** - Bulk labels (Phase 2) - depends on #2
8. **Issue 4** - Bulk assignees/milestone (Phase 2) - depends on #2
9. **Issue 14** - Label caching (Phase 3) - optimization
10. **Issue 5** - Confirmation prompts (Phase 3) - depends on #3
11. **Issue 6** - Epic create (Phase 2) - depends on #3
12. **Issue 7** - Epic status (Phase 3) - independent
13. **Issue 8** - Epic add (Phase 3) - depends on #6

---

## References

- docs/ISSUES.md - Canonical issue tracker
- archive/ - Previous plan versions
- Gitea issues #1-#8 - Phase 2 feature tracking
