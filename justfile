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

# Publish to Gitea PyPI
publish: build
    poetry publish -r gitea

# Release workflow (local): check → bump → commit → tag → publish
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

# --- CI/CD ---

# Trigger CI release workflow (usage: just release-ci patch|minor|major)
release-ci LEVEL:
    #!/usr/bin/env bash
    set -euo pipefail

    # Validate level
    case "{{LEVEL}}" in
        patch|minor|major) ;;
        *) echo "Usage: just release-ci patch|minor|major"; exit 1 ;;
    esac

    # Get token from tea config
    TOKEN=$(grep -A10 'prod-vm-gitea.internal' ~/.config/tea/config.yml | grep token | awk '{print $2}')
    if [ -z "$TOKEN" ]; then
        echo "Error: Could not find Gitea token in tea config"
        exit 1
    fi

    # Check for unpushed commits
    LOCAL_SHA=$(git rev-parse HEAD)
    REMOTE_SHA=$(git rev-parse origin/main 2>/dev/null || echo "")
    if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
        echo "Error: You have unpushed commits. Push first: git push"
        exit 1
    fi

    echo "Triggering publish workflow ({{LEVEL}})..."

    # Write auth header to temp file to avoid token in process args
    HEADER_FILE=$(mktemp)
    chmod 600 "$HEADER_FILE"
    echo "Authorization: token $TOKEN" > "$HEADER_FILE"
    trap "rm -f '$HEADER_FILE'" EXIT

    HTTP_CODE=$(curl -sS -o /tmp/response.txt -w "%{http_code}" \
        --connect-timeout 10 --max-time 30 \
        -X POST \
        -H @"$HEADER_FILE" \
        -H "Content-Type: application/json" \
        -d "{\"ref\": \"main\", \"inputs\": {\"version_level\": \"{{LEVEL}}\"}}" \
        "https://prod-vm-gitea.internal.kellgari.com.au/api/v1/repos/homelab-teams/teax/actions/workflows/publish.yml/dispatches")

    if [ "$HTTP_CODE" -ne 204 ] && [ "$HTTP_CODE" -ne 201 ]; then
        echo "Error: Workflow dispatch failed (HTTP $HTTP_CODE)"
        cat /tmp/response.txt 2>/dev/null || true
        exit 1
    fi

    echo "✓ Publish workflow triggered"
    echo ""
    echo "Monitor progress:"
    echo "  just ci-status"
    echo "  teax runs status -r homelab-teams/teax"

# Show CI status
ci-status:
    @TEAX_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt teax runs status -r homelab-teams/teax
