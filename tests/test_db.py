from fftracker.db import Database
from fftracker.tracker import normalize_player

RAW = {"full_name": "Test Player", "team": "KC", "position": "WR", "espn_id": 123}


def make_db(tmp_path):
    return Database(tmp_path / "t.db")


def test_upsert_and_get(tmp_path):
    db = make_db(tmp_path)
    db.upsert_player(normalize_player("p1", RAW, on_roster=True))
    db.commit()
    row = db.get_player("p1")
    assert row["full_name"] == "Test Player"
    assert row["on_roster"] == 1


def test_upsert_updates_existing(tmp_path):
    db = make_db(tmp_path)
    db.upsert_player(normalize_player("p1", RAW))
    db.commit()
    db.upsert_player(normalize_player("p1", {**RAW, "team": "SF"}))
    db.commit()
    assert db.get_player("p1")["team"] == "SF"


def test_news_dedupe(tmp_path):
    db = make_db(tmp_path)
    args = dict(player_id="p1", source="espn", headline="h", body="b",
                url="http://x", published="2026-01-01", dedupe_key="p1|http://x")
    assert db.add_news(**args) is True
    assert db.add_news(**args) is False  # duplicate rejected
    db.commit()


def test_clear_roster_flags(tmp_path):
    db = make_db(tmp_path)
    db.upsert_player(normalize_player("p1", RAW, on_roster=True))
    db.commit()
    db.clear_roster_flags()
    db.commit()
    assert db.get_player("p1")["on_roster"] == 0


def test_meta_roundtrip(tmp_path):
    db = make_db(tmp_path)
    db.set_meta("league_id", "999")
    assert db.get_meta("league_id") == "999"
    db.set_meta("league_id", "1000")
    assert db.get_meta("league_id") == "1000"


def test_tracked_players_filter(tmp_path):
    db = make_db(tmp_path)
    db.upsert_player(normalize_player("p1", RAW, on_roster=True))
    db.upsert_player(normalize_player("p2", RAW))  # not tracked
    db.commit()
    tracked = db.tracked_players()
    assert {p["player_id"] for p in tracked} == {"p1"}
