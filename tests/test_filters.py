"""Priority-ordered room detection (CONTEXT.md §6)."""

import pytest

from src.filters import detect_room_for_wing


@pytest.fixture
def rooms():
    return [
        {"name": "auth", "keywords": ["login", "password", "jwt"]},
        {"name": "billing", "keywords": ["stripe", "invoice"]},
        {"name": "general", "keywords": []},
    ]


def test_explicit_rooms_json_blocks_override(tmp_path, rooms):
    (tmp_path / "rooms.json").write_text('{"blocks": {"src/payments/": "billing"}}')
    (tmp_path / "src" / "payments").mkdir(parents=True)
    room = detect_room_for_wing(
        filepath=tmp_path / "src" / "payments" / "stripe.py",
        content="# handle login jwt",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "billing", "explicit block should override keyword score"


def test_path_prefix_wins_over_content(tmp_path, rooms):
    (tmp_path / "src" / "auth").mkdir(parents=True)
    room = detect_room_for_wing(
        filepath=tmp_path / "src" / "auth" / "session.py",
        content="# stripe invoice processing",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "auth", "path-prefix 'auth' should beat keyword 'stripe'"


def test_keyword_scoring_fallback(tmp_path, rooms):
    (tmp_path / "lib").mkdir()
    room = detect_room_for_wing(
        filepath=tmp_path / "lib" / "util.py",
        content="def handle_login(password, jwt): ...",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "auth"


def test_unrouted_falls_through_to_general(tmp_path, rooms):
    (tmp_path / "lib").mkdir()
    room = detect_room_for_wing(
        filepath=tmp_path / "lib" / "util.py",
        content="def hello(): pass",
        wing_root=tmp_path,
        rooms=rooms,
    )
    assert room == "general"
