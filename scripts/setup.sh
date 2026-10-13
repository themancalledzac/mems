#!/bin/bash
# Memory Palace one-shot installer.
# Usage: ./scripts/setup.sh [--yes|-y]
#   --yes / -y   non-interactive: skip repo + IDE prompts, use defaults.
set -e
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ASSUME_YES=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=true ;;
        -h|--help)
            echo "Usage: $0 [--yes|-y]"
            echo "  --yes / -y   skip prompts, use defaults (no repos, no IDE install)"
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

# --- color helpers (degrade gracefully when tput unavailable) ---
if command -v tput >/dev/null 2>&1 && [[ -t 1 ]]; then
    BOLD="$(tput bold || true)"
    DIM="$(tput dim || true)"
    GREEN="$(tput setaf 2 || true)"
    RED="$(tput setaf 1 || true)"
    YELLOW="$(tput setaf 3 || true)"
    BLUE="$(tput setaf 4 || true)"
    RESET="$(tput sgr0 || true)"
else
    BOLD=""; DIM=""; GREEN=""; RED=""; YELLOW=""; BLUE=""; RESET=""
fi

say()   { printf "%s\n" "$*"; }
info()  { printf "%s%s%s\n" "$BLUE" "$*" "$RESET"; }
ok()    { printf "%s✓%s %s\n" "$GREEN" "$RESET" "$*"; }
warn()  { printf "%s!%s %s\n" "$YELLOW" "$RESET" "$*"; }
fail()  { printf "%s✗%s %s\n" "$RED" "$RESET" "$*" >&2; }

banner() {
    printf "\n%s%s=== Memory Palace setup ===%s\n\n" "$BOLD" "$BLUE" "$RESET"
}

prompt() {
    # prompt <message> <default> -> echoes answer
    local msg="$1"
    local default="$2"
    if [[ "$ASSUME_YES" == true ]]; then
        printf "%s\n" "$default"
        return
    fi
    local answer
    read -r -p "$msg " answer || answer=""
    if [[ -z "$answer" ]]; then
        answer="$default"
    fi
    printf "%s\n" "$answer"
}

# --- 1. banner + preflight ---
banner

MISSING=()
command -v docker >/dev/null 2>&1 || MISSING+=("docker")
if ! docker compose version >/dev/null 2>&1; then
    MISSING+=("docker compose")
fi
command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
command -v pip >/dev/null 2>&1 || command -v pip3 >/dev/null 2>&1 || MISSING+=("pip")

