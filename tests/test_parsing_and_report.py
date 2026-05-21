from fftracker.db import Database
from fftracker.espn import _parse_articles
from fftracker.report import build_report, format_alert
from fftracker.telegram import _chunk, escape
from fftracker.tracker import Alert, normalize_player

ESPN_PAYLOAD = {
    "articles": [
        {
            "headline": "Robinson logs full practice",
            "description": "RB Bijan Robinson (ankle) was a full participant.",
            "published": "2026-01-02T12:00:00Z",
            "type": "Story",
            "links": {"web": {"href": "https://espn.com/story/1"}},
        },
        {  # media items are skipped
            "headline": "Highlights",
            "type": "Media",
            "links": {"web": {"href": "https://espn.com/video/2"}},
        },
    ]
}


def test_parse_articles_skips_media():
    arts = _parse_articles(ESPN_PAYLOAD)
    assert len(arts) == 1
    assert arts[0].url == "https://espn.com/story/1"
    assert arts[0].dedupe_key() == "https://espn.com/story/1"


def test_parse_articles_empty():
    assert _parse_articles(None) == []
    assert _parse_articles({}) == []


def test_telegram_escape():
    assert escape("a & b <c>") == "a &amp; b &lt;c&gt;"


def test_telegram_chunk_long():
    text = "\n".join(f"line {i}" for i in range(2000))
    chunks = _chunk(text, size=4096)
    assert len(chunks) > 1
    assert all(len(c) <= 4096 for c in chunks)


def test_format_alert_news():
    a = Alert("1", "Bijan Robinson", "news", "Full practice",
              detail="ankle", url="https://espn.com/1")
    out = format_alert(a)
    assert "Bijan Robinson" in out
    assert "Read more" in out
    assert "https://espn.com/1" in out


def test_build_report(tmp_path):
    db = Database(tmp_path / "r.db")
    db.set_meta("league_id", "555")
    db.upsert_player(normalize_player(
        "1", {"full_name": "Bijan Robinson", "team": "ATL", "position": "RB",
              "depth_chart_order": 1, "age": 24, "years_exp": 2}, on_roster=True))
    db.commit()
    report = build_report(db)
    assert "My Dynasty Roster" in report
    assert "Bijan Robinson" in report
    assert "555" in report
