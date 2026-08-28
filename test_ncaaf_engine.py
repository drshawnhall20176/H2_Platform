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


def test_player_row_handles_nan_position_without_crashing():
    # Regression guard for a real, live production crash: a roster row read back through
    # pandas' CSV round-trip (ncaaf_data.load_rosters) represents a missing "position" cell as
    # NaN (a float), not None or "". NaN is TRUTHY in Python, so the old `(player.get("position")
    # or "").upper()` idiom didn't catch it -- crashed with AttributeError calling .upper() on a
    # float. Confirmed via the real traceback: ncaaf_engine.py line 203, in player_row.
    player = {"id": "p1", "name": "Mystery Player", "team": "Ohio State", "position": float("nan")}
    row = E.player_row(player, "Ohio State", "Texas", "Texas @ Ohio State", "2026-08-29",
                       {"passing_YDS": 1000, "passing_ATT": 100}, team_games_played=5)
    assert row is None   # unknown position -> no known markets -> cleanly skipped, not a crash
    print("✓ player_row handles a NaN position value (pandas CSV round-trip) by cleanly "
         "skipping the player, not crashing with AttributeError")


def test_normalize_name_handles_nan_without_crashing():
    # Same NaN-truthiness vulnerability, same fix, applied to the name-join fallback path.
    assert E._normalize_name(float("nan")) == ""
    assert E._normalize_name(None) == ""
    assert E._normalize_name("Star QB") == "star qb"
    print("✓ _normalize_name handles NaN and None without crashing, alongside real names")


def test_stats_by_id_and_name_skips_rows_with_nan_identity_fields():
    import ncaaf_data as ND
    from unittest.mock import patch
    fake_stats = [
        {"season": 2025, "player_id": "p1", "player": "Real Player", "team": "Ohio State",
         "passing_YDS": 1000},
        {"season": 2025, "player_id": float("nan"), "player": float("nan"), "team": "Ohio State",
         "passing_YDS": 500},
    ]
    with patch.object(ND, "load_player_stats", return_value=fake_stats):
        by_id, by_name_team = E._stats_by_id_and_name(2025)
    assert "p1" in by_id
    assert len(by_id) == 1   # the NaN player_id row correctly excluded, not stored under "nan"
    assert (E._normalize_name("Real Player"), "Ohio State") in by_name_team
    print("✓ _stats_by_id_and_name excludes rows with NaN identity fields instead of indexing "
         "them under a bogus 'nan' key")


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


def test_build_slate_produces_real_rows_when_schedule_spans_both_target_and_fallback_years():
    # End-to-end regression guard for the real bug a live user report surfaced: Best Bets showed
    # "No plays for this date" and Command Center showed real games but zero model plays. Root
    # cause: refresh_schedule used to pull only the target year, but stats had fallen back to a
    # prior year -- _team_games_played_for_stats_season needed that prior year's own schedule to
    # count its real completed games, and it simply wasn't cached. Reproduces the exact live
    # state (schedule cache spans BOTH years, matching the fixed refresh_schedule's own new
    # multi-year behavior) and confirms real rows now come out the other end.
    schedule_2026 = [{"id": 1, "season": 2026, "week": 1, "start_date": "2026-08-29T19:30:00Z",
                      "completed": False, "home_team": "Ohio State", "away_team": "Texas",
                      "home_id": 1, "away_id": 2}]
    schedule_2025 = _season_schedule(2025, "Ohio State", "Foe", 12, completed=True)
    roster = [{"id": "p1", "name": "Star QB", "team": "Ohio State", "position": "QB"}]
    stats = [{"season": 2025, "player_id": "p1", "player": "Star QB", "team": "Ohio State",
             "passing_YDS": 3600, "passing_ATT": 360}]

    with patch.object(ND, "load_schedule", return_value=schedule_2026 + schedule_2025), \
        patch.object(ND, "load_rosters", return_value=roster), \
        patch.object(ND, "load_player_stats", return_value=stats):
        rows, meta = E.build_slate("2026-08-29")

    assert len(meta) == 1   # the real 2026 game
    assert len(rows) == 1   # NOT zero -- this is the exact bug being guarded against
    assert rows[0]["PassYds"] == 300.0
    assert rows[0]["_team_games_played"] == 12
    print("✓ build_slate produces real rows when the schedule cache spans both the target and "
         "fallback years, reproducing and confirming the fix for a real reported bug")


