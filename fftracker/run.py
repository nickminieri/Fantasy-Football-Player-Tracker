"""Command-line entrypoint.

Commands:
  run             Sync roster, detect changes, fetch news, send Telegram alerts.
  discover        List your Sleeper leagues + IDs (to set SLEEPER_LEAGUE_ID).
  report          Regenerate ROSTER.md from the current DB (no network).
  projections     Rank every projected player by total season projected points.
  test-telegram   Send a test message to verify your bot credentials.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import projections as proj
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
        # One-time: older builds mis-attributed league-wide news to every
        # player. Clear that data once and re-snapshot quietly under the new logic.
        migrated = db.get_meta("news_attrib_v") != "2"
        if migrated:
            db.conn.execute("DELETE FROM news_items")
            db.set_meta("news_attrib_v", "2")
            db.commit()

        print(f"Syncing roster for '{cfg.sleeper_username}' (season {cfg.season})...")
        change_alerts = tracker.sync()
        print(f"  {len(change_alerts)} status change(s) detected.")

        print("Fetching player news...")
        new_count = len(tracker.gather_news())
        print(f"  {new_count} new article(s).")

        if first_run or migrated:
            # Snapshot existing state/news silently so the user isn't flooded
            # with pre-existing articles. Alert only on changes from here on.
            db.conn.execute("UPDATE news_items SET notified=1")
            db.commit()
            count = len(db.tracked_players())
            print(f"Quiet run: snapshotted {count} players (no alerts sent).")
            if first_run:
                db.set_meta("bootstrapped", "1")
                db.commit()
                if cfg.telegram_enabled:
                    Telegram(cfg.telegram_bot_token, cfg.telegram_chat_id).send(
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


def cmd_projections(cfg, args) -> int:
    season = args.season or cfg.season
    weeks = proj.parse_weeks(args.weeks)
    if not weeks:
        print(f"ERROR: no valid weeks parsed from '{args.weeks}'.", file=sys.stderr)
        return 2
    positions = [p.strip().upper() for p in args.positions.split(",") if p.strip()]
    label = proj.SCORING_LABEL.get(args.scoring, args.scoring.upper())

    print(f"Fetching {season} {label} projections for weeks "
          f"{weeks[0]}–{weeks[-1]} ({len(weeks)} weeks)...")
    players, weeks_with_data = proj.aggregate(
        season, weeks, scoring=args.scoring, positions=positions)
    ranked = proj.rank(players)

    if not ranked:
        print(
            "No projection data returned. Sleeper often doesn't publish weekly "
            "projections for an upcoming season until closer to kickoff — try a "
            "completed season, e.g. `--season 2025`.",
            file=sys.stderr,
        )
        return 1

    print(f"  {weeks_with_data}/{len(weeks)} weeks had data · {len(ranked)} players.\n")
    print(proj.format_console(ranked, top=args.top))

    out = Path(args.out) if args.out else (cfg.report_path.parent / "PROJECTIONS.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        proj.build_report(ranked, season=season, scoring=args.scoring,
                          weeks_with_data=weeks_with_data, weeks_requested=len(weeks)),
        encoding="utf-8",
    )
    print(f"\nWrote full ranking ({len(ranked)} players) to {out}")
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

    p_proj = sub.add_parser(
        "projections",
        help="Rank players by total projected points across the season.",
    )
    p_proj.add_argument("--season", default=None,
                        help="Season to project (defaults to SEASON / current year).")
    p_proj.add_argument("--weeks", default="1-18",
                        help="Weeks to total, e.g. '1-18' or '1,2,5-8' (default 1-18).")
    p_proj.add_argument("--scoring", choices=["ppr", "half_ppr", "std"], default="ppr",
                        help="Scoring basis for projected points (default ppr).")
    p_proj.add_argument("--positions", default=",".join(proj.DEFAULT_POSITIONS),
                        help="Comma-separated positions to include (default QB,RB,WR,TE,K,DEF).")
    p_proj.add_argument("--top", type=int, default=50,
                        help="How many to print to the console; 0 prints all (default 50).")
    p_proj.add_argument("--out", default=None,
                        help="Markdown output path (default data/PROJECTIONS.md).")

    args = parser.parse_args(argv)

    cfg = load_config()
    if args.command == "projections":
        return cmd_projections(cfg, args)
    dispatch = {
        "run": cmd_run,
        "discover": cmd_discover,
        "report": cmd_report,
        "test-telegram": cmd_test_telegram,
    }
    return dispatch[args.command](cfg)


if __name__ == "__main__":
    raise SystemExit(main())
