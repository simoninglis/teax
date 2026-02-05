#!/bin/bash
# CI status for teax - used in tmux status bar
#
# Workflows:
# - ci.yml: Lint, typecheck, test (on push/PR)
# - publish.yml: Manual release workflow
#
# Uses teax --show flag (v0.2.0+) for explicit workflow abbreviations.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR" 2>/dev/null || { echo "CI:?"; exit 0; }

# Get local and remote HEAD
LOCAL_SHA=$(git rev-parse --short HEAD 2>/dev/null) || { echo "CI:?"; exit 0; }
REMOTE_SHA=$(git rev-parse --short origin/main 2>/dev/null) || { echo "CI:?"; exit 0; }

# Workflow display: C=CI, P=Publish
SHOW_PIPELINE="C:ci.yml,P:publish.yml"

get_ci_status() {
    local sha="$1"
    local result
    local exit_code

    result=$(TEAX_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt teax -o tmux runs status -r homelab-teams/teax --sha "$sha" --show "$SHOW_PIPELINE" 2>/dev/null)
    exit_code=$?

    case $exit_code in
        0) echo "$result" ;;           # All passed
        1) echo "$result" ;;           # Some failed (still show status)
        2) echo "$result" ;;           # Running
        3) echo "CI:-" ;;              # No runs
        *) echo "CI:?" ;;              # Error
    esac
}

# Check if local is ahead of remote (unpushed commits)
if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    # Show status for what's actually in CI (remote), with indicator we're ahead
    AHEAD_COUNT=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo "?")
    STATUS=$(get_ci_status "$REMOTE_SHA")
    echo "${STATUS} +${AHEAD_COUNT}"
else
    # Local matches remote, show CI status
    get_ci_status "$LOCAL_SHA"
fi
