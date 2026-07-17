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


def test_player_recent_games_playoff_week_pulls_from_regular_season_tail():
    # Confirmed live during the go-live review pass: playoff weeks (19 Wild Card, 20 Divisional,
    # 21 Conference, 22 Super Bowl) are numbered SEQUENTIALLY after the regular season's 1-18, not
    # colliding with it or restarting — so building a Wild Card week 19 slate should pull recent
    # form from the regular season's actual last games (weeks 14-18), with no special-casing
    # needed for the boundary. This locks that real behavior in as a regression, not just a
    # one-off fact noted about the external data.
    df = pd.DataFrame([{"player_id": "p1", "week": wk, "passing_yards": 200 + wk} for wk in range(14, 19)])
    games = E.player_recent_games(df, "p1", before_week=19, n=5)   # week 19 = Wild Card
    assert len(games) == 5
    assert [g["week"] for g in games] == [18, 17, 16, 15, 14]   # most recent regular-season week first
    print("✓ player_recent_games correctly pulls a Wild Card week's recent form from the regular season's tail")


# ----------------------------------------------------------------- _infer_season / get_player_results
def test_infer_season_regular_season_month():
    assert E._infer_season("2025-10-13") == 2025


def test_infer_season_january_belongs_to_prior_years_season():
    # NFL's season "year" runs Sep-Feb — a January date is the PRIOR year's season's playoffs.
    assert E._infer_season("2026-01-16") == 2025


def test_infer_season_none_for_bad_date():
    assert E._infer_season("not-a-date") is None


def test_get_player_results_returns_whole_week_not_just_literal_date(monkeypatch):
    # THE actual bug this exists to fix: Retrospective crashed because get_player_results didn't
    # exist at all (AttributeError). Once added, it ALSO has to return the WHOLE resolved week's
    # results, not just games on the literal calendar date — build_slate(date_str) already
    # produces a whole week's slate, so grading needs the matching whole week's results, or most
    # of the week's Thursday/Monday-game players would silently show "no result".
    fake_sched_df = pd.DataFrame([
        {"game_id": "2025_06_A_B", "week": 6, "gameday": "2025-10-09", "home_team": "B",
        "away_team": "A", "home_score": 20, "away_score": 17, "home_rest": 7, "away_rest": 7},
        {"game_id": "2025_06_C_D", "week": 6, "gameday": "2025-10-13", "home_team": "D",
        "away_team": "C", "home_score": 24, "away_score": 21, "home_rest": 7, "away_rest": 7},
    ])
    fake_weekly_df = pd.DataFrame([
        {"player_id": "p_thu", "week": 6, "passing_yards": 300, "rushing_yards": 0,
        "receptions": 0, "receiving_yards": 0},   # Thursday game (2025-10-09)
        {"player_id": "p_mon", "week": 6, "passing_yards": 0, "rushing_yards": 80,
        "receptions": 0, "receiving_yards": 0},   # Monday game (2025-10-13)
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched_df))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly_df))
    # Query using the Thursday game's own date — should still return the Monday player's result too
    results = E.get_player_results("2025-10-09")
    assert "p_thu" in results and "p_mon" in results
    assert results["p_mon"]["rushing_yards"] == 80.0
    print("✓ get_player_results returns the WHOLE resolved week, not just games on the literal date")


def test_get_player_results_empty_for_unplayed_week(monkeypatch):
    fake_sched_df = pd.DataFrame([{"game_id": "2026_01_A_B", "week": 1, "gameday": "2026-09-09",
                                  "home_team": "B", "away_team": "A", "home_score": None,
                                  "away_score": None, "home_rest": 7, "away_rest": 7}])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched_df))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(pd.DataFrame()))
    assert E.get_player_results("2026-09-09") == {}
    print("✓ get_player_results returns empty (not an error) for a week that hasn't been played yet")


def test_get_player_results_skips_rows_with_no_player_id(monkeypatch):
    fake_weekly_df = pd.DataFrame([
        {"player_id": "", "week": 6, "passing_yards": 100},
        {"player_id": "p1", "week": 6, "passing_yards": 200, "rushing_yards": 0,
        "receptions": 0, "receiving_yards": 0},
    ])
    fake_sched_df = pd.DataFrame([{"game_id": "2025_06_A_B", "week": 6, "gameday": "2025-10-13",
                                  "home_team": "B", "away_team": "A", "home_score": 1,
                                  "away_score": 1, "home_rest": 7, "away_rest": 7}])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched_df))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly_df))
    results = E.get_player_results("2025-10-13")
    assert list(results.keys()) == ["p1"]
    print("✓ get_player_results correctly skips rows with no player_id")


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


