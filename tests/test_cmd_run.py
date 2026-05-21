"""Exercise the cmd_run flow: quiet first run, then alert on a real change."""
from fftracker import espn, run, sleeper
from fftracker.config import Config
from fftracker.espn import Article

PLAYERS = {
    "100": {"full_name": "Bijan Robinson", "team": "ATL", "position": "RB",
            "depth_chart_order": 1, "espn_id": 4430807, "injury_status": None},
}


class FakeTelegram:
    sent: list[str] = []

    def __init__(self, token, chat_id):
        pass

    def send(self, text, **kwargs):
        FakeTelegram.sent.append(text)
        return True


def _stub(monkeypatch):
    monkeypatch.setattr(sleeper, "get_user_id", lambda u: "user1")
    monkeypatch.setattr(sleeper, "get_all_players", lambda: PLAYERS)
    monkeypatch.setattr(sleeper, "get_league_rosters",
                        lambda lid: [{"owner_id": "user1", "players": ["100"]}])
    monkeypatch.setattr(espn, "get_recent_news",
                        lambda session=None: [
                            Article("Old article", "preseason", "https://e/old",
                                    "2026-01-01T00:00:00Z", athlete_ids=["4430807"])])
    monkeypatch.setattr(run, "Telegram", FakeTelegram)


def test_first_run_is_quiet_then_alerts(tmp_path, monkeypatch):
    _stub(monkeypatch)
    FakeTelegram.sent = []
    cfg = Config(sleeper_username="me", sleeper_league_id="L1",
                 telegram_bot_token="t", telegram_chat_id="c",
                 db_path=tmp_path / "c.db", report_path=tmp_path / "R.md")

    # First run: snapshots, sends only the "live" greeting (no article spam).
    assert run.cmd_run(cfg) == 0
    assert len(FakeTelegram.sent) == 1
    assert "is live" in FakeTelegram.sent[0]
    assert (tmp_path / "R.md").exists()

    # Second run, no changes: nothing new to send.
    FakeTelegram.sent = []
    assert run.cmd_run(cfg) == 0
    assert FakeTelegram.sent == []

    # Now an injury appears -> exactly one alert batch goes out.
    PLAYERS["100"] = {**PLAYERS["100"], "injury_status": "Out"}
    monkeypatch.setattr(sleeper, "get_all_players", lambda: PLAYERS)
    FakeTelegram.sent = []
    assert run.cmd_run(cfg) == 0
    assert len(FakeTelegram.sent) == 1
    assert "Out" in FakeTelegram.sent[0]
