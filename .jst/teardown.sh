#!/usr/bin/env bash
# .jst/teardown.sh — reverses .jst/bootstrap.sh: removes the venv it created.
# Not run automatically by any jira-sdlc-tools skill; invoke by hand when
# retiring a worktree.

set -euo pipefail

cd "${JST_WORKTREE_DIR:-$(git rev-parse --show-toplevel)}"

rm -rf venv

echo "teardown: venv removed"
