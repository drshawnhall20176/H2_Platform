"""
test_ncaaf_engine.py — offline tests for ncaaf_engine.py (no network, cached-file reads mocked).
"""

from unittest.mock import patch

import ncaaf_data as ND
import ncaaf_engine as E


def _season_schedule(season, team_a, team_b, n_games, completed=True):
    return [{"id": 1000 * season + i, "season": season, "week": i,
            "start_date": f"{season}-09-{i:02d}T19:30:00Z", "completed": completed,
            "home_team": team_a, "away_team": team_b, "home_id": 1, "away_id": 2}
           for i in range(1, n_games + 1)]


def test_infer_season_handles_january_rollover():
    assert E._infer_season("2026-09-05") == 2026
    assert E._infer_season("2027-01-19") == 2026   # CFP title game is part of the 2026 season
    assert E._infer_season("2026-12-01") == 2026
    assert E._infer_season("not-a-date") is None
    print("✓ _infer_season rolls a January date back to the prior year's season")


def test_team_games_played_before_counts_only_completed_prior_games():
    schedule = _season_schedule(2026, "Ohio State", "Texas", 5, completed=True)
    schedule[3]["completed"] = False   # week 4 not yet played
    assert E._team_games_played_before(schedule, "Ohio State", week=3) == 2   # weeks 1-2
    assert E._team_games_played_before(schedule, "Ohio State", week=6) == 4   # weeks 1,2,3,5 (4 excluded)
    assert E._team_games_played_before(schedule, "Nobody", week=6) == 0
    print("✓ _team_games_played_before counts only completed games strictly before the given week")


def test_team_games_played_total_counts_whole_completed_season():
    schedule = _season_schedule(2025, "Georgia", "Clemson", 12, completed=True)
    assert E._team_games_played_total(schedule, "Georgia") == 12
    assert E._team_games_played_total(schedule, "Clemson") == 12
    print("✓ _team_games_played_total counts every completed game across a full season")


def test_games_played_for_stats_season_uses_current_season_when_stats_match():
    schedule_2026 = _season_schedule(2026, "Ohio State", "Texas", 3, completed=True)
    n = E._team_games_played_for_stats_season(schedule_2026, stats_season=2026,
                                              target_season=2026, team="Ohio State", week=3)
    assert n == 2   # weeks 1-2 completed before week 3
    print("✓ uses current-season 'games before this week' when stats are from the current season")


def test_games_played_for_stats_season_uses_full_prior_season_on_fallback():
    # Regression guard for the real bug this session found via testing: week 1 of a NEW season
    # has zero completed games (by definition), but the cached stats are often actually last
    # season's FULL totals (ncaaf_data's own documented year-fallback). Dividing last season's
    # season-long total by "0 games played so far this season" silently zeroed out every
    # player's rate -- not understated it, ELIMINATED it, since player_row's own
    # `team_games_played <= 0` guard then dropped every player from the slate entirely.
    with patch.object(E, "get_schedule",
                      return_value=_season_schedule(2025, "Ohio State", "Texas", 12, completed=True)):
        n = E._team_games_played_for_stats_season(
            target_schedule=_season_schedule(2026, "Ohio State", "Texas", 1, completed=False),
            stats_season=2025, target_season=2026, team="Ohio State", week=1)
    assert n == 12   # the FULL prior season, not 0
    print("✓ falls back to the full prior season's game count when stats are a fallback year, "
         "not the broken 'games before week 1 of the new season' (always 0)")


def test_player_row_clears_markets_using_confirmed_column_names():
    stats_row = {"passing_YDS": 3600, "passing_ATT": 360, "rushing_YDS": 240, "rushing_CAR": 60}
    row = E.player_row({"id": "p1", "name": "Star QB", "position": "QB"}, "Ohio State", "Texas",
                       "Texas @ Ohio State", "2026-08-29T19:30:00Z", stats_row,
                       team_games_played=12)
    assert row is not None
    assert row["PassYds"] == 300.0   # 3600 / 12
    assert row["RushYds"] == 20.0    # 240 / 12
    assert set(row["_markets"]) == {"player_pass_yds", "player_rush_yds"}
    print("✓ player_row computes correct per-game rates and clears the right markets for a QB")


