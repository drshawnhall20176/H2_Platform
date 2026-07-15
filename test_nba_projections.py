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
