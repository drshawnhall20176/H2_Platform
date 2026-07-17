"""
test_nfl_engine.py — offline unit tests for nfl_engine.py.

No network required — nflreadpy's load_* functions are monkeypatched with a thin wrapper mimicking
their real Polars-DataFrame-with-.to_pandas() interface, built from real column shapes and (where
noted) real values CONFIRMED LIVE against nflreadpy during this build (not guessed): a real 2025
schedule fetch (285 games, game_id format "2025_01_DAL_PHI", away_rest/home_rest present), a real
weekly-stats fetch (19,421 rows) including Patrick Mahomes' actual Week 1 2025 line (24/39, 258
yards, 1 TD), and real roster/injury fetches.

    python test_nfl_engine.py     # or: pytest test_nfl_engine.py
"""

import pandas as pd

import nfl_engine as E


class _FakePolarsDF:
    """Mimics nflreadpy's real interface just enough for these tests: every load_* function
    returns something with a .to_pandas() method. Avoids adding an explicit polars import/
    dependency to the test file itself (polars is already a transitive nflreadpy dependency, but
    the engine code only ever calls .to_pandas() before touching the data, so that's all this
    needs to fake)."""
    def __init__(self, pdf: pd.DataFrame):
        self._pdf = pdf

    def to_pandas(self) -> pd.DataFrame:
        return self._pdf


# ----------------------------------------------------------------- _resolve_week
def test_resolve_week_matches_date_within_the_weeks_game_range():
    schedule = [
        {"week": 1, "game_date": "2025-09-04"}, {"week": 1, "game_date": "2025-09-08"},
        {"week": 2, "game_date": "2025-09-11"}, {"week": 2, "game_date": "2025-09-15"},
    ]
    assert E._resolve_week(schedule, "2025-09-06") == 1   # a Saturday mid-week-1
    assert E._resolve_week(schedule, "2025-09-13") == 2
    print("✓ _resolve_week correctly matches a date falling within a week's own game range")


def test_resolve_week_buffer_day_after_last_game_still_matches_that_week():
    # A date picked the morning after a Monday-night game should still resolve to that week, not
    # silently fall through to "next upcoming" — the whole point of the +1 day buffer.
    schedule = [{"week": 1, "game_date": "2025-09-04"}, {"week": 1, "game_date": "2025-09-08"}]
    assert E._resolve_week(schedule, "2025-09-09") == 1
    print("✓ _resolve_week's buffer day correctly keeps the day after the last game in that week")


def test_resolve_week_falls_forward_to_next_upcoming_week():
    # A bye-week Tuesday between weeks should resolve to the UPCOMING week, not nothing.
    schedule = [
        {"week": 1, "game_date": "2025-09-04"}, {"week": 1, "game_date": "2025-09-08"},
        {"week": 3, "game_date": "2025-09-18"}, {"week": 3, "game_date": "2025-09-22"},
    ]
    assert E._resolve_week(schedule, "2025-09-12") == 3
    print("✓ _resolve_week falls forward to the next upcoming week for an in-between date")


def test_resolve_week_falls_back_to_last_week_when_date_is_past_the_season():
    schedule = [{"week": 1, "game_date": "2025-09-04"}, {"week": 22, "game_date": "2026-02-08"}]
    assert E._resolve_week(schedule, "2026-07-16") == 22
    print("✓ _resolve_week falls back to the season's last week for a date past the whole season")


def test_resolve_week_none_for_empty_schedule():
    assert E._resolve_week([], "2025-09-04") is None


