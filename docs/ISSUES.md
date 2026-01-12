# teax Issue Tracker

Canonical issue list for teax development. Phase 2 features are tracked in Gitea (#1-#8).

---

## Open Issues

### 9. Low test coverage for API client Open

**Status:** Open

**Problem:** The API client (`api.py`) has only 23% test coverage. All API methods that make HTTP calls are untested, making it risky to refactor or extend.

**Solution:** Add integration-style tests using httpx mock or respx to test API client methods without hitting real servers.

**Acceptance Criteria:**
- [ ] Tests for `get_issue`, `edit_issue`
- [ ] Tests for label operations (`get_issue_labels`, `add_issue_labels`, `remove_issue_label`, `set_issue_labels`)
- [ ] Tests for dependency operations (`list_dependencies`, `list_blocks`, `add_dependency`, `remove_dependency`)
- [ ] Tests for error handling (404, 401, network errors)
- [ ] Coverage for api.py reaches 80%+

**Files affected:**
- tests/test_api.py (new)
- src/teax/api.py

---

### 10. CSV output doesn't escape special characters Open

**Status:** Open

**Problem:** The CSV output format in `OutputFormat.print_deps` and `print_labels` doesn't escape commas or quotes in titles/descriptions, which could break CSV parsing.

**Solution:** Use Python's `csv` module for proper escaping, or at minimum quote fields containing special characters.

**Acceptance Criteria:**
- [ ] Titles with commas are properly quoted
- [ ] Descriptions with quotes are properly escaped
- [ ] CSV output can be parsed by standard CSV tools

**Files affected:**
- src/teax/cli.py (OutputFormat class)

---

### 11. deps rm allows both --on and --blocks simultaneously Open

**Status:** Open

**Problem:** The `deps_rm` command (line 227-228) uses `if/if` instead of `if/elif`, allowing both `--on` and `--blocks` to be processed. This differs from `deps_add` which correctly rejects both.

**Solution:** Change the second `if` to `elif` for consistency with `deps_add`.

**Acceptance Criteria:**
- [ ] `deps rm` with both `--on` and `--blocks` raises UsageError
- [ ] Test added for this case

**Files affected:**
- src/teax/cli.py (deps_rm function)
- tests/test_cli.py

---

### 12. README doesn't document TEAX_INSECURE environment variable Open

**Status:** Open

**Problem:** The `TEAX_INSECURE=1` environment variable for self-hosted CA instances was added but not documented in README.md.

**Solution:** Add a section to README documenting the environment variable.

**Acceptance Criteria:**
- [ ] README documents TEAX_INSECURE usage
- [ ] Explains when to use it (self-hosted CA)

**Files affected:**
- README.md

---

### 13. Missing test for get_login_by_name Open

**Status:** Open

**Problem:** The `get_login_by_name` function in config.py is not tested, though it's used for the `--login` flag.

**Solution:** Add tests for successful lookup and error case.

**Acceptance Criteria:**
- [ ] Test for finding login by name
- [ ] Test for error when login not found

**Files affected:**
- tests/test_config.py

---

### 14. Label ID resolution makes redundant API calls Open

**Status:** Open

**Problem:** `_resolve_label_ids` fetches all repo labels on every label operation. When editing multiple issues or doing bulk operations, this causes redundant API calls.

**Solution:** Cache label IDs per repo within a GiteaClient session, or accept label IDs directly as an alternative to names.

**Acceptance Criteria:**
- [ ] Label resolution cached within single GiteaClient session
- [ ] Subsequent operations reuse cached labels
- [ ] Cache invalidated on client close

**Files affected:**
- src/teax/api.py

---

## Phase 2 Features (Gitea #1-#8)

These are tracked in Gitea as Epic #1: Phase 2 - Bulk Operations and Epic Helpers.

| Gitea # | Title | Priority | Status |
|---------|-------|----------|--------|
| 1 | Epic: Phase 2 - Bulk Operations and Epic Helpers | p1 | Open |
| 2 | Issue range parsing utility | p0 | Open |
| 3 | Bulk command with label support | p1 | Open |
| 4 | Bulk command with assignee/milestone support | p1 | Open |
| 5 | Confirmation prompt with --yes flag | p2 | Open |
| 6 | Epic create command | p1 | Open |
| 7 | Epic status command | p2 | Open |
| 8 | Epic add command | p2 | Open |

---

## Closed Issues

(None yet)
