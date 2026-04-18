"""wing_user snapshot tests."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.wing_user_snapshot import prune_snapshots, snapshot_wing_user


@pytest.fixture
def tmp_palace_with_wing_user(tmp_path):
    """A palace with wing_user seeded with 2 drawers.

    Uses UserWing (same abstraction used elsewhere) to stay in lockstep with mempalace.
    """
    from src.user_wing import UserWing

    palace = tmp_path / "palace"
    palace.mkdir()
    wing = UserWing(palace_path=str(palace))
    wing.write(hall="frustrations", content="I'm frustrated about X", topic="debugging")
    wing.write(hall="decisions", content="Decision: use Y", topic="architecture")
    return palace


def test_snapshot_writes_dated_json(tmp_palace_with_wing_user, tmp_path):
    export_dir = tmp_path / "exports"
    out = snapshot_wing_user(palace_path=tmp_palace_with_wing_user, exports_dir=export_dir)
    assert out.exists()
    data = json.loads(out.read_text())
    assert "drawers" in data
    assert "captured_at" in data
    assert data["drawer_count"] >= 2


def test_snapshot_is_idempotent_per_day(tmp_palace_with_wing_user, tmp_path):
    export_dir = tmp_path / "exports"
    out1 = snapshot_wing_user(tmp_palace_with_wing_user, export_dir)
    out2 = snapshot_wing_user(tmp_palace_with_wing_user, export_dir)
    assert out1 == out2  # same dated filename


def test_prune_keeps_recent(tmp_path):
    exp = tmp_path / "exports"
    exp.mkdir()
    now = datetime.now(timezone.utc)
    for i in range(10):
        ts = (now - timedelta(days=i)).strftime("%Y%m%d")
        p = exp / f"wing_user_backup_{ts}.json"
        p.write_text("{}")
    prune_snapshots(exp, retention_days=3)
    remaining = sorted(exp.glob("wing_user_backup_*.json"))
    # retention_days=3 should keep today, today-1, today-2 -> 3 files
    assert len(remaining) == 3
