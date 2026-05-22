"""Projection ranking tests with all network calls stubbed."""
from fftracker import projections as proj

ALL_PLAYERS = {
    "100": {"full_name": "Bijan Robinson", "team": "ATL", "position": "RB"},
    "200": {"full_name": "Drake London", "team": "ATL", "position": "WR"},
    "QB1": {"full_name": "Patrick Mahomes", "team": "KC", "position": "QB"},
    "PHI": {"full_name": "Philadelphia Eagles", "team": "PHI", "position": "DEF"},
}

# week -> list of projection rows (Sleeper's list shape).
WEEKLY = {
    1: [
        {"player_id": "100", "stats": {"pts_ppr": 20.0, "pts_std": 14.0}},
        {"player_id": "200", "stats": {"pts_ppr": 12.0}},
        {"player_id": "QB1", "stats": {"pts_ppr": 25.0}},
    ],
    2: [
        {"player_id": "100", "stats": {"pts_ppr": 18.0}},
        {"player_id": "100", "stats": {"pts_ppr": 99.0}},  # dup provider, ignored
        {"player_id": "200", "stats": {"pts_ppr": 10.0}},
        {"player_id": "PHI", "stats": {"pts_ppr": 8.0}},
    ],
    3: [],  # an unplayed/empty week contributes nothing
}


def _fetch(season, week, *, positions=None, **kw):
    return WEEKLY.get(week)


def test_parse_weeks():
    assert proj.parse_weeks("1-18") == list(range(1, 19))
    assert proj.parse_weeks("1,2,5-7") == [1, 2, 5, 6, 7]
    assert proj.parse_weeks("3") == [3]


def test_aggregate_sums_and_dedupes_per_week():
    players, weeks_with_data = proj.aggregate(
        "2026", [1, 2, 3], scoring="ppr", all_players=ALL_PLAYERS, fetch=_fetch)
    by_id = {p.player_id: p for p in players}

    assert weeks_with_data == 2  # week 3 was empty
    # Bijan: 20 + 18 (the 99 duplicate in week 2 is ignored), over 2 weeks.
    assert by_id["100"].total == 38.0
    assert by_id["100"].weeks_counted == 2
    assert by_id["100"].avg == 19.0
    # London: 12 + 10.
    assert by_id["200"].total == 22.0
    # Defense projection is picked up and named from the player dict.
    assert by_id["PHI"].name == "Philadelphia Eagles"
    assert by_id["PHI"].position == "DEF"


def test_rank_orders_high_to_low():
    players, _ = proj.aggregate(
        "2026", [1, 2], scoring="ppr", all_players=ALL_PLAYERS, fetch=_fetch)
    ranked = proj.rank(players)
    totals = [p.total for p in ranked]
    assert totals == sorted(totals, reverse=True)
    assert ranked[0].name == "Bijan Robinson"  # 38.0 is the highest


def test_scoring_choice_changes_points():
    players, _ = proj.aggregate(
        "2026", [1], scoring="std", all_players=ALL_PLAYERS, fetch=_fetch)
    by_id = {p.player_id: p for p in players}
    assert by_id["100"].total == 14.0  # pts_std for week 1
    # London has no pts_std in the stub -> no usable points, so not included.
    assert "200" not in by_id


def test_dict_shaped_payload_is_handled():
    def fetch_dict(season, week, *, positions=None, **kw):
        return {"100": {"stats": {"pts_ppr": 5.0}}} if week == 1 else None

    players, weeks_with_data = proj.aggregate(
        "2026", [1, 2], all_players=ALL_PLAYERS, fetch=fetch_dict)
    assert weeks_with_data == 1
    assert players[0].player_id == "100" and players[0].total == 5.0


def test_build_report_markdown():
    players, wwd = proj.aggregate(
        "2026", [1, 2], all_players=ALL_PLAYERS, fetch=_fetch)
    md = proj.build_report(proj.rank(players), season="2026", scoring="ppr",
                           weeks_with_data=wwd, weeks_requested=2,
                           generated="2026-05-22 00:00 UTC")
    assert "2026 Season Projected Points (PPR)" in md
    assert "| 1 | Bijan Robinson |" in md
    assert "Philadelphia Eagles" in md


def test_format_console_truncates_with_top():
    players, _ = proj.aggregate(
        "2026", [1, 2], all_players=ALL_PLAYERS, fetch=_fetch)
    out = proj.format_console(proj.rank(players), top=2)
    assert "and 2 more" in out
