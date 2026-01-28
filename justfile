# teax task runner

set shell := ["bash", "-euo", "pipefail", "-c"]

# Default: show available commands
default:
    @just --list

# Install dependencies
install:
    poetry install

# Run tests
test *ARGS:
    poetry run pytest {{ARGS}}

# Run linting
lint:
    poetry run ruff check .

# Run type checking
typecheck:
    poetry run mypy src/

# Format code
format:
    poetry run ruff format .
    poetry run ruff check --fix .

# Run all quality checks
check: lint typecheck test

# Run CLI (development)
run *ARGS:
    poetry run teax {{ARGS}}

# Clean build artifacts
clean:
    rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist/
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Package Building ---

# Build wheel and sdist
build:
    poetry build

# Show current version
version:
    @grep '^version' pyproject.toml | head -1 | cut -d'"' -f2

# Bump version (usage: just bump patch|minor|major)
bump LEVEL:
    #!/usr/bin/env bash
    set -euo pipefail
    current=$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
    IFS='.' read -r major minor patch <<< "$current"
    case "{{LEVEL}}" in
        patch) patch=$((patch + 1)) ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        major) major=$((major + 1)); minor=0; patch=0 ;;
        *) echo "Usage: just bump patch|minor|major"; exit 1 ;;
    esac
    new="${major}.${minor}.${patch}"
    sed -i "s/^version = \"${current}\"/version = \"${new}\"/" pyproject.toml
    echo "Bumped ${current} → ${new}"

# Release workflow: check → bump → commit → tag → publish
release LEVEL: check
    #!/usr/bin/env bash
    set -euo pipefail
    just bump {{LEVEL}}
    new=$(just version)
    git add pyproject.toml
    git commit -m "chore: release v${new}"
    git tag "v${new}"
    just publish
    echo ""
    echo "Released v${new}!"
    echo "Don't forget: git push origin main --tags"