def test_player_recent_games_respects_strictly_before_and_n():
    fake_game_rows = [
        {"player_id": "p1", "week": 1, "passing_YDS": 200},
        {"player_id": "p1", "week": 2, "passing_YDS": 250},
        {"player_id": "p1", "week": 3, "passing_YDS": 300},
        {"player_id": "p1", "week": 5, "passing_YDS": 999},   # a future week -- must be excluded
        {"player_id": "p2", "week": 2, "passing_YDS": 111},   # a different player -- must be excluded
    ]
    with patch.object(ND, "load_player_game_stats", return_value=fake_game_rows):
        recent = E.player_recent_games("p1", before_week=4, n=2)
    assert len(recent) == 2
    assert [r["week"] for r in recent] == [3, 2]   # most recent first, only 2 (n=2), week 5 excluded
    print("✓ player_recent_games returns only this player's games strictly before the given "
         "week, most recent first, capped at n")


def test_player_recent_games_empty_when_no_cache():
    with patch.object(ND, "load_player_game_stats", return_value=[]):
        assert E.player_recent_games("p1", before_week=5) == []
    print("✓ player_recent_games returns [] gracefully when there's no per-game cache yet")


def test_get_player_results_translates_cfbd_columns_to_shared_market_stat_keys():
    # Regression guard for a real bug caught before it shipped: retro.py's shared MARKET_STAT
    # dict expects "passing_yards"/"rushing_yards"/"receptions"/"receiving_yards" for these exact
    # display market names (NFL's own key convention, reused since NCAAF shares NFL's display
    # names) -- NOT CFBD's raw "passing_YDS" etc. Returning results under the raw CFBD keys would
    # have made every single NCAAF play silently fail to grade even with real data present.
    schedule = [{"id": 1, "season": 2025, "week": 6, "start_date": "2025-10-11T19:30:00Z",
                "completed": True, "home_team": "Ohio State", "away_team": "Texas",
                "home_id": 1, "away_id": 2, "venue": "X", "neutral_site": False}]
    game_rows = [{"player_id": "p1", "week": 6, "passing_YDS": 312, "receiving_REC": None}]

    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        results = E.get_player_results("2025-10-11")

    assert "p1" in results
    assert results["p1"]["passing_yards"] == 312.0     # translated key, matching retro.MARKET_STAT
    assert "passing_YDS" not in results["p1"]            # the raw CFBD key must NOT leak through
    assert "receptions" not in results["p1"]              # None value correctly excluded, not 0.0
    print("✓ get_player_results translates CFBD's real column names into the shared MARKET_STAT "
         "vocabulary retro.py's grading actually looks up")


def test_get_player_results_empty_for_unresolvable_date():
    with patch.object(ND, "load_schedule", return_value=[]):
        assert E.get_player_results("2025-10-11") == {}
    print("✓ get_player_results returns {} gracefully when no schedule/week can be resolved")


def _dh_schedule(n_weeks=3):
    return [{"id": 1000 + i, "season": 2025, "week": i, "start_date": f"2025-09-{i:02d}T19:30:00Z",
            "completed": True, "home_team": "Ohio State", "away_team": "Foe", "home_id": 1, "away_id": 9}
           for i in range(1, n_weeks + 1)]


def test_get_team_allowed_stats_averages_correctly_across_games():
    game_rows = [
        {"game_id": 1, "week": 1, "team": "Team A", "opponent_team": "Weak Defense",
         "passing_YDS": 300, "rushing_YDS": 100},
        {"game_id": 2, "week": 2, "team": "Team B", "opponent_team": "Weak Defense",
         "passing_YDS": 350, "rushing_YDS": 120},
    ]
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        allowed = E.get_team_allowed_stats("Weak Defense", "2025-09-20")
    assert allowed["passing_YDS"] == 325.0    # (300+350)/2
    assert allowed["rushing_YDS"] == 110.0    # (100+120)/2
    print("✓ get_team_allowed_stats correctly averages what a defense allowed across real games")


