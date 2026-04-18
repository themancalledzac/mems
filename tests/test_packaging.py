"""Sanity checks for package configuration."""

import importlib.metadata
import subprocess
import sys

import pytest


@pytest.mark.xfail(reason="mems_cli not yet implemented — see Phase 6")
def test_console_script_installed():
    """`mems` console script resolves to mems_cli.main:main."""
    entry_points = importlib.metadata.entry_points(group="console_scripts")
    mems_ep = next((ep for ep in entry_points if ep.name == "mems"), None)
    assert mems_ep is not None, "mems console script not registered"
    assert mems_ep.value == "mems_cli.main:main"


@pytest.mark.xfail(reason="mems_cli not yet implemented — see Phase 6")
def test_package_imports():
    """Both src and mems_cli are importable."""
    subprocess.check_call([sys.executable, "-c", "import src; import mems_cli"])
