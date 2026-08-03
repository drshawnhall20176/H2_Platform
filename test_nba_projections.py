"""
test_nba_projections.py — offline unit tests for nba_projections.py.

    python test_nba_projections.py     # or: pytest test_nba_projections.py
"""

import numpy as np

import nba_projections as NP
import basketball_projections as BB_P


# ----------------------------------------------------------------- market spec
def test_market_spec_is_nba_scale_not_wnba_scale():
    # NBA's default lines should be meaningfully higher than WNBA's (48-min games, faster pace).
    assert NP.default_line("player_points") == 22.5
    assert NP.default_line("player_rebounds") == 7.5
    assert NP.default_line("player_assists") == 5.5
    assert NP.default_line("player_threes") == 2.5
    print("✓ nba_projections._MARKET_SPEC uses NBA-scale default lines, not WNBA's")


def test_market_list_covers_all_four_core_markets():
    lst = NP.market_list()
    assert {mkey for mkey, _col, _disp in lst} == {"player_points", "player_rebounds",
                                                    "player_assists", "player_threes"}


def test_stat_key_for_maps_row_columns_to_game_log_keys():
    assert NP.stat_key_for("PTS") == "pts"
    assert NP.stat_key_for("FG3M") == "fg3m"


def test_default_line_none_for_unknown_market():
    assert NP.default_line("not_a_real_market") is None


# ----------------------------------------------------------------- build_trend_series
def test_build_trend_series_reverses_to_chronological_order():
    log = [{"date": "2026-01-14", "pts": 30}, {"date": "2026-01-10", "pts": 20}]
    trend = NP.build_trend_series(log)
    assert [g["date"] for g in trend] == ["2026-01-10", "2026-01-14"]


# ----------------------------------------------------------------- blowout_risk_tag / threshold
def test_blowout_risk_tag_is_aliased_to_shared_module():
    assert NP.blowout_risk_tag is BB_P.blowout_risk_tag


def test_nba_blowout_threshold_is_higher_than_wnba_default():
    # NBA's own BLOWOUT_THRESHOLD (12.0) should exceed the shared function's WNBA-tuned default (10.0)
    assert NP.BLOWOUT_THRESHOLD > 10.0
    assert NP.blowout_risk_tag(-11.0, threshold=NP.BLOWOUT_THRESHOLD) == "Competitive"
    assert NP.blowout_risk_tag(-13.0, threshold=NP.BLOWOUT_THRESHOLD) == "⚠️ Blowout risk"
    print("✓ NBA uses its own higher blowout threshold, not WNBA's 10.0 default")


# ----------------------------------------------------------------- build_projection_index / simulate
def test_simulate_player_stat_empty_when_no_values():
    rng = np.random.default_rng(1)
    assert NP.simulate_player_stat([], 100, rng).size == 0


def test_build_projection_index_covers_all_four_markets():
    row = {"Player": "A. Player", "Team": "Lakers", "GameLabel": "Celtics @ Lakers", "Opp": "Celtics",
          "_game_date": "2026-01-14T00:00Z",
          "_game_log": [{"pts": 25, "reb": 8, "ast": 7, "fg3m": 3} for _ in range(8)]}
    index = NP.build_projection_index([row], meta=[], sims=2000, seed=1)
    keys = {mkey for (_nm, mkey) in index.keys()}
    assert keys == {"player_points", "player_rebounds", "player_assists", "player_threes"}


# ----------------------------------------------------------------- build_hot_hand_board
def test_build_hot_hand_board_uses_nba_blowout_threshold():
    rows = [{"Player": "Star", "Team": "Lakers", "Opp": "Celtics",
            "GameLabel": "Celtics @ Lakers", "PTS": 25.0, "REB": 8.0, "AST": 7.0,
            "FG3M": 3.0, "_opp_id": 2, "_team_id": 13}]
    # An 11-point spread: below WNBA's 10.0 threshold it would flag, but NBA's own 12.0 threshold
    # should NOT flag it — confirms build_hot_hand_board actually uses BLOWOUT_THRESHOLD, not the
    # shared function's own bare default.
    team_spreads = {"Lakers": -11.0}
    board = NP.build_hot_hand_board(rows, opp_allowed={}, team_spreads=team_spreads)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Spread"] == -11.0
    assert pts_row["Blowout Risk"] == "Competitive"
    print("✓ build_hot_hand_board uses NBA's own (higher) blowout threshold, not the shared default")