def test_get_team_allowed_stats_empty_for_no_games():
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=[]):
        assert E.get_team_allowed_stats("Nobody", "2025-09-20") == {}
    print("✓ get_team_allowed_stats returns {} gracefully with no per-game data yet")


def test_league_average_allowed_isolates_each_defense_not_both_sides_of_a_game():
    # Regression guard for a real bug caught by testing, not assumed correct: grouping by
    # game_id ALONE sums BOTH teams' offensive output in a game into one number -- double-
    # counting a game as if it were a single "defense allowed" data point, when it's actually
    # TWO (one per team's defense that day). Must group by (opponent_team, game_id).
    game_rows = [
        {"game_id": 1, "week": 1, "team": "Team A", "opponent_team": "Weak Defense", "passing_YDS": 300},
        {"game_id": 1, "week": 1, "team": "Weak Defense", "opponent_team": "Team A", "passing_YDS": 50},
        {"game_id": 2, "week": 2, "team": "Team B", "opponent_team": "Weak Defense", "passing_YDS": 350},
        {"game_id": 3, "week": 2, "team": "Team C", "opponent_team": "Strong Defense", "passing_YDS": 150},
    ]
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        avg = E.get_league_average_pass_yards_allowed("2025-09-20")
    # 4 real (defense, game) data points: 300, 50, 350, 150 -> mean 212.5, NOT (350+350+150)/3
    assert avg == 212.5, f"expected 212.5 (correct per-defense isolation), got {avg}"
    print("✓ league-average-allowed isolates each defense's own performance per game, not both "
         "teams' combined offensive output")


def test_league_average_rush_yards_allowed_uses_rushing_column():
    game_rows = [
        {"game_id": 1, "week": 1, "team": "Team A", "opponent_team": "D1", "rushing_YDS": 100},
        {"game_id": 2, "week": 2, "team": "Team B", "opponent_team": "D2", "rushing_YDS": 200},
    ]
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        avg = E.get_league_average_rush_yards_allowed("2025-09-20")
    assert avg == 150.0
    print("✓ get_league_average_rush_yards_allowed reads the rushing column, not passing")


# ----------------------------------------------------------------- get_player_history_vs_opponent
def test_get_player_history_vs_opponent_filters_by_real_opponent_and_week():
    schedule = _dh_schedule(n_weeks=5)
    game_rows = [
        {"player_id": "p1", "week": 1, "opponent_team": "Rival U", "passing_YDS": 200},
        {"player_id": "p1", "week": 2, "opponent_team": "Someone Else", "passing_YDS": 999},
        {"player_id": "p1", "week": 4, "opponent_team": "Rival U", "passing_YDS": 999},   # not-yet-played (>= resolved week) -- excluded
    ]
    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        games = E.get_player_history_vs_opponent("p1", "Rival U", "2025-09-04")   # resolves to week 3
    assert len(games) == 1
    assert games[0]["passing_YDS"] == 200
    print("✓ get_player_history_vs_opponent isolates the real opponent, excludes other opponents and not-yet-played weeks")


def test_get_player_history_vs_opponent_honestly_empty_for_first_ever_meeting():
    schedule = _dh_schedule(n_weeks=5)
    game_rows = [{"player_id": "p1", "week": 1, "opponent_team": "Someone Else", "passing_YDS": 200}]
    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        assert E.get_player_history_vs_opponent("p1", "Never Played Them", "2025-09-30") == []
    print("✓ get_player_history_vs_opponent honestly returns [] for an opponent never actually played, not a guess")


# ----------------------------------------------------------------- get_team_rest_info
def test_get_team_rest_info_computes_real_days_since_last_game():
    schedule = _season_schedule(2025, "Ohio State", "Rival", 3)
    with patch.object(ND, "load_schedule", return_value=schedule):
        info = E.get_team_rest_info("Ohio State", "2025-09-10")   # last game was week 2 = 2025-09-02
    assert info["rest_days"] == 8   # 09-10 minus 09-02
    assert info["last_opp_name"] == "Rival"
    print("✓ get_team_rest_info correctly computes real days-since-last-game from real start_date values")


