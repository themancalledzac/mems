"""Verify entrypoint.sh dispatches CLI args instead of swallowing them.

Regression test for the 2026-05 backfill bug: ``ENTRYPOINT ["./entrypoint.sh"]``
used to unconditionally ``exec python -m src.mcp_http_server`` and ignore any
positional args, so ``docker run <image> mempalace mine ...`` silently spun up
an idle server instead of running the CLI. The fix: no args -> boot the server;
any args -> exec them directly, after env setup but before the boot flow.

We run the real entrypoint.sh under a fake PATH where ``mempalace`` and
``python`` are stubs that just echo, so the test exercises control flow only
(which branch runs) without a real interpreter or a long-running server.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO / "entrypoint.sh"


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(0o755)


def _bindir_with_stubs(tmp_path: Path) -> Path:
    """A bin dir (to put first on PATH) with fake ``mempalace`` and ``python``."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Fake CLI: prove it ran, and echo the palace env it inherited.
    _stub(
        bindir / "mempalace",
        'echo "MEMPALACE_CLI_RAN args=[$*] palace=[${MEMPALACE_PALACE_PATH:-UNSET}]"',
    )
    # Fake python: stands in for every ``python <<heredoc`` boot step AND the
    # final ``exec python -m src.mcp_http_server`` so the boot flow can run
    # without a real interpreter or a real server.
    _stub(bindir / "python", 'echo "PYTHON_RAN args=[$*]"; exit 0')
    return bindir


def _run(args, tmp_path):
    bindir = _bindir_with_stubs(tmp_path)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "PALACE_PATH": str(tmp_path / "palace"),
        "EXPORTS_PATH": str(tmp_path / "exports"),
        "CONFIG_PATH": str(tmp_path / "config"),
    }
    return subprocess.run(
        ["bash", str(ENTRYPOINT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_cli_args_dispatched_not_swallowed(tmp_path):
    result = _run(["mempalace", "mine", "/claude_projects", "--wing", "w"], tmp_path)

    assert result.returncode == 0, result.stderr
    # The CLI ran with our args...
    assert "MEMPALACE_CLI_RAN args=[mine /claude_projects --wing w]" in result.stdout
    # ...and the server-boot flow was skipped entirely.
    assert "Memory Palace starting" not in result.stdout
    assert "PYTHON_RAN" not in result.stdout


def test_cli_inherits_aligned_palace_env(tmp_path):
    """A dispatched ``mempalace`` sees MEMPALACE_PALACE_PATH aligned to
    PALACE_PATH, so ``docker run <image> mempalace ...`` hits the mounted palace
    without an explicit ``-e MEMPALACE_PALACE_PATH`` override."""
    result = _run(["mempalace", "status"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert f"palace=[{tmp_path / 'palace'}]" in result.stdout


def test_no_args_boots_server(tmp_path):
    result = _run([], tmp_path)

    assert result.returncode == 0, result.stderr
    # Banner + boot flow ran...
    assert "Memory Palace starting" in result.stdout
    # ...and we reached the final serve line.
    assert "src.mcp_http_server" in result.stdout
