from fftracker.config import Config
from fftracker.tracker import detect_changes, normalize_player

RAW = {
    "first_name": "Bijan",
    "last_name": "Robinson",
    "full_name": "Bijan Robinson",
    "team": "ATL",
    "position": "RB",
    "age": 24,
    "years_exp": 2,
    "status": "Active",
    "injury_status": None,
    "depth_chart_order": 1,
    "espn_id": 4430807,
    "news_updated": 1700000000000,
}


def test_normalize_basic():
    p = normalize_player("1", RAW, on_roster=True)
    assert p["full_name"] == "Bijan Robinson"
    assert p["espn_id"] == "4430807"  # coerced to str
    assert p["on_roster"] == 1
    assert p["on_watchlist"] == 0


def test_normalize_fallback_name():
    p = normalize_player("99", {"first_name": "Jane", "last_name": "Doe"})
    assert p["full_name"] == "Jane Doe"


def test_first_sighting_no_alert():
    new = normalize_player("1", RAW)
    assert detect_changes(None, new, Config()) == []


def test_injury_change_alerts():
    old = normalize_player("1", RAW)
    new = normalize_player("1", {**RAW, "injury_status": "Questionable",
                                 "injury_notes": "ankle"})
    alerts = detect_changes(old, new, Config())
    assert len(alerts) == 1
    assert alerts[0].category == "injury"
    assert "Healthy" in alerts[0].title and "Questionable" in alerts[0].title
    assert alerts[0].detail == "ankle"


def test_team_change_alerts():
    old = normalize_player("1", RAW)
    new = normalize_player("1", {**RAW, "team": "WAS"})
    alerts = detect_changes(old, new, Config())
    assert any(a.category == "team" for a in alerts)
    assert "ATL → WAS" in [a.title for a in alerts][0]


def test_depth_chart_move_up():
    old = normalize_player("1", {**RAW, "depth_chart_order": 2})
    new = normalize_player("1", {**RAW, "depth_chart_order": 1})
    alerts = detect_changes(old, new, Config())
    depth = [a for a in alerts if a.category == "depth_chart"]
    assert depth and "moved up" in depth[0].title


def test_alert_toggles_off():
    cfg = Config(alert_injuries=False)
    old = normalize_player("1", RAW)
    new = normalize_player("1", {**RAW, "injury_status": "Out"})
    assert detect_changes(old, new, cfg) == []