def test_get_team_rest_info_empty_before_any_games():
    schedule = _season_schedule(2025, "Ohio State", "Rival", 3)
    with patch.object(ND, "load_schedule", return_value=schedule):
        info = E.get_team_rest_info("Ohio State", "2025-09-01")   # before week 1 has even happened
    assert info["rest_days"] is None
    assert info["last_game_date"] is None
    print("✓ get_team_rest_info honestly returns None (never a fabricated value) before any real game has been played")


def test_get_team_rest_info_never_returns_a_fake_short_week_flag():
    # A real, deliberate omission this function's own docstring explains -- confirms it doesn't
    # silently reappear as a guessed value.
    schedule = _season_schedule(2025, "Ohio State", "Rival", 3)
    with patch.object(ND, "load_schedule", return_value=schedule):
        info = E.get_team_rest_info("Ohio State", "2025-09-10")
    assert "is_short_week" not in info, (
        "is_short_week must stay genuinely absent -- NFL's own definition has no honest FBS "
        "equivalent, so fabricating one here would be a guess dressed up as a signal")
    print("✓ get_team_rest_info never reintroduces a fabricated is_short_week flag")


# ----------------------------------------------------------------- TD-allowed functions
def test_get_team_passing_tds_allowed_averages_correctly():
    game_rows = [
        {"game_id": 1, "week": 1, "opponent_team": "Weak Defense", "passing_TD": 3},
        {"game_id": 2, "week": 2, "opponent_team": "Weak Defense", "passing_TD": 1},
    ]
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        avg = E.get_team_passing_tds_allowed("Weak Defense", "2025-09-20")
    assert avg == 2.0
    print("✓ get_team_passing_tds_allowed correctly averages real passing TDs allowed across real games")


def test_get_team_rushing_and_total_tds_allowed():
    game_rows = [
        {"game_id": 1, "week": 1, "opponent_team": "Weak Defense", "rushing_TD": 2, "receiving_TD": 1},
        {"game_id": 2, "week": 2, "opponent_team": "Weak Defense", "rushing_TD": 0, "receiving_TD": 3},
    ]
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        rushing_avg = E.get_team_rushing_tds_allowed("Weak Defense", "2025-09-20")
        total_avg = E.get_team_tds_allowed("Weak Defense", "2025-09-20")
    assert rushing_avg == 1.0   # (2+0)/2
    assert total_avg == 3.0     # rushing (1.0) + receiving ((1+3)/2=2.0), NOT rushing+passing
    print("✓ get_team_tds_allowed correctly sums real rushing + receiving (not passing), matching NFL's own real convention")


def test_get_team_tds_allowed_honest_none_for_no_games():
    with patch.object(ND, "load_schedule", return_value=_dh_schedule()), \
        patch.object(ND, "load_player_game_stats", return_value=[]):
        assert E.get_team_tds_allowed("Nobody", "2025-09-20") is None
        assert E.get_team_passing_tds_allowed("Nobody", "2025-09-20") is None
    print("✓ TD-allowed functions honestly return None (never a fabricated 0.0) with no real per-game data yet")


def test_get_team_td_stat_allowed_respects_recent_n_window():
    game_rows = [
        {"game_id": 1, "week": 1, "opponent_team": "D1", "passing_TD": 5},
        {"game_id": 2, "week": 2, "opponent_team": "D1", "passing_TD": 1},
        {"game_id": 3, "week": 3, "opponent_team": "D1", "passing_TD": 1},
    ]
    with patch.object(ND, "load_schedule", return_value=_dh_schedule(n_weeks=4)), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        recent = E.get_team_passing_tds_allowed("D1", "2025-09-25", n=2)   # last 2 of the 3 real games
    assert recent == 1.0   # weeks 2+3 only: (1+1)/2, excludes week 1's real 5
    print("✓ TD-allowed functions correctly respect a real n= recent-games window, not always the whole season")


