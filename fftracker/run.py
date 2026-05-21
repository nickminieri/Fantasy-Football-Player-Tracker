"""Command-line entrypoint.

Commands:
  run             Sync roster, detect changes, fetch news, send Telegram alerts.
  discover        List your Sleeper leagues + IDs (to set SLEEPER_LEAGUE_ID).
  report          Regenerate ROSTER.md from the current DB (no network).
  test-telegram   Send a test message to verify your bot credentials.
"""
from __future__ import annotations

import argparse
import sys

from . import sleeper
from .config import load_config
from .db import Database
from .report import build_report, format_alert_batch
from .telegram import Telegram
from .tracker import Alert, Tracker


def cmd_run(cfg) -> int:
    if not cfg.sleeper_username:
        print("ERROR: SLEEPER_USERNAME is not set.", file=sys.stderr)
        return 2

    db = Database(cfg.db_path)
    try:
        tracker = Tracker(cfg, db)
        first_run = db.get_meta("bootstrapped") != "1"

        print(f"Syncing roster for '{cfg.sleeper_username}' (season {cfg.season})...")
        change_alerts = tracker.sync()
        print(f"  {len(change_alerts)} status change(s) detected.")

        print("Fetching player news...")
        new_count = len(tracker.gather_news())
        print(f"  {new_count} new article(s).")

        if first_run:
            # Snapshot existing state/news silently so the user isn't flooded
            # with pre-existing articles. Alert only on changes from here on.
            db.conn.execute("UPDATE news_items SET notified=1")
            db.set_meta("bootstrapped", "1")
            db.commit()
            tg_first = Telegram(cfg.telegram_bot_token, cfg.telegram_chat_id) \
                if cfg.telegram_enabled else None
            count = len(db.tracked_players())
            print(f"First run: snapshotted {count} players (no alerts sent).")
            if tg_first:
                tg_first.send(
                    f"✅ <b>Fantasy tracker is live</b>\nWatching {count} players. "
                    "You'll get news, injury, depth-chart and trade alerts here."
                )
            _write_report(cfg, db)
            db.prune_news(cfg.news_retention_days)
            return 0

        # Build news alerts from the DB so a previously failed send retries.
        pending_news = db.unnotified_news()
        news_alerts = [
            Alert(row["player_id"], row.get("full_name") or "Unknown", "news",
                  row["headline"], detail=row.get("body") or "", url=row.get("url") or "")
            for row in pending_news
        ]
        alerts = change_alerts + news_alerts

        if alerts and cfg.telegram_enabled:
            tg = Telegram(cfg.telegram_bot_token, cfg.telegram_chat_id)
            sent = tg.send(format_alert_batch(alerts))
            if sent:
                print(f"Sent {len(alerts)} alert(s) to Telegram.")
                for row in pending_news:
                    db.mark_notified(row["id"])
                db.commit()
            else:
                print("Telegram send failed; will retry news next run.")
        elif alerts:
            print("Telegram not configured; alerts not sent:")
            for a in alerts:
                print(f"  [{a.category}] {a.player_name}: {a.title}")

        _write_report(cfg, db)
        db.prune_news(cfg.news_retention_days)
    finally:
        db.close()
    return 0


def _write_report(cfg, db):
    cfg.report_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.report_path.write_text(build_report(db), encoding="utf-8")
    print(f"Wrote {cfg.report_path}")


def cmd_discover(cfg) -> int:
    if not cfg.sleeper_username:
        print("ERROR: SLEEPER_USERNAME is not set.", file=sys.stderr)
        return 2
    user_id = sleeper.get_user_id(cfg.sleeper_username)
    if not user_id:
        print(f"Username '{cfg.sleeper_username}' not found.", file=sys.stderr)
        return 1
    leagues = sleeper.get_user_leagues(user_id, cfg.season)
    if not leagues:
        print(f"No NFL leagues found for {cfg.sleeper_username} in {cfg.season}.")
        return 0
    print(f"user_id: {user_id}")
    print(f"Leagues for season {cfg.season}:\n")
    for lg in leagues:
        print(f"  {lg.name}")
        print(f"    league_id: {lg.league_id}  ({lg.total_rosters} teams)")
    print("\nSet SLEEPER_LEAGUE_ID to the id of your dynasty league.")
    return 0


def cmd_report(cfg) -> int:
    db = Database(cfg.db_path)
    try:
        cfg.report_path.write_text(build_report(db), encoding="utf-8")
        print(f"Wrote {cfg.report_path}")
    finally:
        db.close()
    return 0


def cmd_test_telegram(cfg) -> int:
    if not cfg.telegram_enabled:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set.",
              file=sys.stderr)
        return 2
    tg = Telegram(cfg.telegram_bot_token, cfg.telegram_chat_id)
    ok = tg.send("✅ <b>Fantasy tracker connected!</b>\nYou'll get player news here.")
    print("Sent." if ok else "Failed to send.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fftracker")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "discover", "report", "test-telegram"):
        sub.add_parser(name)
    args = parser.parse_args(argv)

    cfg = load_config()
    dispatch = {
        "run": cmd_run,
        "discover": cmd_discover,
        "report": cmd_report,
        "test-telegram": cmd_test_telegram,
    }
    return dispatch[args.command](cfg)


if __name__ == "__main__":
    raise SystemExit(main())
