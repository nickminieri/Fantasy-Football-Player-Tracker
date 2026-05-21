"""Core logic: normalize Sleeper players, diff state for changes, gather news."""
from __future__ import annotations

from dataclasses import dataclass

from . import espn, sleeper
from .config import Config
from .db import Database


@dataclass
class Alert:
    player_id: str
    player_name: str
    category: str  # "news" | "injury" | "depth_chart" | "team"
    title: str
    detail: str = ""
    url: str = ""


def normalize_player(player_id: str, raw: dict, *, on_roster: bool = False,
                     on_watchlist: bool = False) -> dict:
    """Map a Sleeper player object onto our player table columns."""
    full_name = raw.get("full_name") or " ".join(
        x for x in [raw.get("first_name"), raw.get("last_name")] if x
    ).strip() or player_id
    return {
        "player_id": player_id,
        "full_name": full_name,
        "team": raw.get("team"),
        "position": raw.get("position"),
        "age": raw.get("age"),
        "years_exp": raw.get("years_exp"),
        "status": raw.get("status"),
        "injury_status": raw.get("injury_status"),
        "injury_notes": raw.get("injury_notes"),
        "injury_body_part": raw.get("injury_body_part"),
        "depth_chart_position": raw.get("depth_chart_position"),
        "depth_chart_order": raw.get("depth_chart_order"),
        "number": raw.get("number"),
        "college": raw.get("college"),
        "espn_id": str(raw["espn_id"]) if raw.get("espn_id") else None,
        "news_updated": raw.get("news_updated"),
        "on_roster": 1 if on_roster else 0,
        "on_watchlist": 1 if on_watchlist else 0,
    }


def _depth_label(order) -> str:
    mapping = {1: "starter (1st)", 2: "2nd string", 3: "3rd string"}
    try:
        order = int(order)
    except (TypeError, ValueError):
        return "unknown"
    return mapping.get(order, f"{order}th on depth chart")


def detect_changes(old: dict | None, new: dict, cfg: Config) -> list[Alert]:
    """Compare a previously stored player row to the freshly fetched state."""
    if old is None:
        return []  # First time we see a player: snapshot only, don't alert.
    alerts: list[Alert] = []
    name = new["full_name"]
    pid = new["player_id"]

    if cfg.alert_injuries and (old.get("injury_status") or "") != (new.get("injury_status") or ""):
        old_s = old.get("injury_status") or "Healthy"
        new_s = new.get("injury_status") or "Healthy"
        note = new.get("injury_notes") or new.get("injury_body_part") or ""
        alerts.append(Alert(
            pid, name, "injury",
            f"Injury status: {old_s} → {new_s}",
            detail=note,
        ))

    if cfg.alert_team_changes and (old.get("team") or "") != (new.get("team") or ""):
        old_t = old.get("team") or "FA"
        new_t = new.get("team") or "FA"
        alerts.append(Alert(
            pid, name, "team",
            f"Team change: {old_t} → {new_t}",
        ))

    if cfg.alert_depth_chart:
        old_o, new_o = old.get("depth_chart_order"), new.get("depth_chart_order")
        if old_o != new_o and new_o is not None:
            direction = ""
            try:
                if old_o is not None:
                    direction = " (moved up)" if int(new_o) < int(old_o) else " (moved down)"
            except (TypeError, ValueError):
                pass
            alerts.append(Alert(
                pid, name, "depth_chart",
                f"Depth chart: now {_depth_label(new_o)}{direction}",
            ))

    return alerts


class Tracker:
    def __init__(self, cfg: Config, db: Database, session=None):
        self.cfg = cfg
        self.db = db
        self.session = session

    # -- roster resolution ----------------------------------------------
    def resolve_league_id(self, user_id: str) -> str | None:
        if self.cfg.sleeper_league_id:
            return self.cfg.sleeper_league_id
        leagues = sleeper.get_user_leagues(user_id, self.cfg.season)
        if len(leagues) == 1:
            return leagues[0].league_id
        return None  # ambiguous; caller should report and ask for SLEEPER_LEAGUE_ID

    def get_roster_player_ids(self, league_id: str, user_id: str) -> list[str]:
        rosters = sleeper.get_league_rosters(league_id)
        mine = sleeper.find_user_roster(rosters, user_id)
        return list(mine.get("players") or []) if mine else []

    # -- main sync -------------------------------------------------------
    def sync(self) -> list[Alert]:
        """Refresh roster + player state and return alerts for any changes."""
        cfg = self.cfg
        user_id = sleeper.get_user_id(cfg.sleeper_username)
        if not user_id:
            raise RuntimeError(f"Sleeper username '{cfg.sleeper_username}' not found")

        league_id = self.resolve_league_id(user_id)
        if not league_id:
            raise RuntimeError(
                "Could not determine league. You're in multiple leagues this "
                "season — set SLEEPER_LEAGUE_ID. Run the 'discover' command to list them."
            )

        roster_ids = set(self.get_roster_player_ids(league_id, user_id))
        all_players = sleeper.get_all_players()

        # Resolve watchlist names -> player_ids.
        watch_ids = self._resolve_watchlist(all_players)

        tracked = roster_ids | watch_ids
        self.db.set_meta("league_id", league_id)
        self.db.set_meta("user_id", user_id)
        self.db.set_meta("roster_count", str(len(roster_ids)))

        alerts: list[Alert] = []
        self.db.clear_roster_flags()
        for pid in tracked:
            raw = all_players.get(pid)
            if not raw:
                continue
            old = self.db.get_player(pid)
            new = normalize_player(
                pid, raw,
                on_roster=pid in roster_ids,
                on_watchlist=pid in watch_ids,
            )
            alerts.extend(detect_changes(old, new, cfg))
            self.db.upsert_player(new)
        self.db.commit()
        return alerts

    def _resolve_watchlist(self, all_players: dict) -> set[str]:
        if not self.cfg.watchlist:
            return set()
        wanted = {n.strip().lower() for n in self.cfg.watchlist}
        found = set()
        for pid, raw in all_players.items():
            name = (raw.get("full_name") or "").strip().lower()
            if name in wanted:
                found.add(pid)
        return found

    # -- news ------------------------------------------------------------
    def gather_news(self) -> list[Alert]:
        """Fetch ESPN news for tracked players and store new items as alerts."""
        if not self.cfg.alert_news:
            return []
        alerts: list[Alert] = []
        for player in self.db.tracked_players():
            espn_id = player.get("espn_id")
            if not espn_id:
                continue
            try:
                articles = espn.get_player_news(espn_id, session=self.session)
            except Exception as exc:  # ESPN has no SLA; never let it abort the run
                print(f"[news] {player['full_name']}: {exc}")
                continue
            for art in articles:
                key = f"{player['player_id']}|{art.dedupe_key()}"
                inserted = self.db.add_news(
                    player_id=player["player_id"],
                    source=art.source,
                    headline=art.headline,
                    body=art.description,
                    url=art.url,
                    published=art.published,
                    dedupe_key=key,
                )
                if inserted:
                    alerts.append(Alert(
                        player["player_id"], player["full_name"], "news",
                        art.headline, detail=art.description, url=art.url,
                    ))
        self.db.commit()
        return alerts