# ----------------------------------------------------------------- Matchup Lab support
def test_team_abbrs_from_meta_is_identity_for_nfl():
    # NFL's team_id already IS the ESPN/nflverse abbreviation ("KC"), unlike ESPN basketball's
    # numeric ids needing a real lookup — so this is correctly a passthrough, not a bug.
    meta = [{"home_id": "KC", "away_id": "LAC"}, {"home_id": "PHI", "away_id": "DAL"}]
    assert E.team_abbrs_from_meta(meta) == {"KC": "KC", "LAC": "LAC", "PHI": "PHI", "DAL": "DAL"}


def _fake_weekly(rows):
    return pd.DataFrame(rows)


def test_get_player_season_games_returns_full_season_most_recent_first(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 6, "gameday": "2025-10-13",
                               "home_team": "B", "away_team": "A", "home_score": 1,
                               "away_score": 1, "home_rest": 7, "away_rest": 7}])
    fake_weekly = _fake_weekly([
        {"player_id": "p1", "week": w, "passing_yards": 200 + w} for w in range(1, 6)])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly))
    games = E.get_player_season_games("p1", "2025-10-13")
    assert len(games) == 5
    assert games[0]["week"] == 5   # most recent first
    print("✓ get_player_season_games returns the full season so far, most recent first")


def test_get_player_history_vs_opponent_filters_to_that_opponent_only(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 6, "gameday": "2025-10-13",
                               "home_team": "B", "away_team": "A", "home_score": 1,
                               "away_score": 1, "home_rest": 7, "away_rest": 7}])
    fake_weekly = _fake_weekly([
        {"player_id": "p1", "week": 2, "opponent_team": "LV", "passing_yards": 250},
        {"player_id": "p1", "week": 4, "opponent_team": "DEN", "passing_yards": 300},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly))
    h2h_lv = E.get_player_history_vs_opponent("p1", "LV", "2025-10-13")
    assert len(h2h_lv) == 1 and h2h_lv[0]["week"] == 2
    h2h_none = E.get_player_history_vs_opponent("p1", "SEA", "2025-10-13")
    assert h2h_none == []   # honest empty — the common case for most NFL matchups
    print("✓ get_player_history_vs_opponent correctly filters to games against that exact opponent")


def test_get_team_allowed_stats_averages_across_games_grouped_by_week(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 6, "gameday": "2025-10-13",
                               "home_team": "B", "away_team": "A", "home_score": 1,
                               "away_score": 1, "home_rest": 7, "away_rest": 7}])
    # Two players facing "KC" in week 1 (same game -> sum to the team total that week), one
    # player facing "KC" in week 2 -> average across the TWO GAMES, not across all player rows.
    fake_weekly = _fake_weekly([
        {"player_id": "p1", "week": 1, "opponent_team": "KC", "passing_yards": 150,
        "rushing_yards": 0, "receptions": 0, "receiving_yards": 0},
        {"player_id": "p2", "week": 1, "opponent_team": "KC", "passing_yards": 0,
        "rushing_yards": 50, "receptions": 0, "receiving_yards": 0},
        {"player_id": "p3", "week": 2, "opponent_team": "KC", "passing_yards": 250,
        "rushing_yards": 60, "receptions": 0, "receiving_yards": 0},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly))
    allowed = E.get_team_allowed_stats("KC", "2025-10-13", n=None)
    # week 1 total: 150 pass, 50 rush. week 2 total: 250 pass, 60 rush. avg across 2 games:
    assert allowed["passing_yards"] == 200.0    # avg(150, 250)
    assert allowed["rushing_yards"] == 55.0     # avg(50, 60)
    print("✓ get_team_allowed_stats correctly groups by game/week before averaging, not by player row")


def test_get_team_allowed_stats_n_limits_to_most_recent_games(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 10, "gameday": "2025-11-10",
                               "home_team": "B", "away_team": "A", "home_score": 1,
                               "away_score": 1, "home_rest": 7, "away_rest": 7}])
    fake_weekly = _fake_weekly([
        {"player_id": "p1", "week": w, "opponent_team": "KC", "passing_yards": w * 10,
        "rushing_yards": 0, "receptions": 0, "receiving_yards": 0} for w in range(1, 6)])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly))
    recent2 = E.get_team_allowed_stats("KC", "2025-11-10", n=2)
    season = E.get_team_allowed_stats("KC", "2025-11-10", n=None)
    assert recent2["passing_yards"] == 45.0   # avg(week4=40, week5=50)
    assert season["passing_yards"] == 30.0    # avg(10,20,30,40,50)
    assert recent2 != season                  # n limits recency, genuinely differs from the full season
    print("✓ get_team_allowed_stats' n parameter correctly limits to the most recent n games")


def test_get_team_allowed_stats_empty_when_no_games_allowed(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 1, "gameday": "2025-09-04",
                               "home_team": "B", "away_team": "A", "home_score": None,
                               "away_score": None, "home_rest": 7, "away_rest": 7}])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(pd.DataFrame()))
    assert E.get_team_allowed_stats("KC", "2025-09-04") == {}


