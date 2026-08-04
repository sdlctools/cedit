#!/usr/bin/env bash
# .jst/bootstrap.sh — per-worktree bootstrap hook. Run by jira-task-executor,
# once per worktree, automatically. See skills/_shared/project-config.md
# § the optional worktree hook for the full contract.
#
# Fail-soft: a non-zero exit is reported by the executor and the run
# continues. Idempotent: safe to re-run in an already-bootstrapped worktree.

set -euo pipefail

cd "${JST_WORKTREE_DIR:-$(git rev-parse --show-toplevel)}"

if [ ! -d venv ]; then
  python3 -m venv venv
fi
venv/bin/pip install -q -r requirements.txt

echo "bootstrap: ready — run tests with 'venv/bin/python3 -m pytest'"
