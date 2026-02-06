# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.6] - 2026-02-06

### Fixed

- Milestones without `start_date:` in description now return `planned` instead of `in_progress` (#38)
- `sprint status` now uses milestone-based detection per ADR-0017 instead of label-based detection (#39)

## [0.6.5] - 2026-02-06

### Fixed

- Milestone lifecycle state now parses `start_date:` from description per ADR-0017 (anchored to line start)

## [0.6.4] - 2026-02-06

### Fixed

- Type hint for Milestone `normalize_empty_timestamp` validator now correctly accepts `str|datetime|None`
- Handle naive datetimes in `_get_milestone_lifecycle_state` to prevent crash if Gitea returns timestamps without timezone info

## [0.6.3] - 2026-02-06

### Fixed

- Use consistent first-match for duplicate sprint milestones in `sprint_status` (was keeping last match, now matches `sprint_issues` behaviour)

## [0.6.2] - 2026-02-06

### Added

- `sprint status` now shows milestone lifecycle state (in_progress/planned/completed) next to current sprint
- `sprint status` lists planned sprints with their milestone states
- `sprint issues N` shows header with milestone state and due date when milestone exists

## [0.6.1] - 2026-02-06

### Fixed

- Normalize timezone in milestone state comparison to handle server timezone differences

## [0.6.0] - 2026-02-06

### Added

- **Milestone commands** for sprint lifecycle tracking (ADR-0017):
  - `milestone list` - List milestones with state filter
  - `milestone create` - Create milestone with `--if-not-exists` support
  - `milestone close` - Close a milestone
  - `milestone open` - Reopen a closed milestone
  - `milestone edit` - Edit title/description/due-date
  - `milestone state` - Get lifecycle state (completed/in_progress/planned/not_found)
  - `milestone current` - Get current in-progress sprint
- API methods: `create_milestone()`, `update_milestone()`
- Extended Milestone model with description, open_issues, closed_issues, due_on, created_at, updated_at, closed_at fields
- Unicode bidi control character neutralization in `_ESC_PATTERN` for visual spoofing prevention

### Fixed

- `milestone create --if-not-exists` now catches both ValueError and HTTPStatusError for numeric titles

## [0.5.0] - 2026-02-05

### Added

- `token create` command for API token management
- SSL cert bundle support for poetry publish

## [0.4.1] - 2026-01-16

### Fixed

- Security and UX improvements from codex A-grade review

## [0.4.0] - 2026-01-16

### Added

- `issue close` command
- `issue reopen` command
- `issue create` command
- CI/CD workflows and issue comment CRUD

## [0.3.0] - 2026-01-15

### Added

- Sprint management commands (`sprint status`, `sprint ready`, `sprint issues`, `sprint plan`)

## [0.2.0] - 2026-01-14

### Added

- `--show` flag for explicit workflow specification in `runs status`
- Animated spinner for running workflows in tmux output

## [0.1.0] - 2026-01-12

### Added

- Initial release
- Issue dependency management (`deps list`, `deps add`, `deps rm`)
- Issue editing (`issue edit`, `issue labels`, `issue bulk`)
- Epic management (`epic create`, `epic status`, `epic add`)
- Label ensure command
- Runner management commands
- Workflow runs commands
- Secrets and variables management
- Package management commands

[Unreleased]: https://github.com/simoninglis/teax/compare/v0.6.6...HEAD
[0.6.6]: https://github.com/simoninglis/teax/compare/v0.6.5...v0.6.6
[0.6.5]: https://github.com/simoninglis/teax/compare/v0.6.4...v0.6.5
[0.6.4]: https://github.com/simoninglis/teax/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/simoninglis/teax/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/simoninglis/teax/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/simoninglis/teax/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/simoninglis/teax/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/simoninglis/teax/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/simoninglis/teax/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/simoninglis/teax/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/simoninglis/teax/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/simoninglis/teax/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/simoninglis/teax/releases/tag/v0.1.0
