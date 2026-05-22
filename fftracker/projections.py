"""Season-long projection rankings built from Sleeper weekly projections.

Walks each week of the season, reads every player's projected fantasy points for
that game, and totals them per player so they can be ranked highest → lowest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import sleeper

# Standard fantasy-relevant positions. Override via --positions on the CLI.
DEFAULT_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# Map our scoring choice to the precomputed points key in a projection's stats.
SCORING_STAT = {"ppr": "pts_ppr", "half_ppr": "pts_half_ppr", "std": "pts_std"}
SCORING_LABEL = {"ppr": "PPR", "half_ppr": "Half-PPR", "std": "Standard"}


@dataclass
class PlayerProjection:
    player_id: str
    name: str
    position: str | None
    team: str | None
    total: float = 0.0
    weeks_counted: int = 0
    by_week: dict[int, float] = field(default_factory=dict)

    @property
    def avg(self) -> float:
        return self.total / self.weeks_counted if self.weeks_counted else 0.0


def parse_weeks(spec: str) -> list[int]:
    """Parse a weeks spec like '1-18' or '1,2,5-8' into a sorted list of ints."""
    weeks: set[int] = set()
    for chunk in str(spec).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            weeks.update(range(int(lo), int(hi) + 1))
        else:
            weeks.add(int(chunk))
    return sorted(w for w in weeks if w > 0)


def _proj_points(row: dict, stat_key: str) -> float | None:
    stats = row.get("stats") or {}
    try:
        return float(stats.get(stat_key))
    except (TypeError, ValueError):
        return None


def _iter_rows(payload):
    """Yield projection rows, tolerating both list and player_id-keyed dict shapes."""
    if isinstance(payload, dict):
        for pid, row in payload.items():
            if isinstance(row, dict):
                row.setdefault("player_id", pid)
                yield row
    elif isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                yield row


def _resolve_meta(pid: str, row: dict, all_players: dict) -> tuple[str, str | None, str | None]:
    meta = all_players.get(pid) or {}
    embedded = row.get("player") or {}
    name = (
        meta.get("full_name")
        or " ".join(x for x in [embedded.get("first_name"), embedded.get("last_name")] if x).strip()
        or embedded.get("full_name")
        or pid
    )
    position = meta.get("position") or embedded.get("position") or row.get("position")
    team = meta.get("team") or row.get("team") or embedded.get("team")
    return name, position, team


def aggregate(season, weeks, *, scoring: str = "ppr", positions: list[str] | None = None,
              all_players: dict | None = None, fetch=None):
    """Total projected points per player across the given weeks.

    Returns ``(projections, weeks_with_data)`` where projections is an unsorted
    list of PlayerProjection. ``fetch`` defaults to ``sleeper.get_projections``
    and is injectable for testing.
    """
    stat_key = SCORING_STAT.get(scoring, "pts_ppr")
    positions = positions or DEFAULT_POSITIONS
    fetch = fetch or sleeper.get_projections
    all_players = all_players if all_players is not None else sleeper.get_all_players()

    agg: dict[str, PlayerProjection] = {}
    weeks_with_data = 0
    for wk in weeks:
        rows = list(_iter_rows(fetch(season, wk, positions=positions)))
        if rows:
            weeks_with_data += 1
        for row in rows:
            pid = str(row.get("player_id") or "")
            if not pid:
                continue
            pts = _proj_points(row, stat_key)
            if pts is None:
                continue
            pp = agg.get(pid)
            if pp is None:
                name, position, team = _resolve_meta(pid, row, all_players)
                pp = agg[pid] = PlayerProjection(pid, name, position, team)
            if wk in pp.by_week:
                continue  # one row per player per week; ignore duplicate providers
            pp.by_week[wk] = pts
            pp.total += pts
            pp.weeks_counted += 1
    return list(agg.values()), weeks_with_data


def rank(projections: list[PlayerProjection]) -> list[PlayerProjection]:
    """Highest total first; ties broken by name for stable output."""
    return sorted(projections, key=lambda p: (-p.total, p.name))


def build_report(ranked: list[PlayerProjection], *, season, scoring: str,
                 weeks_with_data: int, weeks_requested: int, generated: str | None = None) -> str:
    generated = generated or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    label = SCORING_LABEL.get(scoring, scoring.upper())
    lines = [
        f"# {season} Season Projected Points ({label})",
        "",
        f"_Auto-generated {generated} · Sleeper weekly projections · "
        f"{weeks_with_data}/{weeks_requested} weeks with data · "
        f"{len(ranked)} players · highest → lowest_",
        "",
        "| Rank | Player | Pos | Team | Proj Pts | Wks | Avg/Wk |",
        "|-----:|--------|-----|------|---------:|----:|-------:|",
    ]
    for i, p in enumerate(ranked, 1):
        lines.append(
            f"| {i} | {p.name} | {p.position or '—'} | {p.team or 'FA'} "
            f"| {p.total:.1f} | {p.weeks_counted} | {p.avg:.1f} |"
        )
    lines.append("")
    return "\n".join(lines)


def format_console(ranked: list[PlayerProjection], top: int = 50) -> str:
    """A compact aligned table for the terminal. top<=0 prints everyone."""
    shown = ranked if top is None or top <= 0 else ranked[:top]
    header = f"{'#':>4}  {'Player':<24} {'Pos':<4} {'Tm':<4} {'ProjPts':>8} {'Wks':>4} {'Avg':>6}"
    lines = [header, "-" * len(header)]
    for i, p in enumerate(shown, 1):
        name = (p.name[:23] + "…") if len(p.name) > 24 else p.name
        lines.append(
            f"{i:>4}  {name:<24} {(p.position or '—'):<4} {(p.team or 'FA'):<4} "
            f"{p.total:>8.1f} {p.weeks_counted:>4} {p.avg:>6.1f}"
        )
    if top and top > 0 and len(ranked) > top:
        lines.append(f"... and {len(ranked) - top} more (full ranking written to file).")
    return "\n".join(lines)