# ----------------------------------------------------------------- get_schedule
def test_get_schedule_parses_real_confirmed_shape(monkeypatch):
    # Real column names, confirmed live: load_schedules([2025]) actually returned exactly these
    # columns, including away_rest/home_rest already computed — NFL doesn't need to derive rest
    # days by scanning recent games the way every basketball engine in this platform does.
    fake_df = pd.DataFrame([
        {"game_id": "2025_01_DAL_PHI", "week": 1, "gameday": "2025-09-04",
        "home_team": "PHI", "away_team": "DAL", "home_score": 24, "away_score": 20,
        "home_rest": 7, "away_rest": 7},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_df))
    sched = E.get_schedule(2025)
    assert len(sched) == 1
    assert sched[0]["game_id"] == "2025_01_DAL_PHI"
    assert sched[0]["home_rest"] == 7 and sched[0]["away_rest"] == 7
    print("✓ get_schedule correctly parses the real, confirmed nflreadpy schedule shape")


def test_get_schedule_empty_on_fetch_failure(monkeypatch):
    def raise_err(seasons):
        raise ConnectionError("simulated failure")
    monkeypatch.setattr(E.nfl, "load_schedules", raise_err)
    assert E.get_schedule(2026) == []


# ----------------------------------------------------------------- get_team_roster
def test_get_team_roster_skips_empty_gsis_id(monkeypatch):
    # Real, confirmed data quality quirk: some roster rows (recently-signed/practice-squad
    # players) have an empty gsis_id, not None — must be skipped, not included with a blank id.
    fake_df = pd.DataFrame([
        {"season": 2025, "team": "KC", "position": "QB", "full_name": "Patrick Mahomes", "gsis_id": "00-0033873"},
        {"season": 2025, "team": "KC", "position": "DL", "full_name": "No Id Guy", "gsis_id": ""},
    ])
    monkeypatch.setattr(E.nfl, "load_rosters", lambda seasons: _FakePolarsDF(fake_df))
    roster = E.get_team_roster("KC", 2025)
    assert len(roster) == 1
    assert roster[0]["id"] == "00-0033873" and roster[0]["name"] == "Patrick Mahomes"
    print("✓ get_team_roster correctly skips roster rows with no gsis_id")


# ----------------------------------------------------------------- load_season_weekly_stats
def test_load_season_weekly_stats_computes_touches_column(monkeypatch):
    fake_df = pd.DataFrame([
        {"player_id": "p1", "week": 1, "carries": 15, "targets": 3},
        {"player_id": "p2", "week": 1, "carries": 0, "targets": 8},
    ])
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_df))
    weekly = E.load_season_weekly_stats(2025)
    assert weekly.loc[weekly["player_id"] == "p1", "_touches"].iloc[0] == 18
    assert weekly.loc[weekly["player_id"] == "p2", "_touches"].iloc[0] == 8
    print("✓ load_season_weekly_stats correctly computes the derived _touches column")


# ----------------------------------------------------------------- player_recent_games
def test_player_recent_games_real_confirmed_mahomes_line(monkeypatch):
    # REAL, confirmed live: Patrick Mahomes' actual Week 1 2025 line was 24/39, 258 passing
    # yards, 1 TD (player_id "00-0033873", matching the same GSIS id format rosters use).
    fake_df = pd.DataFrame([
        {"player_id": "00-0033873", "week": 1, "completions": 24, "attempts": 39,
        "passing_yards": 258, "passing_tds": 1, "carries": 0, "targets": 0},
        {"player_id": "00-0033873", "week": 2, "completions": 16, "attempts": 29,
        "passing_yards": 187, "passing_tds": 1, "carries": 0, "targets": 0},
    ])
    fake_df["_touches"] = fake_df["carries"] + fake_df["targets"]
    games = E.player_recent_games(fake_df, "00-0033873", before_week=3, n=5)
    assert len(games) == 2
    assert games[0]["week"] == 2 and games[0]["passing_yards"] == 187   # most recent first
    assert games[1]["week"] == 1 and games[1]["passing_yards"] == 258
    print("✓ player_recent_games correctly returns real confirmed Mahomes data, most recent first")