if (( ${#MISSING[@]} > 0 )); then
    fail "missing required tools: ${MISSING[*]}"
    say ""
    say "Install hints:"
    say "  macOS:  brew install --cask docker && brew install python"
    say "  Linux:  see https://docs.docker.com/engine/install/ and your package manager for python3"
    exit 1
fi
ok "preflight passed (docker, docker compose, python3)"

# --- 2. config dir (never clobber existing user files) ---
CONFIG_DIR="$HOME/.config/mems"
mkdir -p "$CONFIG_DIR"

USER_YAML="$CONFIG_DIR/mempalace.yaml"
USER_REPOS="$CONFIG_DIR/repos.json"

SKELETON_REPOS_MARKER="example_wing"

if [[ ! -f "$USER_YAML" ]]; then
    if [[ -f "$REPO_ROOT/config/mempalace.yaml" ]]; then
        cp "$REPO_ROOT/config/mempalace.yaml" "$USER_YAML"
        ok "copied mempalace.yaml → $USER_YAML"
    else
        warn "config/mempalace.yaml not found in repo — skipping"
    fi
else
    ok "preserved existing $USER_YAML"
fi

if [[ ! -f "$USER_REPOS" ]]; then
    cat > "$USER_REPOS" <<JSON
{
  "example_wing": {
    "path": "/repos/example",
    "default_hall": "general"
  }
}
JSON
    ok "wrote skeleton repos.json → $USER_REPOS"
else
    ok "preserved existing $USER_REPOS"
fi

# --- 3. host paths (interactive populate of skeleton) ---
IS_SKELETON=false
if grep -q "$SKELETON_REPOS_MARKER" "$USER_REPOS"; then
    IS_SKELETON=true
fi

if [[ "$IS_SKELETON" == true && "$ASSUME_YES" != true ]]; then
    say ""
    info "Configure repos to index"
    say "Enter a comma-separated list of absolute paths to repos you want indexed,"
    say "or type 'skip' to configure later."
    REPO_PATHS=$(prompt "Paths (or 'skip'):" "skip")
    if [[ "$REPO_PATHS" != "skip" && -n "$REPO_PATHS" ]]; then
        python3 - "$USER_REPOS" "$REPO_PATHS" <<'PY'
import json
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
raw = sys.argv[2]

entries = {}
skipped = []
for item in raw.split(","):
    p = item.strip()
    if not p:
        continue
    abs_path = os.path.abspath(os.path.expanduser(p))
    name = Path(abs_path).name.replace(".", "-")
    if not name:
        skipped.append(p)
        continue
    entries[name] = {"path": abs_path, "default_hall": "general"}

if entries:
    target.write_text(json.dumps(entries, indent=2) + "\n")
    print(f"wrote {len(entries)} wing(s) to {target}")
    for name, cfg in entries.items():
        print(f"  {name} → {cfg['path']}")
if skipped:
    print(f"skipped entries: {skipped}")
PY
    else
        warn "skipping repo configuration — edit $USER_REPOS later"
    fi
elif [[ "$IS_SKELETON" == true ]]; then
    warn "repos.json still skeleton — edit $USER_REPOS to add repos"
fi

# --- 4. docker image build ---
say ""
info "Building Docker image (this may take a few minutes on first run)..."
if ! (cd "$REPO_ROOT" && docker compose build); then
    fail "docker compose build failed"
    exit 1
fi
ok "Docker image built"

# --- 5. first boot + health poll ---
say ""
info "Starting container..."
if ! docker volume inspect memory_mempalace-data >/dev/null 2>&1; then
    docker volume create memory_mempalace-data >/dev/null || { fail "docker volume create failed"; exit 1; }
    ok "created palace volume memory_mempalace-data"
fi
if ! (cd "$REPO_ROOT" && docker compose up -d); then
    fail "docker compose up -d failed"
    exit 1
fi

info "Waiting for http://localhost:8787/health ..."
HEALTH_URL="http://localhost:8787/health"
LAST_ERR=""
HEALTHY=false
for i in $(seq 1 20); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    LAST_ERR=$(curl -sS -o /dev/null -w "HTTP %{http_code}" "$HEALTH_URL" 2>&1 || true)
    sleep 3
done

if [[ "$HEALTHY" == true ]]; then
    ok "service healthy at $HEALTH_URL"
else
    fail "service did not become healthy (last: $LAST_ERR)"
    say "    try: docker compose logs --tail=50"
    # don't bail here — user can still install CLI and retry
fi

# --- 6. install CLI ---
say ""
info "Installing mems CLI (pip install --user -e .)..."
PIP_BIN="pip3"
command -v pip3 >/dev/null 2>&1 || PIP_BIN="pip"
if ! (cd "$REPO_ROOT" && "$PIP_BIN" install --user -e .); then
    fail "pip install --user -e . failed"
    exit 1
fi
ok "mems CLI installed"

USER_BASE="$(python3 -m site --user-base 2>/dev/null || true)"
USER_BIN="${USER_BASE}/bin"
if [[ -n "$USER_BASE" && ":$PATH:" != *":$USER_BIN:"* ]]; then
    warn "$USER_BIN is not on your PATH"
    say "    add to your shell rc:  export PATH=\"\$PATH:$USER_BIN\""
fi

# --- 7. IDE integration prompt ---
say ""
INSTALL_IDE=$(prompt "Install Cursor/Codex config now? [y/N]" "n")
case "$INSTALL_IDE" in
    y|Y|yes|YES)
        if [[ -x "$SCRIPT_DIR/install_cursor.sh" ]]; then
            info "Installing Cursor integration..."
            "$SCRIPT_DIR/install_cursor.sh" || warn "install_cursor.sh reported issues"
        else
            warn "install_cursor.sh not executable — skipping"
        fi
        if [[ -x "$SCRIPT_DIR/install_codex.sh" ]]; then
            info "Installing Codex integration..."
            "$SCRIPT_DIR/install_codex.sh" || warn "install_codex.sh reported issues"
        else
            warn "install_codex.sh not executable — skipping"
        fi
        ;;
    *)
        say "skipping IDE install (run scripts/install_cursor.sh or scripts/install_codex.sh later)"
        ;;
esac

# --- 8. done banner ---
say ""
printf "%s%s=== setup complete ===%s\n" "$BOLD" "$GREEN" "$RESET"
say ""
say "Next steps:"
say "  ${BOLD}mems status${RESET}                          — verify the service"
say "  ${BOLD}mems repo add <name> <path>${RESET}         — register another repo"
say "  ${BOLD}mems search \"<query>\"${RESET}               — try a semantic search"
say ""
say "Troubleshooting: see docs/TROUBLESHOOTING.md (coming in Phase 9)"
say ""