def test_get_player_season_games_uses_player_recent_games_with_resolved_week():
    schedule = _dh_schedule(n_weeks=5)
    game_rows = [
        {"player_id": "p1", "week": 1, "passing_YDS": 200},
        {"player_id": "p1", "week": 3, "passing_YDS": 300},
        {"player_id": "p1", "week": 5, "passing_YDS": 999},   # resolves as "current" week -- excluded
    ]
    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_player_game_stats", return_value=game_rows):
        games = E.get_player_season_games("p1", "2025-09-30")   # resolves to the last week (5) via fallback
    weeks = sorted(g["week"] for g in games)
    assert weeks == [1, 3]   # strictly before week 5, most-recent-first internally
    print("✓ get_player_season_games resolves the right week and excludes that week's own game")


# ----------------------------------------------------------------- get_team_recent_scoring
def test_get_team_recent_scoring_uses_ncaaf_own_field_names():
    # REAL, CONFIRMED DISTINCTION from NFL's identical-looking function: NCAAF's cached schedule
    # uses home_points/away_points and a real "completed" boolean -- NOT NFL's home_score/
    # away_score. This test fails loudly if that distinction ever gets silently blurred.
    schedule = [
        {"week": 1, "home_team": "Georgia", "away_team": "Alabama",
         "home_points": 27, "away_points": 24, "completed": True},
        {"week": 2, "home_team": "Tennessee", "away_team": "Georgia",
         "home_points": 10, "away_points": 31, "completed": True},
        {"week": 3, "home_team": "Georgia", "away_team": "Auburn",
         "home_points": None, "away_points": None, "completed": False},
    ]
    form = E.get_team_recent_scoring("Georgia", schedule, before_week=3)
    assert form["season_games"] == 2   # week 3 not completed yet -- excluded
    assert form["season_avg"] == 29.0   # (27 + 31) / 2
    print("✓ get_team_recent_scoring reads NCAAF's own real field names, excludes incomplete games")


def test_get_team_recent_scoring_none_when_no_games_played_yet():
    schedule = [{"week": 3, "home_team": "Georgia", "away_team": "Alabama",
                "home_points": 27, "away_points": 24, "completed": True}]
    form = E.get_team_recent_scoring("Georgia", schedule, before_week=1)
    assert form is None
    print("✓ get_team_recent_scoring returns honest None when this team has no completed games "
         "before the given week yet")


# ----------------------------------------------------------------- compute_drive_points
def test_compute_drive_points_normal_alternating_drives():
    # A real, ordinary sequence: Team A scores a TD (0->7), Team B kicks a FG (0->3), Team A adds
    # another FG (7->10). Confirms the delta math is genuinely correct, not just plausible.
    drives = [
        {"drive_number": 1, "offense": "Team A", "defense": "Team B", "offense_score": 7, "defense_score": 0},
        {"drive_number": 2, "offense": "Team B", "defense": "Team A", "offense_score": 3, "defense_score": 7},
        {"drive_number": 3, "offense": "Team A", "defense": "Team B", "offense_score": 10, "defense_score": 3},
    ]
    out = E.compute_drive_points(drives)
    assert out[0]["points_this_drive"] == 7.0
    assert out[1]["points_this_drive"] == 3.0
    assert out[2]["points_this_drive"] == 3.0   # 10 - 7 (their own prior score), not 10 - 3
    assert all(d["defensive_points_this_drive"] == 0.0 for d in out)
    print("✓ compute_drive_points correctly computes real per-drive points for a normal, alternating sequence")


def test_compute_drive_points_catches_a_real_defensive_score():
    # THE real, critical edge case this function exists to handle correctly: Team B's defense
    # returns a pick-six while Team A is on offense. Team A's own drive ends in a real turnover
    # (0 points for them), but Team B's own score jumps by 7 -- attributed as a real, honest
    # defensive_points_this_drive, not silently lost.
    drives = [
        {"drive_number": 1, "offense": "Team A", "defense": "Team B", "offense_score": 0, "defense_score": 7},
    ]
    out = E.compute_drive_points(drives)
    assert out[0]["points_this_drive"] == 0.0
    assert out[0]["defensive_points_this_drive"] == 7.0
    print("✓ compute_drive_points correctly catches a real defensive/special-teams score, never silently loses it")


