#!/bin/bash
# One-shot backfill of ~/.claude/projects/*.jsonl into the palace as wing_claude_imports.
# Idempotent - mempalace's drawer IDs are deterministic so re-runs are no-ops.
set -euo pipefail

PALACE_PATH="${MEMPALACE_PALACE_PATH:-$HOME/.mempalace/palace}"
SOURCE="${1:-$HOME/.claude/projects}"

echo "Backfilling Claude Code sessions"
echo "  source: $SOURCE"
echo "  palace: $PALACE_PATH"
echo "  wing:   claude_imports"
echo

MEMPALACE_PALACE_PATH="$PALACE_PATH" \
    mempalace mine "$SOURCE" --mode convos --wing claude_imports
