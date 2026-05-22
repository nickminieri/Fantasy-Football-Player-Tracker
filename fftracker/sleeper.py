"""Sleeper read-only API client.

Sleeper's public API needs no key and no auth. Docs: https://docs.sleeper.com/
Rate limit: stay under 1000 calls/min (we make a handful per run).
"""
from __future__ import annotations

from dataclasses import dataclass

from .http import get_json

BASE = "https://api.sleeper.app/v1"
# Stats/projections live at the API root, not under /v1.
PROJECTIONS_BASE = "https://api.sleeper.app/projections/nfl"


@dataclass
class League:
    league_id: str
    name: str
    season: str
    total_rosters: int
    previous_league_id: str | None = None


def get_user_id(username: str) -> str | None:
    """Resolve a Sleeper username (or user_id) to a numeric user_id."""
    data = get_json(f"{BASE}/user/{username}")
    if not data:
        return None
    return data.get("user_id")


def get_user_leagues(user_id: str, season: str, sport: str = "nfl") -> list[League]:
    data = get_json(f"{BASE}/user/{user_id}/leagues/{sport}/{season}") or []
    return [
        League(
            league_id=l.get("league_id"),
            name=l.get("name", "(unnamed)"),
            season=l.get("season", season),
            total_rosters=l.get("total_rosters", 0),
            previous_league_id=l.get("previous_league_id"),
        )
        for l in data
    ]


def get_league_rosters(league_id: str) -> list[dict]:
    """Each roster has owner_id, co_owners, and players (list of player_ids)."""
    return get_json(f"{BASE}/league/{league_id}/rosters") or []


def find_user_roster(rosters: list[dict], user_id: str) -> dict | None:
    """Return the roster owned (or co-owned) by user_id."""
    for roster in rosters:
        if roster.get("owner_id") == user_id:
            return roster
        co = roster.get("co_owners") or []
        if user_id in co:
            return roster
    return None


def get_all_players() -> dict[str, dict]:
    """Fetch the full NFL player dictionary keyed by player_id (~5MB).

    Returns player objects with name, team, position, injury_status,
    depth_chart_position/order, age, years_exp, espn_id, news_updated, etc.
    """
    return get_json(f"{BASE}/players/nfl") or {}


def get_projections(season, week, *, season_type: str = "regular",
                    positions: list[str] | None = None, order_by: str = "ppr"):
    """Fetch per-player projections for one NFL week.

    Returns Sleeper's raw payload (a list of projection rows). Each row carries a
    ``player_id`` and a ``stats`` dict with precomputed fantasy points
    (``pts_ppr``, ``pts_half_ppr``, ``pts_std``) alongside the projected stat line.
    Returns None for a week Sleeper has no data for (e.g. an unplayed future week).
    """
    params: dict = {"season_type": season_type, "order_by": order_by}
    if positions:
        # requests serializes a list value as repeated keys: position[]=QB&position[]=RB
        params["position[]"] = list(positions)
    return get_json(f"{PROJECTIONS_BASE}/{season}/{week}", params=params)


def get_trending(kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[dict]:
    """Trending adds/drops across Sleeper. kind is 'add' or 'drop'."""
    params = {"lookback_hours": lookback_hours, "limit": limit}
    return get_json(f"{BASE}/players/nfl/trending/{kind}", params=params) or []