def test_compute_drive_points_survives_missing_data_without_corrupting_the_running_score():
    # Team A's own 2nd drive has no real offense_score on file. Their 3rd real drive must still
    # compute correctly against their real, LAST KNOWN score (7 from drive 1), not against a
    # corrupted or reset running total.
    drives = [
        {"drive_number": 1, "offense": "Team A", "defense": "Team B", "offense_score": 7, "defense_score": 0},
        {"drive_number": 2, "offense": "Team A", "defense": "Team B", "offense_score": None, "defense_score": 0},
        {"drive_number": 3, "offense": "Team A", "defense": "Team B", "offense_score": 14, "defense_score": 0},
    ]
    out = E.compute_drive_points(drives)
    assert out[1]["points_this_drive"] is None   # honest None, not a guessed 0
    assert out[2]["points_this_drive"] == 7.0    # 14 - 7 (drive 1's real known score), NOT 14 - 0
    print("✓ compute_drive_points survives a real missing value without corrupting the running score for later drives")


def test_compute_drive_points_sorts_by_drive_number_not_input_order():
    drives = [
        {"drive_number": 2, "offense": "Team B", "defense": "Team A", "offense_score": 3, "defense_score": 7},
        {"drive_number": 1, "offense": "Team A", "defense": "Team B", "offense_score": 7, "defense_score": 0},
    ]
    out = E.compute_drive_points(drives)
    assert out[0]["drive_number"] == 1 and out[1]["drive_number"] == 2
    print("✓ compute_drive_points correctly sorts by drive_number regardless of real input order")


# ----------------------------------------------------------------- _outcome_for_drive
def test_outcome_for_drive_buckets_touchdowns_correctly():
    # The real, deliberate 6/7/8 ambiguity this function's own docstring names directly.
    assert E._outcome_for_drive(7.0, 0.0) == "touchdown"
    assert E._outcome_for_drive(6.0, 0.0) == "touchdown"   # missed/blocked PAT
    assert E._outcome_for_drive(8.0, 0.0) == "touchdown"   # made 2pt conversion
    print("✓ _outcome_for_drive correctly buckets all three real touchdown point values (6/7/8)")


def test_outcome_for_drive_buckets_field_goal_safety_and_no_score():
    assert E._outcome_for_drive(3.0, 0.0) == "field_goal"
    assert E._outcome_for_drive(2.0, 0.0) == "safety"
    assert E._outcome_for_drive(0.0, 0.0) == "no_score"
    print("✓ _outcome_for_drive correctly buckets field goal, safety, and no-score drives")


def test_outcome_for_drive_defensive_score_overrides_offense_points():
    assert E._outcome_for_drive(0.0, 7.0) == "defensive_score"
    print("✓ _outcome_for_drive correctly classifies a real defensive score as its own real bucket")


def test_outcome_for_drive_honest_none_when_points_unknown():
    assert E._outcome_for_drive(None, None) is None
    assert E._outcome_for_drive(None, 0.0) is None
    print("✓ _outcome_for_drive honestly returns None (never a guessed bucket) when the real point value isn't known")


# ----------------------------------------------------------------- get_team_drive_outcomes
def test_get_team_drive_outcomes_full_integration():
    schedule = _dh_schedule(n_weeks=5)
    drive_rows = [
        {"game_id": 1, "week": 1, "drive_number": 1, "offense": "Ohio State", "defense": "Rival",
        "offense_score": 7, "defense_score": 0},
        {"game_id": 1, "week": 1, "drive_number": 2, "offense": "Ohio State", "defense": "Rival",
        "offense_score": 10, "defense_score": 0},
        {"game_id": 1, "week": 1, "drive_number": 3, "offense": "Rival", "defense": "Ohio State",
        "offense_score": 7, "defense_score": 10},   # a different team's own offense -- must be excluded
    ]
    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_drives", return_value=drive_rows):
        outcomes = E.get_team_drive_outcomes("Ohio State", "2025-09-30")   # after week 1
    assert outcomes == ["touchdown", "field_goal"]   # 7-0=7 (TD), 10-7=3 (FG); Rival's own drive excluded
    print("✓ get_team_drive_outcomes correctly isolates one real team's own offensive drives and buckets them")


