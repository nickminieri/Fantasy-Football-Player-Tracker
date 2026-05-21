"""End-to-end pipeline test with all network calls stubbed out."""
from fftracker import espn, sleeper
from fftracker.config import Config
from fftracker.db import Database
from fftracker.espn import Article
from fftracker.report import build_report
from fftracker.tracker import Tracker

ALL_PLAYERS = {
    "100": {"full_name": "Bijan Robinson", "team": "ATL", "position": "RB",
            "depth_chart_order": 1, "age": 24, "years_exp": 2, "espn_id": 4430807,
            "injury_status": None},
    "200": {"full_name": "Drake London", "team": "ATL", "position": "WR",
            "depth_chart_order": 1, "age": 23, "years_exp": 2, "espn_id": 4426502,
            "injury_status": None},
    "999": {"full_name": "Bench Guy", "team": "FA", "position": "WR"},
}


def _stub_network(monkeypatch):
    monkeypatch.setattr(sleeper, "get_user_id", lambda u: "user1")
    monkeypatch.setattr(sleeper, "get_all_players", lambda: ALL_PLAYERS)
    monkeypatch.setattr(sleeper, "get_league_rosters",
                        lambda lid: [{"owner_id": "user1", "players": ["100", "200"]}])
    monkeypatch.setattr(
        espn, "get_player_news",
        lambda espn_id, session=None: [
            Article("Big news", "something happened", f"https://e/{espn_id}",
                    "2026-01-01T00:00:00Z")
        ],
    )


def test_full_run(tmp_path, monkeypatch):
    _stub_network(monkeypatch)
    cfg = Config(sleeper_username="me", sleeper_league_id="L1",
                 db_path=tmp_path / "i.db")
    db = Database(cfg.db_path)
    tracker = Tracker(cfg, db)

    # First sync: snapshots roster, no change alerts.
    assert tracker.sync() == []
    tracked = db.tracked_players()
    assert {p["player_id"] for p in tracked} == {"100", "200"}

    # News gathered for both rostered players.
    news_alerts = tracker.gather_news()
    assert len(news_alerts) == 2

    # Re-running news yields nothing new (dedupe works).
    assert tracker.gather_news() == []

    # An injury appears -> change alert on next sync.
    ALL_PLAYERS["100"] = {**ALL_PLAYERS["100"], "injury_status": "Questionable"}
    alerts = tracker.sync()
    assert any(a.category == "injury" and a.player_name == "Bijan Robinson"
               for a in alerts)

    report = build_report(db)
    assert "Bijan Robinson" in report and "Drake London" in report
    db.close()


def test_ambiguous_league_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sleeper, "get_user_id", lambda u: "user1")
    monkeypatch.setattr(sleeper, "get_user_leagues", lambda uid, season: [
        sleeper.League("A", "League A", season, 12),
        sleeper.League("B", "League B", season, 10),
    ])
    cfg = Config(sleeper_username="me", db_path=tmp_path / "i2.db")  # no league_id
    db = Database(cfg.db_path)
    tracker = Tracker(cfg, db)
    try:
        import pytest
        with pytest.raises(RuntimeError, match="multiple leagues"):
            tracker.sync()
    finally:
        db.close()