def test_build_hot_hand_board_pace_adjustment_same_as_wnba():
    rows = [{"Player": "Star", "Team": "Lakers", "Opp": "Fast Team",
            "GameLabel": "Fast Team @ Lakers", "PTS": 25.0, "REB": 8.0, "AST": 7.0,
            "FG3M": 3.0, "_opp_id": 2, "_team_id": 13}]
    opp_allowed = {
        2: {"pts": 118.0, "reb": 44.0, "ast": 26.0, "fg3m": 14.0, "poss": 100.0},
        6: {"pts": 104.0, "reb": 40.0, "ast": 22.0, "fg3m": 10.0, "poss": 96.0},
    }
    board = NP.build_hot_hand_board(rows, opp_allowed)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Opp Allows /100 Poss"] == 118.0   # 118 / 100 * 100
    print("✓ build_hot_hand_board's pace-adjustment math matches WNBA's (copy-adapt, not a new design)")


# ----------------------------------------------------------------- shrinkage (same fix as WNBA)
def _log(pts, reb, ast, fg3m):
    return {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3m, "min": 30}


def test_default_board_no_longer_clusters_different_streak_lengths_identically():
    # Same regression as WNBA's — confirms the shrinkage fix was actually wired into
    # nba_projections.py too, not just wnba_projections.py, since this is a copy-adapt file.
    short_log = [_log(30, 8, 6, 3) for _ in range(4)]     # 4/4 games clear any reasonable line
    long_log = [_log(30, 8, 6, 3) for _ in range(10)]     # 10/10 games clear the same line
    rows = [
        {"Player": "Short Streak", "Team": "Lakers", "Opp": "Celtics",
        "GameLabel": "Celtics @ Lakers", "_game_date": "2026-01-14T00:00Z", "_game_log": short_log},
        {"Player": "Long Streak", "Team": "Lakers", "Opp": "Celtics",
        "GameLabel": "Celtics @ Lakers", "_game_date": "2026-01-14T00:00Z", "_game_log": long_log},
    ]
    index = NP.build_projection_index(rows, meta=[], sims=8000, seed=5)
    board = NP.default_board_from_index(index)
    short_pts = next(b for b in board if b["Player"] == "Short Streak" and b["Market"] == "Points")
    long_pts = next(b for b in board if b["Player"] == "Long Streak" and b["Market"] == "Points")
    assert short_pts["ModelProb"] != long_pts["ModelProb"]
    assert long_pts["ModelProb"] > short_pts["ModelProb"]
    print("✓ NBA's default board also no longer clusters different streak lengths identically")


def test_build_best_bets_no_longer_clusters_different_streak_lengths_identically():
    short_log = [_log(30, 8, 6, 3) for _ in range(4)]
    long_log = [_log(30, 8, 6, 3) for _ in range(10)]
    rows = [
        {"Player": "Short Streak", "Team": "Lakers", "Opp": "Celtics",
        "GameLabel": "Celtics @ Lakers", "_pid": 1, "_game_log": short_log},
        {"Player": "Long Streak", "Team": "Lakers", "Opp": "Celtics",
        "GameLabel": "Celtics @ Lakers", "_pid": 2, "_game_log": long_log},
    ]
    plays = NP.build_best_bets(rows, sims=8000, seed=5)
    short_pts = next(p for p in plays if p["Player"] == "Short Streak" and p["Market"] == "Points")
    long_pts = next(p for p in plays if p["Player"] == "Long Streak" and p["Market"] == "Points")
    assert short_pts["ModelProb"] != long_pts["ModelProb"]
    assert short_pts["Conviction"] != long_pts["Conviction"]
    print("✓ NBA's build_best_bets Conviction ranking also no longer ties streak lengths together")


# ----------------------------------------------------------------- real price/reference wiring
def test_build_best_bets_matches_original_behavior_with_no_real_data():
    # The critical backward-compatibility guarantee: no real_lines, no offers -- every existing
    # caller must see the exact original always-placeholder, always-theoretical behavior.
    log = [_log(28, 7, 5, 2), _log(24, 8, 6, 3), _log(30, 6, 4, 2)]
    rows = [{"Player": "LeBron James", "Team": "Lakers", "Opp": "Celtics",
            "GameLabel": "Celtics @ Lakers", "_pid": 1, "_game_log": log}]
    plays = NP.build_best_bets(rows, sims=8000, seed=5)
    pts = next(p for p in plays if p["Market"] == "Points")
    assert pts["Line"] == 22.5   # the original _MARKET_SPEC placeholder, unchanged
    assert pts["LineSource"] == "default"
    assert pts["RealPrice"] is None
    assert pts["PriceSource"] == "model_fair"
    assert pts["ConvictionSource"] == "model_typical"
    print("✓ NBA build_best_bets matches the exact original behavior when no real data is supplied")