def test_get_team_drive_outcomes_honest_empty_before_any_games():
    schedule = _dh_schedule(n_weeks=5)
    with patch.object(ND, "load_schedule", return_value=schedule), \
        patch.object(ND, "load_drives", return_value=[]):
        assert E.get_team_drive_outcomes("Ohio State", "2025-09-01") == []
    print("✓ get_team_drive_outcomes honestly returns [] before any real drives are on file")


# ============================================================================ Per-team stats-season fallback
# BUILT DIRECTLY ON REQUEST, fixing a real, live-confirmed bug: a real refresh run against CFBD
# returned 1,082 real player-stat rows for season=2026, but every one of them belonged to one of
# 37 FCS/D-II programs whose seasons start earlier than FBS's own Week 1 -- ZERO overlap against
# the real roster's 138 FBS teams. The old "is the whole file empty" fallback never fired, since
# the file wasn't empty, and the whole real slate came back with 0 rows. See ncaaf_data.
# refresh_player_season_stats' own docstring for the full story.

def test_stats_by_id_and_name_prefers_target_season_over_prior_when_both_exist():
    fake_stats = [
        {"season": 2025, "player_id": "1", "player": "Returning Player", "team": "Georgia",
         "passing_YDS": 3200},
        {"season": 2026, "player_id": "1", "player": "Returning Player", "team": "Georgia",
         "passing_YDS": 400},
    ]
    with patch.object(ND, "load_player_stats", return_value=fake_stats):
        by_id, by_name_team = E._stats_by_id_and_name(2026)
    assert by_id["1"]["season"] == 2026
    assert by_id["1"]["passing_YDS"] == 400
    print("✓ _stats_by_id_and_name prefers the target season's own row over a prior one when both exist for the same player")


def test_stats_by_id_and_name_falls_back_to_prior_season_when_target_missing():
    fake_stats = [
        {"season": 2025, "player_id": "1", "player": "FBS Player", "team": "Alabama",
         "passing_YDS": 3200},
    ]
    with patch.object(ND, "load_player_stats", return_value=fake_stats):
        by_id, by_name_team = E._stats_by_id_and_name(2026)
    assert by_id["1"]["season"] == 2025
    assert by_id["1"]["passing_YDS"] == 3200
    print("✓ _stats_by_id_and_name genuinely falls back to a prior season's row when the target season has none for that player")


def test_stats_by_id_and_name_never_leaks_a_future_season_lookahead_bias():
    # THE real, deliberate fix over this function's own prior version, which accepted `season`
    # but never used it at all: a query for season=2025 (the 2025-baseline toggle's own real use
    # case) must never surface a season=2026 row, even if the cache happens to contain one.
    fake_stats = [
        {"season": 2025, "player_id": "1", "player": "X", "team": "Georgia", "passing_YDS": 3000},
        {"season": 2026, "player_id": "1", "player": "X", "team": "Georgia", "passing_YDS": 50},
    ]
    with patch.object(ND, "load_player_stats", return_value=fake_stats):
        by_id, by_name_team = E._stats_by_id_and_name(2025)
    assert by_id["1"]["season"] == 2025, (
        "querying for season=2025 must never leak a real season=2026 row -- a genuine lookahead-bias violation")
    assert by_id["1"]["passing_YDS"] == 3000
    print("✓ _stats_by_id_and_name never leaks a future season's row into a query for an earlier one")


