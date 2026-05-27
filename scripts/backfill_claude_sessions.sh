#!/bin/bash
# One-shot backfill of ~/.claude/projects/*.jsonl into the palace as
# wing_claude_imports. Idempotent — mempalace's drawer IDs are deterministic,
# so re-runs are no-ops.
#
# Runs `mempalace mine` inside the wrapper's docker image. We override the
# ENTRYPOINT because entrypoint.sh unconditionally launches the MCP server
# and ignores positional args.
#
# Usage:
#   bash scripts/backfill_claude_sessions.sh                              # default source: ~/.claude/projects
#   bash scripts/backfill_claude_sessions.sh /path/to/jsonl/dir           # custom source
#   PALACE_VOLUME=other_vol IMAGE=other-img bash scripts/backfill_...sh   # override volume/image
#
# Note: this writes to the same chromadb-backed palace the production
# `mempalace` container uses. ChromaDB's SQLite layer serializes writes,
# so running this alongside a busy production server is safe for the data
# but may briefly slow MCP responses. For a quiet run, stop the production
# container first: `docker compose stop mempalace`.
set -euo pipefail

SOURCE="${1:-$HOME/.claude/projects}"
PALACE_VOLUME="${PALACE_VOLUME:-memory_mempalace-data}"
IMAGE="${IMAGE:-memory-mempalace}"

if [ ! -d "$SOURCE" ]; then
    echo "error: source dir does not exist: $SOURCE" >&2
    exit 1
fi

echo "Backfilling Claude Code sessions into wing_claude_imports"
echo "  source: $SOURCE"
echo "  volume: $PALACE_VOLUME"
echo "  image:  $IMAGE"
echo

docker run --rm \
    --entrypoint mempalace \
    -v "$PALACE_VOLUME:/data" \
    -v "$SOURCE:/claude_projects:ro" \
    -e MEMPALACE_PALACE_PATH=/data/palace \
    "$IMAGE" \
    mine /claude_projects --mode convos --wing claude_imports