def test_build_best_bets_real_line_used_when_available():
    log = [_log(28, 7, 5, 2), _log(24, 8, 6, 3), _log(30, 6, 4, 2)]
    rows = [{"Player": "LeBron James", "Team": "Lakers", "Opp": "Celtics",
            "GameLabel": "Celtics @ Lakers", "_pid": 1, "_game_log": log}]
    real_lines = {("lebron james", "player_points"): 25.5}
    plays = NP.build_best_bets(rows, sims=8000, seed=5, real_lines=real_lines)
    pts = next(p for p in plays if p["Market"] == "Points")
    assert pts["Line"] == 25.5
    assert pts["LineSource"] == "book"
    print("✓ NBA build_best_bets now genuinely uses a real line when real_lines supplies one")


def test_build_best_bets_real_price_and_reference_used_when_offers_available():
    log = [_log(28, 7, 5, 2), _log(24, 8, 6, 3), _log(30, 6, 4, 2), _log(26, 7, 5, 3), _log(29, 8, 6, 2)]
    rows = [{"Player": "LeBron James", "Team": "Lakers", "Opp": "Celtics",
            "GameLabel": "Celtics @ Lakers", "_pid": 1, "_game_log": log}]
    real_lines = {("lebron james", "player_points"): 25.5}
    offers = [{"player": "LeBron James", "market": "player_points", "point": 25.5,
              "over": {"draftkings": -115}, "under": {"draftkings": -105}}]
    plays = NP.build_best_bets(rows, sims=8000, seed=5, real_lines=real_lines,
                               offers=offers, preferred_book="draftkings")
    pts = next(p for p in plays if p["Market"] == "Points")
    assert pts["RealPrice"] == -115.0
    assert pts["RealPriceBook"] == "draftkings"
    assert pts["PriceSource"] == "book"
    assert pts["ConvictionSource"] == "book"
    assert pts["Fair"] != pts["RealPrice"]
    print("✓ NBA build_best_bets attaches a real captured price and a real market reference when "
         "offers cover this player, without altering what Fair itself means")


def test_build_best_bets_falls_back_honestly_when_offers_dont_cover_this_player():
    log = [_log(28, 7, 5, 2), _log(24, 8, 6, 3), _log(30, 6, 4, 2)]
    rows = [{"Player": "Some Bench Player", "Team": "Lakers", "Opp": "Celtics",
            "GameLabel": "Celtics @ Lakers", "_pid": 1, "_game_log": log}]
    offers = [{"player": "A Totally Different Player", "market": "player_points", "point": 10.5,
              "over": {"draftkings": -110}, "under": {"draftkings": -110}}]
    plays = NP.build_best_bets(rows, sims=8000, seed=5, offers=offers, preferred_book="draftkings")
    pts = next(p for p in plays if p["Market"] == "Points")
    assert pts["RealPrice"] is None
    assert pts["PriceSource"] == "model_fair"
    assert pts["ConvictionSource"] == "model_typical"
    print("✓ NBA build_best_bets falls back honestly when offers exist but don't cover this specific player")



# ----------------------------------------------------------------- build_minutes_row
def test_build_minutes_row_uses_avg_min_from_row():
    row = {"AvgMin": 28.4}
    result = NP.build_minutes_row(row, h2h_log=[])
    assert result["Market"] == "Minutes"
    assert result["Recent Avg"] == 28.4
    print("✓ build_minutes_row reports Recent Avg straight from row['AvgMin'], no recomputation")


def test_build_minutes_row_computes_season_and_h2h_averages():
    row = {"AvgMin": 30.0}
    season_log = [{"min": m} for m in (26, 28, 30, 32, 34)]   # season avg 30
    h2h = [{"min": 25}, {"min": 35}]
    result = NP.build_minutes_row(row, h2h_log=h2h, season_log=season_log)
    assert result["Season Avg"] == 30.0
    assert result["H2H Avg"] == 30.0
    assert result["H2H Games"] == 2
    print("✓ build_minutes_row computes Season Avg and H2H Avg correctly from real game logs")


