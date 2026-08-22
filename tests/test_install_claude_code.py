"""Verify install_claude_code.sh wires all four hooks idempotently.

The install script defaults the Stop/PreCompact paths to
``$HOME/Code/mempalace/hooks/mempal_{save,precompact}_hook.sh`` and the
PreToolUse path to the wrapper repo's bundled orientation script. Those files
don't exist under the test's fake ``$HOME``, so we point each hook at an
existing stub binary via the ``HOOK_*_CMD`` env-var overrides documented at the
top of the install script.
"""

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_claude_code.sh"

# Use /bin/true as a stub: it exists on every macOS/Linux box and the install
# script only needs the path to exist; it never executes the hook itself.
STUB_HOOK = "/bin/true"


def _test_env(fake_home: Path) -> dict:
    return {
        "HOME": str(fake_home),
        "PATH": "/usr/bin:/bin",
        "HOOK_PRETOOLUSE_CMD": STUB_HOOK,
        "HOOK_FS_GATE_CMD": STUB_HOOK,
        "HOOK_STOP_CMD": STUB_HOOK,
        "HOOK_PRECOMPACT_CMD": STUB_HOOK,
    }


def _pretooluse_matchers(settings: dict) -> set[str]:
    return {
        entry.get("matcher")
        for entry in settings.get("hooks", {}).get("PreToolUse", [])
        if isinstance(entry, dict)
    }


def test_script_installs_all_four_hooks(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=_test_env(fake_home),
    )
    assert result.returncode == 0, result.stderr

    settings = json.loads((fake_home / ".claude" / "settings.json").read_text())
    hook_names = set(settings.get("hooks", {}).keys())
    assert {"PreToolUse", "Stop", "PreCompact"}.issubset(hook_names)

    # Two distinct PreToolUse gates: subagent dispatch and parent-loop filesystem.
    assert {"Agent", "Bash|Grep|Glob|Read"}.issubset(_pretooluse_matchers(settings))


def test_fs_gate_hook_is_registered_with_real_path(tmp_path):
    """Without an override, the fs-gate must point at the bundled script."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    env = _test_env(fake_home)
    del env["HOOK_FS_GATE_CMD"]
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True)

    settings = json.loads((fake_home / ".claude" / "settings.json").read_text())
    commands = [
        hook.get("command", "")
        for entry in settings["hooks"]["PreToolUse"]
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
    ]
    assert any(c.endswith("pretooluse_fs_gate.py") for c in commands)


def test_script_is_idempotent(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()

    env = _test_env(fake_home)
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True)
    first = (fake_home / ".claude" / "settings.json").read_text()

    subprocess.run(["bash", str(SCRIPT)], env=env, check=True)
    second = (fake_home / ".claude" / "settings.json").read_text()

    assert first == second, "second run mutated settings.json"