def test_player_recent_games_excludes_the_before_week_itself():
    # THE lookahead-bias guard: week 1 has nothing strictly before it.
    df = pd.DataFrame([{"player_id": "p1", "week": 1, "passing_yards": 300}])
    assert E.player_recent_games(df, "p1", before_week=1) == []
    print("✓ player_recent_games correctly excludes the target week itself (no lookahead bias)")


# ----------------------------------------------------------------- get_team_injuries
def test_get_team_injuries_real_confirmed_shape(monkeypatch):
    fake_df = pd.DataFrame([
        {"team": "NYG", "week": 6, "full_name": "Darius Slayton", "report_status": "Out",
        "position": "WR", "report_primary_injury": "Hamstring", "report_secondary_injury": None},
    ])
    monkeypatch.setattr(E.nfl, "load_injuries", lambda seasons: _FakePolarsDF(fake_df))
    inj = E.get_team_injuries("NYG", 2025, 6)
    assert inj == [{"player": "Darius Slayton", "status": "Out", "position": "WR",
                   "return_date": None, "comment": "Hamstring"}]
    print("✓ get_team_injuries matches basketball_engine.get_team_injuries' own output shape")


# ----------------------------------------------------------------- player_row (position gating)
def test_player_row_qb_gets_only_pass_yards_market():
    player = {"id": "00-0033873", "name": "Patrick Mahomes", "position": "QB"}
    log = [{"passing_yards": 258, "attempts": 39}, {"passing_yards": 187, "attempts": 29}]
    row = E.player_row(player, "KC", "LAC", "KC @ LAC", "2025-09-05", log)
    assert row is not None
    assert row["_markets"] == ["player_pass_yds"]
    print("✓ player_row gives a QB only the Pass Yards market, never Receptions")


def test_player_row_rb_gets_rush_and_receiving_markets_when_both_clear_floor():
    player = {"id": "p1", "name": "Test RB", "position": "RB"}
    log = [{"rushing_yards": 80, "carries": 18, "targets": 4, "receptions": 3,
           "receiving_yards": 25, "_touches": 22}] * 3
    row = E.player_row(player, "KC", "LAC", "KC @ LAC", "2025-09-05", log)
    assert set(row["_markets"]) == {"player_rush_yds", "player_receptions", "player_reception_yds"}
    print("✓ player_row gives a productive RB both rushing and receiving markets")


def test_player_row_rb_with_no_targets_gets_only_rush_market():
    # Real pattern confirmed live: Devin Singletary-style early-down back with real rush volume
    # but too few targets to clear the receiving floor.
    player = {"id": "p1", "name": "Ground Only RB", "position": "RB"}
    log = [{"rushing_yards": 60, "carries": 15, "targets": 0, "receptions": 0,
           "receiving_yards": 0, "_touches": 15}] * 5
    row = E.player_row(player, "KC", "LAC", "KC @ LAC", "2025-09-05", log)
    assert row["_markets"] == ["player_rush_yds"]
    print("✓ player_row correctly excludes receiving markets for a RB with no real target volume")


def test_player_row_none_when_no_market_clears_the_floor():
    player = {"id": "p1", "name": "Deep Bench WR", "position": "WR"}
    log = [{"targets": 0, "receptions": 0, "receiving_yards": 0}] * 3
    assert E.player_row(player, "KC", "LAC", "KC @ LAC", "2025-09-05", log) is None
    print("✓ player_row returns None for a player who clears no market's rotation floor at all")


def test_player_row_none_for_unrecognized_position():
    player = {"id": "p1", "name": "Long Snapper", "position": "LS"}
    log = [{"passing_yards": 0}] * 3
    assert E.player_row(player, "KC", "LAC", "KC @ LAC", "2025-09-05", log) is None


def test_player_row_none_with_empty_game_log():
    player = {"id": "00-0033873", "name": "Patrick Mahomes", "position": "QB"}
    assert E.player_row(player, "KC", "LAC", "KC @ LAC", "2025-09-05", []) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
