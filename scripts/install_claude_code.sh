#!/bin/bash
# Register Memory Palace Claude Code hooks in ~/.claude/settings.json.
# Four hooks installed idempotently:
#   - PreToolUse: Agent              -> wrapper's pretooluse_agent_orientation.py
#   - PreToolUse: Bash|Grep|Glob|Read -> wrapper's pretooluse_fs_gate.py
#   - Stop                           -> upstream's mempal_save_hook.sh (transcript auto-mine)
#   - PreCompact                     -> upstream's mempal_precompact_hook.sh (emergency save)
# Backs up settings.json to settings.json.bak.<UTC-ts> on first mutation.
#
# Hook paths can be overridden via env vars for testing:
#   HOOK_PRETOOLUSE_CMD, HOOK_FS_GATE_CMD, HOOK_STOP_CMD, HOOK_PRECOMPACT_CMD
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SETTINGS="${HOME}/.claude/settings.json"
PRETOOLUSE="${HOOK_PRETOOLUSE_CMD:-$REPO_ROOT/integration/claude_code/pretooluse_agent_orientation.py}"
FS_GATE="${HOOK_FS_GATE_CMD:-$REPO_ROOT/integration/claude_code/pretooluse_fs_gate.py}"
STOP="${HOOK_STOP_CMD:-${HOME}/Code/mempalace/hooks/mempal_save_hook.sh}"
PRECOMPACT="${HOOK_PRECOMPACT_CMD:-${HOME}/Code/mempalace/hooks/mempal_precompact_hook.sh}"

# Only enforce existence when the caller didn't supply a custom path.
# Custom paths are typically used by tests pointing at stub binaries that
# already exist (e.g. /bin/true), so re-checking them is redundant.
if [[ -z "${HOOK_PRETOOLUSE_CMD:-}" && ! -f "$PRETOOLUSE" ]]; then
    echo "error: missing $PRETOOLUSE" >&2
    exit 1
fi
if [[ -z "${HOOK_FS_GATE_CMD:-}" && ! -f "$FS_GATE" ]]; then
    echo "error: missing $FS_GATE" >&2
    exit 1
fi
if [[ -z "${HOOK_STOP_CMD:-}" && ! -f "$STOP" ]]; then
    echo "error: missing $STOP" >&2
    echo "  install upstream mempalace: git clone https://github.com/MemPalace/mempalace.git $HOME/Code/mempalace" >&2
    exit 1
fi
if [[ -z "${HOOK_PRECOMPACT_CMD:-}" && ! -f "$PRECOMPACT" ]]; then
    echo "error: missing $PRECOMPACT" >&2
    echo "  install upstream mempalace: git clone https://github.com/MemPalace/mempalace.git $HOME/Code/mempalace" >&2
    exit 1
fi

# chmod +x is best-effort; skip if we don't own the file (e.g. test stubs).
for f in "$PRETOOLUSE" "$FS_GATE" "$STOP" "$PRECOMPACT"; do
    if [[ -f "$f" && -w "$f" ]]; then
        chmod +x "$f" 2>/dev/null || true
    fi
done

mkdir -p "$(dirname "$SETTINGS")"

HOOK_PRETOOLUSE_CMD="$PRETOOLUSE" \
HOOK_FS_GATE_CMD="$FS_GATE" \
HOOK_STOP_CMD="$STOP" \
HOOK_PRECOMPACT_CMD="$PRECOMPACT" \
SETTINGS_PATH="$SETTINGS" \
python3 "$REPO_ROOT/integration/claude_code/hooks_install.py"