def test_build_minutes_row_honest_empty_h2h():
    row = {"AvgMin": 28.0}
    result = NP.build_minutes_row(row, h2h_log=[])
    assert result["H2H Games"] == 0
    assert result["H2H Avg"] is None
    assert result["H2H Spread"] is None
    print("✓ build_minutes_row honestly reports zero H2H games rather than guessing")


def test_build_minutes_row_flags_high_variance():
    row = {"AvgMin": 28.0}
    season_log = [{"min": 28}] * 10   # season avg 28
    # wide swing: 10 and 38 minutes across 2 meetings -- spread of 28, more than 75% of season avg (21)
    h2h = [{"min": 38}, {"min": 10}]
    result = NP.build_minutes_row(row, h2h_log=h2h, season_log=season_log)
    assert result["High Variance"] is True
    assert result["H2H Spread"] == "10\u201338"
    print("✓ build_minutes_row flags a wide H2H minutes swing as high variance, with the real spread shown")


def test_build_minutes_row_has_no_suppressed_or_defense_trend_fields():
    # Real, deliberate design: Minutes has no "how does this opponent defend it" concept, so
    # these must be explicitly absent/None, never silently computed as if they meant something.
    row = {"AvgMin": 28.0}
    result = NP.build_minutes_row(row, h2h_log=[])
    assert result["Suppressed"] is False
    assert result["Opp Recent Allowed"] is None
    assert result["Opp Season Allowed"] is None
    assert result["Defense Trend"] is None
    print("✓ build_minutes_row correctly omits Suppressed/Defense Trend -- no honest signal exists for those")


def test_build_minutes_row_compatible_with_profile_table_columns():
    # Regression guard: the view file appends this row directly onto build_matchup_profile's own
    # output and selects a fixed column set from the combined list -- every one of those columns
    # must exist on this row's dict too, or the real Streamlit page would crash on a KeyError.
    row = {"AvgMin": 28.0}
    result = NP.build_minutes_row(row, h2h_log=[])
    required = ["Market", "Recent Avg", "Season Avg", "H2H Avg", "H2H Games",
               "H2H Spread", "High Variance", "Suppressed"]
    assert all(k in result for k in required)
    print("✓ build_minutes_row's output has every column the recent-form table actually selects")


# ----------------------------------------------------------------- L5 Avg / L10 Avg (added directly on request)
def test_build_matchup_profile_l5_and_l10_are_real_separate_windows():
    # Real, exact, hand-verifiable construction: season_log is "most recent first" -- the first 5
    # entries are a genuine hot stretch (30 pts/g), the next 5 a cooler stretch (10 pts/g), so L5,
    # L10, and Season Avg must all land at DIFFERENT, exactly-computable real numbers if the
    # windowing is correct.
    row = {"PTS": 24.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    hot = [{"pts": 30, "reb": 5, "ast": 3, "fg3m": 2} for _ in range(5)]
    cool = [{"pts": 10, "reb": 5, "ast": 3, "fg3m": 2} for _ in range(5)]
    season_log = hot + cool
    profile = NP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["L5 Avg"] == 30.0
    assert pts["L10 Avg"] == 20.0
    assert pts["Season Avg"] == 20.0
    print("\u2713 L5 Avg and L10 Avg reflect their own real, distinct windows -- exact, hand-verified numbers")


def test_build_matchup_profile_l5_none_with_fewer_than_5_real_games():
    row = {"PTS": 24.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2} for _ in range(3)]
    profile = NP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["L5 Avg"] is None
    assert pts["L10 Avg"] is None
    assert pts["Season Avg"] == 20.0
    print("\u2713 L5 Avg/L10 Avg are honestly None (not a padded/partial average) with fewer than 5/10 real games")


def test_build_matchup_profile_l5_real_but_l10_none_with_seven_real_games():
    row = {"PTS": 24.0, "REB": 5.0, "AST": 3.0, "FG3M": 2.0}
    season_log = [{"pts": 20, "reb": 5, "ast": 3, "fg3m": 2} for _ in range(7)]
    profile = NP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       season_log=season_log)
    pts = next(p for p in profile if p["Market"] == "Points")
    assert pts["L5 Avg"] == 20.0
    assert pts["L10 Avg"] is None
    print("\u2713 L5 Avg computes correctly even when L10 honestly can't yet, with 7 real games")



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
