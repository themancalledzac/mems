"""Map host file paths to palace wings for the Claude Code hooks.

Registered repos come from `$MEMORY_CONFIG_DIR/repos.json` (default
`~/.config/mems/repos.json`). Paths outside every registered root fall back to
git: the main checkout behind a worktree, then the clone's origin. Stdlib only;
every git call has a 1 s timeout and failure means "no wing".
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from functools import lru_cache
from pathlib import Path

CONFIG_ENV = "MEMORY_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "~/.config/mems"
GIT_TIMEOUT_SECONDS = 1.0

_SEGMENT_TOKENS = {";", "&&", "||", "|", "&", "(", ")", "|&"}
_IGNORED_PREFIXES = ("/dev/",)


def _normalize(path: str, cwd: str | None = None) -> str:
    expanded = os.path.expanduser(path)
    if cwd and not os.path.isabs(expanded):
        expanded = os.path.join(os.path.expanduser(cwd), expanded)
    return os.path.normpath(os.path.abspath(expanded))


def load_repo_roots() -> list[tuple[str, str]]:
    """Return (host_root, wing) pairs from repos.json, longest root first.

    A missing or malformed file yields an empty list.
    """
    config_dir = os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG_DIR
    try:
        data = json.loads((Path(config_dir).expanduser() / "repos.json").read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    roots = []
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        wing = entry.get("wing") or key
        if isinstance(path, str) and path and isinstance(wing, str):
            roots.append((_normalize(path), wing))
    roots.sort(key=lambda pair: len(pair[0]), reverse=True)
    return roots


def _prefix_match(path: str, roots: list[tuple[str, str]]) -> str | None:
    for root, wing in roots:
        if path == root or path.startswith(root.rstrip(os.sep) + os.sep):
            return wing
    return None


def _basename_match(name: str, roots: list[tuple[str, str]]) -> str | None:
    for root, wing in roots:
        if name and os.path.basename(root) == name:
            return wing
    return None


def _nearest_dir(path: str) -> str | None:
    current = path
    while current and not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return current or None


@lru_cache(maxsize=64)
def _git_common_dir(directory: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _origin_url(common_dir: str) -> str | None:
    try:
        lines = (Path(common_dir) / "config").read_text(errors="replace").splitlines()
    except OSError:
        return None
    in_origin = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.replace(" ", "") == '[remote"origin"]'
            continue
        if in_origin and "=" in stripped:
            key, value = stripped.split("=", 1)
            if key.strip() == "url":
                return value.strip() or None
    return None


def _wing_for_origin(url: str, roots: list[tuple[str, str]]) -> str | None:
    local = url[len("file://") :] if url.startswith("file://") else url
    if local.startswith(("/", "~")):
        return _prefix_match(_normalize(local), roots)
    stem = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if stem.endswith(".git"):
        stem = stem[: -len(".git")]
    return _basename_match(stem, roots)


def _wing_from_git(target: str, roots: list[tuple[str, str]]) -> str | None:
    directory = _nearest_dir(target)
    if directory is None:
        return None
    common_dir = _git_common_dir(directory)
    if not common_dir:
        return None
    checkout = os.path.dirname(os.path.normpath(common_dir))
    wing = _prefix_match(checkout, roots) or _basename_match(os.path.basename(checkout), roots)
    if wing:
        return wing
    url = _origin_url(common_dir)
    return _wing_for_origin(url, roots) if url else None


def wing_for_path(path: str) -> str | None:
    """Return the wing whose repo holds `path`, or None.

    Tries registered roots first, then the git common dir's parent (worktrees),
    then the origin URL (clones such as `~/.cache/orch*`).
    """
    if not path:
        return None
    roots = load_repo_roots()
    if not roots:
        return None
    target = _normalize(path)
    return _prefix_match(target, roots) or _wing_from_git(target, roots)


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def _is_redirect(token: str) -> bool:
    return bool(token) and set(token) <= set("<>&") and ("<" in token or ">" in token)


def _bash_targets(command: str, cwd: str) -> list[str]:
    targets = []
    current = cwd
    segment_start = True
    skip_next = False
    pending_cd = False
    for token in _shell_tokens(command):
        if token in _SEGMENT_TOKENS:
            segment_start = True
            pending_cd = False
            continue
        if _is_redirect(token):
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        if segment_start:
            if "=" in token and not token.startswith(("/", ".", "~")):
                continue
            segment_start = False
            pending_cd = token == "cd"
            continue
        if token.startswith("-"):
            continue
        if not token.startswith(("/", "~", ".")) and "/" not in token:
            continue
        resolved = _normalize(token, current)
        if pending_cd:
            current = resolved
            pending_cd = False
        if resolved.startswith(_IGNORED_PREFIXES) or resolved == "/dev/null":
            continue
        targets.append(resolved)
    return targets or [_normalize(current)]


def target_paths(tool_name: str, tool_input: dict, cwd: str) -> list[str]:
    """Return the absolute paths a filesystem tool call looks at.

    Relative paths resolve against `cwd`, or against a preceding `cd` in Bash.
    A Bash command with no path arguments targets its working directory.
    """
    tool_input = tool_input or {}
    cwd = cwd or os.getcwd()
    if tool_name == "Read":
        path = tool_input.get("file_path")
        return [_normalize(path, cwd)] if isinstance(path, str) and path else []
    if tool_name in {"Grep", "Glob"}:
        path = tool_input.get("path")
        return [_normalize(path if isinstance(path, str) and path else cwd, cwd)]
    if tool_name == "Bash":
        command = tool_input.get("command")
        return _bash_targets(command, cwd) if isinstance(command, str) and command else []
    return []


def first_wing(paths: list[str]) -> str | None:
    """Return the wing of the first path under a registered root.

    If none matches, only the first path gets the git fallback, so one hook call
    runs at most one git process.
    """
    roots = load_repo_roots()
    targets = [_normalize(path) for path in paths if path]
    if not roots or not targets:
        return None
    for target in targets:
        wing = _prefix_match(target, roots)
        if wing:
            return wing
    return _wing_from_git(targets[0], roots)
