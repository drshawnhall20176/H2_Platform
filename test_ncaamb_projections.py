"""
test_ncaamb_projections.py — offline unit tests for ncaamb_projections.py.

    python test_ncaamb_projections.py     # or: pytest test_ncaamb_projections.py
"""

import numpy as np

import ncaamb_projections as NP
import basketball_projections as BB_P


# ----------------------------------------------------------------- market spec
def test_market_spec_is_wnba_scale_not_nba_scale():
    # NCAAMB's default lines should match WNBA's, not NBA's — both are 40-minute games, unlike
    # NBA's 48-minute ones.
    assert NP.default_line("player_points") == 12.5
    assert NP.default_line("player_rebounds") == 5.5
    assert NP.default_line("player_assists") == 3.5
    assert NP.default_line("player_threes") == 1.5
    print("✓ ncaamb_projections._MARKET_SPEC uses WNBA-scale default lines (40-min games), not NBA's")


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
    log = [{"date": "2027-01-14", "pts": 20}, {"date": "2027-01-10", "pts": 14}]
    trend = NP.build_trend_series(log)
    assert [g["date"] for g in trend] == ["2027-01-10", "2027-01-14"]


# ----------------------------------------------------------------- blowout_risk_tag / threshold
def test_blowout_risk_tag_is_aliased_to_shared_module():
    assert NP.blowout_risk_tag is BB_P.blowout_risk_tag


def test_ncaamb_blowout_threshold_is_higher_than_nba_and_wnba():
    # NCAAMB's own BLOWOUT_THRESHOLD (15.0) should exceed both NBA's (12.0) and WNBA's (10.0)
    # defaults — Division I has bigger talent gaps between top and bottom programs than exist
    # between any two pro teams.
    assert NP.BLOWOUT_THRESHOLD > 12.0
    assert NP.blowout_risk_tag(-13.0, threshold=NP.BLOWOUT_THRESHOLD) == "Competitive"
    assert NP.blowout_risk_tag(-16.0, threshold=NP.BLOWOUT_THRESHOLD) == "⚠️ Blowout risk"
    print("✓ NCAAMB uses its own higher blowout threshold, reflecting Division I's wider talent gaps")


# ----------------------------------------------------------------- build_projection_index / simulate
def test_simulate_player_stat_empty_when_no_values():
    rng = np.random.default_rng(1)
    assert NP.simulate_player_stat([], 100, rng).size == 0


def test_build_projection_index_covers_all_four_markets():
    row = {"Player": "A. Player", "Team": "Duke", "GameLabel": "UConn @ Duke", "Opp": "UConn",
          "_game_date": "2027-01-14T00:00Z",
          "_game_log": [{"pts": 15, "reb": 6, "ast": 4, "fg3m": 2} for _ in range(8)]}
    index = NP.build_projection_index([row], meta=[], sims=2000, seed=1)
    keys = {mkey for (_nm, mkey) in index.keys()}
    assert keys == {"player_points", "player_rebounds", "player_assists", "player_threes"}


# ----------------------------------------------------------------- build_hot_hand_board
def test_build_hot_hand_board_uses_ncaamb_blowout_threshold():
    rows = [{"Player": "Star", "Team": "Duke", "Opp": "UConn",
            "GameLabel": "UConn @ Duke", "PTS": 15.0, "REB": 6.0, "AST": 4.0,
            "FG3M": 2.0, "_opp_id": 41, "_team_id": 150}]
    # A 14-point spread: NBA's/WNBA's thresholds would flag this, but NCAAMB's higher 15.0
    # threshold should NOT — confirms build_hot_hand_board actually uses BLOWOUT_THRESHOLD, not
    # the shared function's own bare default.
    team_spreads = {"Duke": -14.0}
    board = NP.build_hot_hand_board(rows, opp_allowed={}, team_spreads=team_spreads)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Spread"] == -14.0
    assert pts_row["Blowout Risk"] == "Competitive"
    print("✓ build_hot_hand_board uses NCAAMB's own (higher) blowout threshold, not the shared default")


