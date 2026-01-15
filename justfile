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

# --- Package Publishing ---

# Gitea PyPI registry configuration
REGISTRY := "gitea-pypi"
GITEA_HOST := "prod-vm-gitea.internal.kellgari.com.au"
GITEA_ORG := "homelab-teams"
CA_BUNDLE := "/etc/ssl/certs/ca-certificates.crt"

# One-time setup: configure Poetry repository for Gitea PyPI
setup-publish:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Configuring Poetry repository..."
    poetry config repositories.{{REGISTRY}} \
        https://{{GITEA_HOST}}/api/packages/{{GITEA_ORG}}/pypi
    echo ""
    echo "Repository configured: {{REGISTRY}}"
    echo ""
    echo "Now configure credentials (choose one):"
    echo ""
    echo "Option A - Environment variables (recommended):"
    echo "  export POETRY_HTTP_BASIC_GITEA_PYPI_USERNAME=<your-gitea-username>"
    echo "  export POETRY_HTTP_BASIC_GITEA_PYPI_PASSWORD=<your-gitea-token>"
    echo ""
    echo "Option B - Global config (stored in ~/.config/pypoetry/auth.toml):"
    echo "  poetry config http-basic.{{REGISTRY}} <username> <token>"
    echo ""
    echo "Get token from: https://{{GITEA_HOST}}/user/settings/applications"
    echo "Select scope: 'package' (write:package)"

# Build wheel and sdist
build:
    poetry build

# Publish to Gitea PyPI registry (run 'just build' first)
publish: build
    REQUESTS_CA_BUNDLE={{CA_BUNDLE}} poetry publish -r {{REGISTRY}}

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
