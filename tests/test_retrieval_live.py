"""Live regression check against the committed baseline. Needs MEMS_EVAL_LIVE=1."""

from __future__ import annotations

import os
from argparse import Namespace

import pytest

from mems_cli.commands import eval as eval_cmd

pytestmark = pytest.mark.skipif(
    os.environ.get("MEMS_EVAL_LIVE") != "1", reason="set MEMS_EVAL_LIVE=1 to run"
)


def test_no_regression_against_baseline(capsys):
    if not eval_cmd.DEFAULT_BASELINE.exists():
        pytest.skip("retrieval_baseline.json not committed yet")
    args = Namespace(
        holdout=False,
        wing=None,
        n=10,
        arg=[],
        out=None,
        compare=str(eval_cmd.DEFAULT_BASELINE),
        update_baseline=False,
        allow_drift=False,
        as_json=False,
        corpus=str(eval_cmd.DEFAULT_CORPUS),
    )
    assert eval_cmd.cmd_eval(args) == 0, capsys.readouterr().out