def test_player_row_returns_none_below_every_floor():
    # A backup QB with almost no attempts shouldn't clear the pass-yards floor.
    stats_row = {"passing_YDS": 40, "passing_ATT": 4, "rushing_YDS": 0, "rushing_CAR": 0}
    row = E.player_row({"id": "p2", "name": "Bench QB", "position": "QB"}, "Ohio State", "Texas",
                       "Texas @ Ohio State", "2026-08-29T19:30:00Z", stats_row,
                       team_games_played=12)
    assert row is None
    print("✓ player_row returns None for a player who clears no market's rotation floor")


def test_player_row_returns_none_with_no_stats_row_or_zero_games():
    base_player = {"id": "p1", "name": "X", "position": "QB"}
    assert E.player_row(base_player, "T", "O", "G", None, None, team_games_played=12) is None
    assert E.player_row(base_player, "T", "O", "G", None, {"passing_YDS": 300}, team_games_played=0) is None
    print("✓ player_row returns None when there's no stats row or zero games played (avoids a "
         "division-by-zero style silent wrong rate)")


def test_build_slate_end_to_end_with_season_fallback_stats():
    # The full integration test reproducing the exact real scenario: week 1 of a new season,
    # where the season stats cache is actually last year's completed totals.
    schedule_2026 = [{"id": 1, "season": 2026, "week": 1, "start_date": "2026-08-29T19:30:00Z",
                      "completed": False, "home_team": "Ohio State", "away_team": "Texas",
                      "home_id": 1, "away_id": 2, "venue": "X", "neutral_site": False}]
    schedule_2025_osu = _season_schedule(2025, "Ohio State", "Foe", 12, completed=True)
    schedule_2025_tex = _season_schedule(2025, "Texas", "Foe2", 12, completed=True)
    roster = [
        {"id": "p1", "name": "Star QB", "team": "Ohio State", "position": "QB"},
        {"id": "p3", "name": "Top WR", "team": "Texas", "position": "WR"},
    ]
    stats = [
        {"season": 2025, "player_id": "p1", "player": "Star QB", "team": "Ohio State",
         "passing_YDS": 3600, "passing_ATT": 360, "rushing_YDS": 240, "rushing_CAR": 60},
        {"season": 2025, "player_id": "p3", "player": "Top WR", "team": "Texas",
         "receiving_REC": 72, "receiving_YDS": 1080},
    ]

    def fake_load_schedule():
        return schedule_2026 + schedule_2025_osu + schedule_2025_tex

    with patch.object(ND, "load_schedule", side_effect=fake_load_schedule), \
        patch.object(ND, "load_rosters", return_value=roster), \
        patch.object(ND, "load_player_stats", return_value=stats):
        rows, meta = E.build_slate("2026-08-29")

    assert len(meta) == 1 and meta[0]["label"] == "Texas @ Ohio State"
    assert len(rows) == 2
    qb = next(r for r in rows if r["Player"] == "Star QB")
    wr = next(r for r in rows if r["Player"] == "Top WR")
    assert qb["PassYds"] == 300.0 and qb["_team_games_played"] == 12
    assert wr["Receptions"] == 6.0 and wr["RecYds"] == 90.0
    print("✓ build_slate correctly produces real per-game rates at week 1 of a new season, using "
         "the fallback season's own full game count instead of the broken zero")


def test_build_slate_falls_back_to_name_team_join_when_id_does_not_match():
    schedule = [{"id": 1, "season": 2026, "week": 1, "start_date": "2026-08-29T19:30:00Z",
                "completed": True, "home_team": "Ohio State", "away_team": "Texas",
                "home_id": 1, "away_id": 2, "venue": "X", "neutral_site": False}] + \
              _season_schedule(2026, "Ohio State", "Foe", 3, completed=True)
    # Roster's id ("roster-p1") deliberately does NOT match the stats row's player_id
    # ("stats-p1") -- exercises the documented id-space-mismatch fallback path.
    roster = [{"id": "roster-p1", "name": "Star QB", "team": "Ohio State", "position": "QB"}]
    stats = [{"season": 2026, "player_id": "stats-p1", "player": "Star QB", "team": "Ohio State",
             "passing_YDS": 900, "passing_ATT": 90, "rushing_YDS": 0, "rushing_CAR": 0}]

    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_rosters", return_value=roster), \
        patch.object(ND, "load_player_stats", return_value=stats):
        rows, meta = E.build_slate("2026-09-19")   # a later week so games-played > 0

    assert len(rows) == 1
    assert rows[0]["Player"] == "Star QB"
    print("✓ build_slate finds a player via the normalized name+team fallback when the id join "
         "doesn't match")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
