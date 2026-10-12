#!/usr/bin/env sh
# Apply patches/*.patch to the mempalace installed in a Python environment.
# Run after `uv sync`. Defaults to .venv/bin/python; pass another interpreter as $1.
# Skips a patch that is already applied and fails if one no longer applies.
set -eu
cd "$(dirname "$0")/.."
py="${1:-.venv/bin/python}"
site=$("$py" -c 'import mempalace, os; print(os.path.dirname(os.path.dirname(mempalace.__file__)))')
for p in patches/*.patch; do
    if patch -p1 -R -s -f --dry-run -d "$site" < "$p" > /dev/null 2>&1; then
        echo "already applied: $p"
        continue
    fi
    patch -p1 -N -f -d "$site" < "$p"
done
