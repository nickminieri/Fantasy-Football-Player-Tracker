"""Generate the human-readable ROSTER.md snapshot and format Telegram alerts."""
from __future__ import annotations

from datetime import datetime, timezone

from .db import Database
from .telegram import escape
from .tracker import Alert

CATEGORY_EMOJI = {
    "news": "📰",
    "injury": "🚑",
    "depth_chart": "📊",
    "team": "🔁",
}

POSITION_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 4, "DEF": 5}


def _injury_badge(player: dict) -> str:
    status = player.get("injury_status")
    return f" ⚠️ {status}" if status else ""


def build_report(db: Database) -> str:
    players = db.tracked_players()
    league_id = db.get_meta("league_id", "?")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    roster = [p for p in players if p.get("on_roster")]
    watch = [p for p in players if not p.get("on_roster") and p.get("on_watchlist")]
    roster.sort(key=lambda p: (POSITION_ORDER.get(p.get("position"), 9),
                               p.get("depth_chart_order") or 99,
                               p.get("full_name") or ""))

    lines = [
        "# My Dynasty Roster",
        "",
        f"_Auto-generated {generated} · Sleeper league `{league_id}` · "
        f"{len(roster)} players_",
        "",
        "| Pos | Player | Team | Depth | Status | Age | Exp |",
        "|-----|--------|------|-------|--------|-----|-----|",
    ]
    for p in roster:
        depth = p.get("depth_chart_order")
        depth_str = f"#{depth}" if depth else "—"
        status = p.get("injury_status") or p.get("status") or "Active"
        lines.append(
            f"| {p.get('position') or '—'} "
            f"| {p.get('full_name')} "
            f"| {p.get('team') or 'FA'} "
            f"| {depth_str} "
            f"| {status} "
            f"| {p.get('age') or '—'} "
            f"| {p.get('years_exp') if p.get('years_exp') is not None else '—'} |"
        )

    if watch:
        lines += ["", "## Watchlist", "",
                  "| Pos | Player | Team | Status |",
                  "|-----|--------|------|--------|"]
        for p in watch:
            status = p.get("injury_status") or p.get("status") or "Active"
            lines.append(
                f"| {p.get('position') or '—'} | {p.get('full_name')} "
                f"| {p.get('team') or 'FA'} | {status} |"
            )

    # Recent news section.
    news = db.conn.execute(
        "SELECT n.headline, n.url, n.published, p.full_name "
        "FROM news_items n LEFT JOIN players p ON p.player_id = n.player_id "
        "ORDER BY n.seen_at DESC LIMIT 25"
    ).fetchall()
    if news:
        lines += ["", "## Recent News", ""]
        for row in news:
            name = row["full_name"] or "Unknown"
            if row["url"]:
                lines.append(f"- **{name}** — [{row['headline']}]({row['url']})")
            else:
                lines.append(f"- **{name}** — {row['headline']}")

    lines.append("")
    return "\n".join(lines)


def format_alert(alert: Alert) -> str:
    """Format a single alert as a Telegram HTML block."""
    emoji = CATEGORY_EMOJI.get(alert.category, "•")
    parts = [f"{emoji} <b>{escape(alert.player_name)}</b>", escape(alert.title)]
    if alert.detail:
        parts.append(escape(alert.detail))
    if alert.url:
        parts.append(f'<a href="{escape(alert.url)}">Read more</a>')
    return "\n".join(parts)


def format_alert_batch(alerts: list[Alert]) -> str:
    """Group alerts into one digest message (newest run summary)."""
    blocks = [format_alert(a) for a in alerts]
    header = f"<b>Fantasy update — {len(alerts)} item(s)</b>"
    return header + "\n\n" + "\n\n".join(blocks)
