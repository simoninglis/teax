# teax Issue Tracker

Canonical issue list for teax development. Primary tracking in Gitea.

**Gitea:** https://prod-vm-gitea.internal.kellgari.com.au/homelab-teams/teax/issues

---

## Open Issues

| Gitea # | Title | Priority | Status |
|---------|-------|----------|--------|
| 21 | Fail closed on HTTP URLs (token over plain HTTP) | CRITICAL | New |
| 22 | Fix version bump automation for metadata-based versioning | IMPORTANT | New |
| 23 | Fix hardcoded version string in CLI test | IMPORTANT | New |
| 24 | Validate parse_repo rejects empty owner/repo segments | IMPORTANT | New |
| 20 | Add --body flag to issue edit command | p2 | Open |
| 19 | Remove unused DependencyRequest model | p3 | Open |
| 17 | Add end-to-end tests for epic commands | p3 | Open |
| 15 | Reduce redundant label fetches in epic_create | p3 | Open |
| 14 | Improve input validation for color and repo | p3 | Open |
| 13 | Deduplicate child issues in epic commands | p3 | Open |
| 12 | Improve pagination efficiency | p3 | Open |
| 9 | Fix base URL subpath handling for non-root Gitea | p1 | Open |

---

### 21. Fail closed on HTTP URLs (token over plain HTTP)

**Status:** New (from codex review 2026-01-15)

**Problem:** `GiteaClient` only emits a warning when the configured base URL is `http://`, but still sends the `Authorization` token over an unencrypted channel. Warnings are easy to miss in scripts/CI.

**Solution:** Fail closed by default (raise `ValueError`) when `http://` is detected, require explicit opt-in via `TEAX_ALLOW_INSECURE_HTTP=1` to proceed.

**Acceptance Criteria:**
- [ ] HTTP URLs raise error by default
- [ ] `TEAX_ALLOW_INSECURE_HTTP=1` allows proceeding with warning
- [ ] Clear error message explaining the risk
- [ ] Tests for both paths

**Files affected:**
- src/teax/api.py

---

### 22. Fix version bump automation for metadata-based versioning

**Status:** New (from codex review 2026-01-15)

**Problem:** `just bump` attempts to rewrite `__version__` in `src/teax/__init__.py`, but that file now uses `importlib.metadata.version()`. The bump script silently fails.

**Solution:** Update `justfile` bump recipe to only update `pyproject.toml` (via `poetry version`), remove the sed command that edits `__init__.py`.

**Acceptance Criteria:**
- [ ] `just bump patch` correctly bumps version
- [ ] README documentation updated
- [ ] No attempt to edit `__init__.py`

**Files affected:**
- justfile
- README.md

---

### 23. Fix hardcoded version string in CLI test

**Status:** New (from codex review 2026-01-15)

**Problem:** `test_main_version` asserts `"0.1.0"` appears in output, but version is now `0.1.2` and dynamic. Test breaks on version bumps.

**Solution:** Assert output matches SemVer regex or compare against `importlib.metadata.version("teax")`.

**Acceptance Criteria:**
- [ ] Test passes regardless of current version
- [ ] Validates version format is valid SemVer

**Files affected:**
- tests/test_cli.py

---

### 24. Validate parse_repo rejects empty owner/repo segments

**Status:** New (from codex review 2026-01-15)

**Problem:** Inputs like `"owner/"` or `"/repo"` pass validation and return empty strings, causing confusing API errors.

**Solution:** Validate both segments are non-empty after splitting.

**Acceptance Criteria:**
- [ ] `parse_repo("owner/")` raises BadParameter
- [ ] `parse_repo("/repo")` raises BadParameter
- [ ] Tests added for edge cases

**Files affected:**
- src/teax/cli.py
- tests/test_cli.py

---

### 20. Add --body flag to issue edit command

**Status:** Open

**Problem:** The `teax issue edit` command is missing the `--body` flag. The API already supports this.

**Solution:** Add `--body` option to `issue_edit` command in `cli.py`.

**Acceptance Criteria:**
- [ ] `teax issue edit 25 --repo o/r --body "text"` updates body
- [ ] Tests added

**Files affected:**
- src/teax/cli.py
- tests/test_cli.py

---

### 19. Remove unused DependencyRequest model

**Status:** Open

**Problem:** `DependencyRequest` in models.py is defined but never used.

**Solution:** Remove the unused model.

**Acceptance Criteria:**
- [ ] DependencyRequest removed
- [ ] Tests still pass

**Files affected:**
- src/teax/models.py

---

## Closed Issues

### Recently Closed

| Gitea # | Title | Resolution |
|---------|-------|------------|
| 18 | Implement milestone lookup by name | Implemented with caching |
| 16 | Increase CLI test coverage to 80% | **Achieved 96%** |
| 11 | Use SecretStr for token | Implemented |
| 10 | Pre-validate milestone in bulk command | Implemented |

### Phase 2 Features (Gitea #1-#8) - COMPLETED

| Gitea # | Title |
|---------|-------|
| 1-8 | Bulk operations and epic helpers |

### Phase 1 Bug Fixes - COMPLETED

| # | Title |
|---|-------|
| Various | API coverage, CSV escaping, validation fixes |

---

## Nice-to-Have (Not Yet in Gitea)

These items identified in codex review may be added as issues later:

- **Base URL whitespace trimming**: `_normalize_base_url()` should `strip()` whitespace
- **Model field normalization**: Coerce `None -> []` for list fields in Pydantic validators
- **Cache key collision prevention**: Use tuple keys `(owner, repo)` instead of f-string
- **Environment-dependent test fix**: `test_epic_create_valid_colors` needs `mock_client`
- **Truncation warning tests**: Add tests for pagination `max_pages` truncation paths
- **Dependency vulnerability scanning**: Add `just audit` using pip-audit