def test_team_stats_season_resolves_per_team_not_globally():
    # THE direct regression guard for the real live bug: two teams playing the same real week,
    # one with real target-season data (FCS team whose season already started), one without
    # (major FBS team not yet underway) -- each team's OWN resolution must be independent.
    fake_stats = [
        {"season": 2026, "player_id": "1", "player": "FCS Player", "team": "Elon", "passing_YDS": 500},
        {"season": 2025, "player_id": "2", "player": "FBS Player", "team": "Alabama", "passing_YDS": 3000},
    ]
    roster = {
        "Elon": [{"id": 1, "name": "FCS Player", "team": "Elon"}],
        "Alabama": [{"id": 2, "name": "FBS Player", "team": "Alabama"}],
        "Georgia": [{"id": 3, "name": "No Data Guy", "team": "Georgia"}],
    }
    with patch.object(ND, "load_player_stats", return_value=fake_stats):
        stats_by_id, stats_by_name_team = E._stats_by_id_and_name(2026)
        id_join_misses = 0

        def _lookup(player):
            nonlocal id_join_misses
            pid = player.get("id")
            if pid is not None and str(pid) in stats_by_id:
                return stats_by_id[str(pid)]
            return stats_by_name_team.get((E._normalize_name(player.get("name")), player.get("team")))

        def _team_stats_season(team):
            for p in roster.get(team, []):
                row = _lookup(p)
                if row is not None:
                    return row.get("season")
            return None

        assert _team_stats_season("Elon") == 2026
        assert _team_stats_season("Alabama") == 2025
        assert _team_stats_season("Georgia") is None
    print("✓ per-team stats-season resolution is genuinely independent per team, not one global value for the whole slate")


def test_build_slate_correctly_handles_a_real_mixed_season_scenario():
    # THE full, real, end-to-end regression guard for the exact live bug -- one team with real
    # target-season data, one team requiring a real prior-season fallback (with that season's
    # own real schedule needed for the games-played denominator), verified together in one real
    # build_slate call, not just each piece tested in isolation.
    #
    # Elon gets a real, PRIOR, completed 2026 game (week 0) before the week-1 matchup being
    # queried -- the same real-world shape the live bug's own data had: FCS programs like Elon
    # genuinely start their season before FBS's own week 1, so their real week-1-and-earlier
    # stats already exist by the time this specific week-1 slate is being built. Omitting this
    # prior game would make team_games_played_before(week=1) genuinely, correctly resolve to 0
    # for Elon regardless of any fix here -- a real games-played-denominator gap, not a stats-
    # season resolution bug, and testing the wrong thing if left in by accident.
    schedule_2026 = [
        {"id": 0, "season": 2026, "week": 0, "start_date": "2026-08-22T19:00:00Z",
        "completed": True, "home_team": "Elon", "away_team": "Warmup Opponent",
        "home_id": 1, "away_id": 9},
        {"id": 1, "season": 2026, "week": 1, "start_date": "2026-08-29T19:00:00Z",
        "completed": False, "home_team": "Elon", "away_team": "Furman",
        "home_id": 1, "away_id": 2},
    ]
    schedule_2025 = _season_schedule(2025, "Furman", "Rival", 10, completed=True)
    combined_schedule = schedule_2026 + schedule_2025

    roster = [
        {"id": 1, "name": "Elon QB", "team": "Elon", "position": "QB"},
        {"id": 2, "name": "Furman QB", "team": "Furman", "position": "QB"},
    ]
    stats = [
        {"season": 2026, "player_id": "1", "player": "Elon QB", "team": "Elon",
         "passing_YDS": 300, "passing_ATT": 40},
        {"season": 2025, "player_id": "2", "player": "Furman QB", "team": "Furman",
         "passing_YDS": 2500, "passing_ATT": 300},
    ]
    with patch.object(ND, "load_schedule", return_value=combined_schedule), \
        patch.object(ND, "load_rosters", return_value=roster), \
        patch.object(ND, "load_player_stats", return_value=stats), \
        patch.object(ND, "load_player_game_stats", return_value=[]):
        rows, meta = E.build_slate("2026-08-29")

    assert len(rows) == 2, f"expected both QBs to clear the rotation floor, got {len(rows)}: {rows}"
    by_team = {r["Team"]: r for r in rows}
    assert by_team["Elon"]["_stats_row"]["season"] == 2026
    assert by_team["Furman"]["_stats_row"]["season"] == 2025
    # Elon QB: 300 real yards over their 1 real, prior, completed 2026 game (week 0) = 300.0/game.
    # Furman QB: 2500 real yards over the real 10-game 2025 season = 250.0/game.
    assert by_team["Elon"]["PassYds"] == 300.0
    assert by_team["Furman"]["PassYds"] == 250.0
    print("✓ build_slate correctly produces real rows for BOTH a target-season team and a prior-season-fallback team in the same real slate")


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
