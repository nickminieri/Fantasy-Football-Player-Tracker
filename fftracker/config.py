"""Configuration loading.

Secrets and per-user settings come from environment variables (GitHub Actions
secrets in production). A small optional ``config.yaml`` can supply non-secret
extras like a watchlist of players that aren't on your roster.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a declared dependency
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "tracker.db"
DEFAULT_REPORT_PATH = REPO_ROOT / "data" / "ROSTER.md"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


@dataclass
class Config:
    sleeper_username: str | None = None
    sleeper_league_id: str | None = None
    season: str = field(default_factory=lambda: str(datetime.now().year))
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    db_path: Path = DEFAULT_DB_PATH
    report_path: Path = DEFAULT_REPORT_PATH
    # Extra player names to track even if not on the roster (from config.yaml).
    watchlist: list[str] = field(default_factory=list)
    # Alert toggles.
    alert_news: bool = True
    alert_injuries: bool = True
    alert_depth_chart: bool = True
    alert_team_changes: bool = True
    # How many days of news history to retain in the DB.
    news_retention_days: int = 60

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def _load_yaml(path: Path) -> dict:
    if not path.exists() or yaml is None:
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def load_config(config_path: Path | None = None) -> Config:
    """Build a Config from environment variables, with config.yaml as fallback."""
    file_cfg = _load_yaml(config_path or DEFAULT_CONFIG_PATH)

    def pick(env_key: str, yaml_key: str, default=None):
        val = os.environ.get(env_key)
        if val is not None and val != "":
            return val
        return file_cfg.get(yaml_key, default)

    alerts = file_cfg.get("alerts", {}) if isinstance(file_cfg.get("alerts"), dict) else {}

    cfg = Config(
        sleeper_username=pick("SLEEPER_USERNAME", "sleeper_username"),
        sleeper_league_id=pick("SLEEPER_LEAGUE_ID", "sleeper_league_id"),
        season=str(pick("SEASON", "season", str(datetime.now().year))),
        telegram_bot_token=pick("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        telegram_chat_id=pick("TELEGRAM_CHAT_ID", "telegram_chat_id"),
        watchlist=list(file_cfg.get("watchlist", []) or []),
        alert_news=bool(alerts.get("news", True)),
        alert_injuries=bool(alerts.get("injuries", True)),
        alert_depth_chart=bool(alerts.get("depth_chart", True)),
        alert_team_changes=bool(alerts.get("team_changes", True)),
        news_retention_days=int(file_cfg.get("news_retention_days", 60)),
    )
    return cfg
