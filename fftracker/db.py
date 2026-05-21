"""SQLite persistence.

The DB file is committed back to the repo by the GitHub Action so state
(player snapshots + which news we've already sent) survives between stateless
runs. That's what prevents duplicate notifications.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id           TEXT PRIMARY KEY,
    full_name           TEXT,
    team                TEXT,
    position            TEXT,
    age                 INTEGER,
    years_exp           INTEGER,
    status              TEXT,
    injury_status       TEXT,
    injury_notes        TEXT,
    injury_body_part    TEXT,
    depth_chart_position TEXT,
    depth_chart_order   INTEGER,
    number              INTEGER,
    college             TEXT,
    espn_id             TEXT,
    news_updated        INTEGER,
    on_roster           INTEGER DEFAULT 0,
    on_watchlist        INTEGER DEFAULT 0,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS news_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT,
    source      TEXT,
    headline    TEXT,
    body        TEXT,
    url         TEXT,
    published   TEXT,
    dedupe_key  TEXT UNIQUE,
    seen_at     TEXT,
    notified    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_news_player ON news_items(player_id);
CREATE INDEX IF NOT EXISTS idx_players_roster ON players(on_roster);
"""

PLAYER_COLUMNS = [
    "player_id", "full_name", "team", "position", "age", "years_exp",
    "status", "injury_status", "injury_notes", "injury_body_part",
    "depth_chart_position", "depth_chart_order", "number", "college",
    "espn_id", "news_updated", "on_roster", "on_watchlist", "updated_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---- meta ----------------------------------------------------------
    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # ---- players -------------------------------------------------------
    def get_player(self, player_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM players WHERE player_id=?", (player_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_player(self, record: dict):
        record = {**record, "updated_at": _now()}
        cols = [c for c in PLAYER_COLUMNS if c in record]
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "player_id")
        sql = (
            f"INSERT INTO players ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(player_id) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, [record[c] for c in cols])

    def clear_roster_flags(self):
        self.conn.execute("UPDATE players SET on_roster=0, on_watchlist=0")

    def tracked_players(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM players WHERE on_roster=1 OR on_watchlist=1 "
            "ORDER BY position, depth_chart_order"
        ).fetchall()
        return [dict(r) for r in rows]

    def commit(self):
        self.conn.commit()

    # ---- news ----------------------------------------------------------
    def news_exists(self, dedupe_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM news_items WHERE dedupe_key=?", (dedupe_key,)
        ).fetchone()
        return row is not None

    def add_news(self, *, player_id: str, source: str, headline: str, body: str,
                 url: str, published: str, dedupe_key: str) -> bool:
        """Insert a news item. Returns True if newly inserted (not a duplicate)."""
        try:
            self.conn.execute(
                "INSERT INTO news_items "
                "(player_id, source, headline, body, url, published, dedupe_key, seen_at, notified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (player_id, source, headline, body, url, published, dedupe_key, _now()),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def unnotified_news(self) -> list[dict]:
        """News items stored but not yet successfully pushed (incl. past failures)."""
        rows = self.conn.execute(
            "SELECT n.*, p.full_name FROM news_items n "
            "LEFT JOIN players p ON p.player_id = n.player_id "
            "WHERE n.notified=0 ORDER BY n.seen_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_notified(self, news_id: int):
        self.conn.execute("UPDATE news_items SET notified=1 WHERE id=?", (news_id,))

    def prune_news(self, retention_days: int):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        self.conn.execute("DELETE FROM news_items WHERE seen_at < ?", (cutoff,))
        self.conn.commit()
