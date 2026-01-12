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
    rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