def test_build_hot_hand_board_pace_adjustment_same_as_wnba_nba():
    rows = [{"Player": "Star", "Team": "Duke", "Opp": "Fast Team",
            "GameLabel": "Fast Team @ Duke", "PTS": 15.0, "REB": 6.0, "AST": 4.0,
            "FG3M": 2.0, "_opp_id": 2, "_team_id": 150}]
    opp_allowed = {
        2: {"pts": 78.0, "reb": 34.0, "ast": 16.0, "fg3m": 8.0, "poss": 68.0},
        6: {"pts": 70.0, "reb": 30.0, "ast": 14.0, "fg3m": 6.0, "poss": 64.0},
    }
    board = NP.build_hot_hand_board(rows, opp_allowed)
    pts_row = next(b for b in board if b["Market"] == "Points")
    assert pts_row["Opp Allows /100 Poss"] == round(78.0 / 68.0 * 100, 1)
    print("✓ build_hot_hand_board's pace-adjustment math matches WNBA's/NBA's (copy-adapt, not a new design)")


# ----------------------------------------------------------------- shrinkage (same fix as WNBA/NBA)
def _log(pts, reb, ast, fg3m):
    return {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3m, "min": 28}


def test_default_board_no_longer_clusters_different_streak_lengths_identically():
    # Same regression as WNBA's/NBA's — confirms the shrinkage fix was actually wired into
    # ncaamb_projections.py too, not just the other two, since this is a copy-adapt file.
    short_log = [_log(18, 6, 4, 2) for _ in range(4)]     # 4/4 games clear any reasonable line
    long_log = [_log(18, 6, 4, 2) for _ in range(10)]     # 10/10 games clear the same line
    rows = [
        {"Player": "Short Streak", "Team": "Duke", "Opp": "UConn",
        "GameLabel": "UConn @ Duke", "_game_date": "2027-01-14T00:00Z", "_game_log": short_log},
        {"Player": "Long Streak", "Team": "Duke", "Opp": "UConn",
        "GameLabel": "UConn @ Duke", "_game_date": "2027-01-14T00:00Z", "_game_log": long_log},
    ]
    index = NP.build_projection_index(rows, meta=[], sims=8000, seed=5)
    board = NP.default_board_from_index(index)
    short_pts = next(b for b in board if b["Player"] == "Short Streak" and b["Market"] == "Points")
    long_pts = next(b for b in board if b["Player"] == "Long Streak" and b["Market"] == "Points")
    assert short_pts["ModelProb"] != long_pts["ModelProb"]
    assert long_pts["ModelProb"] > short_pts["ModelProb"]
    print("✓ NCAAMB's default board also no longer clusters different streak lengths identically")


def test_build_best_bets_no_longer_clusters_different_streak_lengths_identically():
    short_log = [_log(18, 6, 4, 2) for _ in range(4)]
    long_log = [_log(18, 6, 4, 2) for _ in range(10)]
    rows = [
        {"Player": "Short Streak", "Team": "Duke", "Opp": "UConn",
        "GameLabel": "UConn @ Duke", "_pid": 1, "_game_log": short_log},
        {"Player": "Long Streak", "Team": "Duke", "Opp": "UConn",
        "GameLabel": "UConn @ Duke", "_pid": 2, "_game_log": long_log},
    ]
    plays = NP.build_best_bets(rows, sims=8000, seed=5)
    short_pts = next(p for p in plays if p["Player"] == "Short Streak" and p["Market"] == "Points")
    long_pts = next(p for p in plays if p["Player"] == "Long Streak" and p["Market"] == "Points")
    assert short_pts["ModelProb"] != long_pts["ModelProb"]
    assert short_pts["Conviction"] != long_pts["Conviction"]
    print("✓ NCAAMB's build_best_bets Conviction ranking also no longer ties streak lengths together")


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
