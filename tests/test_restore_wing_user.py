"""wing_user restore tests."""

import pytest

from src.restore_wing_user import restore_if_empty
from src.wing_user_snapshot import snapshot_wing_user


@pytest.fixture
def tmp_palace_with_wing_user(tmp_path):
    from src.user_wing import UserWing

    palace = tmp_path / "palace"
    palace.mkdir()
    wing = UserWing(palace_path=str(palace))
    wing.write(hall="frustrations", content="I'm frustrated about X", topic="debugging")
    wing.write(hall="decisions", content="Decision: use Y", topic="architecture")
    return palace


def test_restore_noops_when_non_empty(tmp_palace_with_wing_user, tmp_path):
    exp = tmp_path / "exports"
    snapshot_wing_user(tmp_palace_with_wing_user, exp)
    result = restore_if_empty(tmp_palace_with_wing_user, exp)
    assert result["action"] == "skipped"
    assert "not empty" in result["reason"]


def test_restore_reinserts_when_empty(tmp_palace_with_wing_user, tmp_path):
    exp = tmp_path / "exports"
    snapshot_wing_user(tmp_palace_with_wing_user, exp)

    # Wipe wing_user via the same collection abstraction UserWing / snapshot uses.
    from mempalace.palace import get_collection

    col = get_collection(
        str(tmp_palace_with_wing_user),
        collection_name="mempalace_drawers",
        create=True,
    )
    existing = col.get(where={"wing": "user"})
    col.delete(ids=existing["ids"])

    # Confirm wiped.
    after = col.get(where={"wing": "user"})
    assert after["ids"] == []

    result = restore_if_empty(tmp_palace_with_wing_user, exp)
    assert result["action"] == "restored"
    assert result["drawers_restored"] == 2

    # Confirm drawers actually re-inserted.
    repop = col.get(where={"wing": "user"})
    assert len(repop["ids"]) == 2


def test_restore_noops_when_no_backup(tmp_path):
    palace = tmp_path / "empty_palace"
    palace.mkdir()
    result = restore_if_empty(palace, tmp_path / "empty_exports")
    assert result["action"] == "skipped"


def test_restore_only_touches_user_wing(tmp_path):
    """restore_wing_user must not import or re-upsert non-user-wing drawers.

    General palace recovery is upstream's job (`mempalace repair --mode from-sqlite`,
    added in 3.3.5 #1308). The docstring may *reference* that delegation, but the
    module must not implement it — guard against any code construct that invokes
    from-sqlite mode (kwarg form or CLI flag).
    """
    import ast
    import inspect

    from src import restore_wing_user

    src = inspect.getsource(restore_wing_user)
    # Sanity: the module should reference user_wing/halls.
    assert "wing_user" in src or "user_wing" in src

    # Strip docstrings and comments before checking for from-sqlite invocations,
    # so the delegation note in the module docstring doesn't trip the guard.
    tree = ast.parse(src)
    string_constants = "\n".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )
    code_only = src
    for literal in string_constants.splitlines():
        if literal.strip():
            code_only = code_only.replace(literal, "")

    assert 'mode="from-sqlite"' not in code_only and "--mode from-sqlite" not in code_only, (
        "restore_wing_user should not duplicate mempalace repair --mode from-sqlite logic"
    )