def test_get_team_rest_info_uses_real_schedule_rest_fields(monkeypatch):
    fake_sched = pd.DataFrame([
        {"game_id": "g1", "week": 5, "gameday": "2025-10-06", "home_team": "KC", "away_team": "JAX",
        "home_score": 1, "away_score": 1, "home_rest": 8, "away_rest": 8},
        {"game_id": "g2", "week": 6, "gameday": "2025-10-13", "home_team": "KC", "away_team": "LV",
        "home_score": None, "away_score": None, "home_rest": 7, "away_rest": 7},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    info = E.get_team_rest_info("KC", "2025-10-13")   # week 6, most recent PRIOR game was week 5
    assert info["rest_days"] == 8
    assert info["is_short_week"] is False
    assert info["last_opp_name"] == "JAX"
    print("✓ get_team_rest_info reads real schedule rest fields directly, no scanning needed")


def test_get_team_rest_info_flags_short_week(monkeypatch):
    fake_sched = pd.DataFrame([
        {"game_id": "g1", "week": 5, "gameday": "2025-10-09", "home_team": "KC", "away_team": "JAX",
        "home_score": 1, "away_score": 1, "home_rest": 4, "away_rest": 4},
        {"game_id": "g2", "week": 6, "gameday": "2025-10-16", "home_team": "KC", "away_team": "LV",
        "home_score": None, "away_score": None, "home_rest": 7, "away_rest": 7},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    info = E.get_team_rest_info("KC", "2025-10-16")
    assert info["is_short_week"] is True
    print("✓ get_team_rest_info correctly flags a short week (Thursday game after a Sunday one)")


def test_get_team_rest_info_empty_when_no_prior_game(monkeypatch):
    fake_sched = pd.DataFrame([
        {"game_id": "g1", "week": 1, "gameday": "2025-09-04", "home_team": "KC", "away_team": "JAX",
        "home_score": None, "away_score": None, "home_rest": 7, "away_rest": 7},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    info = E.get_team_rest_info("KC", "2025-09-04")   # week 1 — nothing before it
    assert info == {"rest_days": None, "is_short_week": False, "last_game_date": None, "last_opp_name": None}


def test_get_team_tds_allowed_groups_by_game_then_averages(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 6, "gameday": "2025-10-13",
                               "home_team": "B", "away_team": "A", "home_score": 1,
                               "away_score": 1, "home_rest": 7, "away_rest": 7}])
    fake_weekly = _fake_weekly([
        {"player_id": "p1", "week": 1, "opponent_team": "KC", "rushing_tds": 1, "receiving_tds": 0},
        {"player_id": "p2", "week": 1, "opponent_team": "KC", "rushing_tds": 0, "receiving_tds": 1},
        {"player_id": "p3", "week": 2, "opponent_team": "KC", "rushing_tds": 0, "receiving_tds": 2},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly))
    allowed = E.get_team_tds_allowed("KC", "2025-10-13", n=None)
    # week 1 total: 2 TDs (1+1). week 2 total: 2 TDs. avg across 2 games = 2.0
    assert allowed == 2.0
    print("✓ get_team_tds_allowed correctly sums per game before averaging, not per player row")


def test_get_team_tds_allowed_zero_when_no_data(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 1, "gameday": "2025-09-04",
                               "home_team": "B", "away_team": "A", "home_score": None,
                               "away_score": None, "home_rest": 7, "away_rest": 7}])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(pd.DataFrame()))
    assert E.get_team_tds_allowed("KC", "2025-09-04") == 0.0


def test_league_average_pass_yards_allowed_averages_across_all_games(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 6, "gameday": "2025-10-13",
                               "home_team": "B", "away_team": "A", "home_score": 1,
                               "away_score": 1, "home_rest": 7, "away_rest": 7}])
    # Two DIFFERENT defenses (KC, DAL), each with their own game — league average spans both.
    fake_weekly = _fake_weekly([
        {"player_id": "p1", "week": 1, "opponent_team": "KC", "passing_yards": 200},
        {"player_id": "p2", "week": 1, "opponent_team": "DAL", "passing_yards": 300},
    ])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(fake_weekly))
    avg = E.get_league_average_pass_yards_allowed("2025-10-13")
    assert avg == 250.0   # avg(200, 300) across the two real games
    print("✓ get_league_average_pass_yards_allowed correctly averages across every team's games league-wide")


def test_league_average_pass_yards_allowed_zero_when_no_data(monkeypatch):
    fake_sched = pd.DataFrame([{"game_id": "g", "week": 1, "gameday": "2025-09-04",
                               "home_team": "B", "away_team": "A", "home_score": None,
                               "away_score": None, "home_rest": 7, "away_rest": 7}])
    monkeypatch.setattr(E.nfl, "load_schedules", lambda seasons: _FakePolarsDF(fake_sched))
    monkeypatch.setattr(E.nfl, "load_player_stats",
                        lambda seasons, summary_level="week": _FakePolarsDF(pd.DataFrame()))
    assert E.get_league_average_pass_yards_allowed("2025-09-04") == 0.0


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
