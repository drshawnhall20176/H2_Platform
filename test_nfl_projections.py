"""
test_nfl_projections.py — offline unit tests for nfl_projections.py.

    python test_nfl_projections.py     # or: pytest test_nfl_projections.py
"""

import numpy as np

import nfl_projections as NP
import basketball_projections as BB_P


# ----------------------------------------------------------------- market spec
def test_market_spec_covers_all_four_position_dependent_markets():
    assert NP.default_line("player_pass_yds") == 224.5
    assert NP.default_line("player_rush_yds") == 44.5
    assert NP.default_line("player_receptions") == 3.5
    assert NP.default_line("player_reception_yds") == 39.5
    print("✓ nfl_projections._MARKET_SPEC covers all four position-dependent markets")


def test_market_list_matches_market_spec():
    lst = NP.market_list()
    assert {mkey for mkey, _col, _disp in lst} == {
        "player_pass_yds", "player_rush_yds", "player_receptions", "player_reception_yds"}


def test_default_line_none_for_unknown_market():
    assert NP.default_line("not_a_real_market") is None


def test_shrink_prob_is_the_shared_one_not_a_duplicate():
    # Confirms nfl_projections deliberately REUSES basketball_projections.shrink_prob (see this
    # module's own docstring for why the cross-domain import is intentional) rather than defining
    # its own copy that could silently drift from the fix.
    assert NP.BB_P.shrink_prob is BB_P.shrink_prob


# ----------------------------------------------------------------- build_projection_index (position gating)
def test_build_projection_index_only_uses_a_rows_own_markets():
    # A QB row should never contribute a receiving-market index entry, even though the row dict
    # technically has a "receiving_yards"-shaped absence — the _markets gate is what matters.
    qb_row = {"Player": "Test QB", "Team": "KC", "GameLabel": "KC @ LAC", "Opp": "LAC",
             "_game_date": "2025-09-05",
             "_recent_games": [{"passing_yards": 250, "attempts": 35}] * 3,
             "_markets": ["player_pass_yds"]}
    index = NP.build_projection_index([qb_row], meta=[], sims=2000, seed=1)
    keys = {mkey for (_nm, mkey) in index.keys()}
    assert keys == {"player_pass_yds"}
    print("✓ build_projection_index only builds index entries for a row's own gated markets")


def test_build_projection_index_skips_rows_with_no_markets():
    row = {"Player": "No Markets", "Team": "KC", "GameLabel": "KC @ LAC", "Opp": "LAC",
          "_game_date": "2025-09-05", "_recent_games": [{"passing_yards": 0}], "_markets": []}
    index = NP.build_projection_index([row], meta=[], sims=1000, seed=1)
    assert index == {}


# ----------------------------------------------------------------- shrinkage (same fix as every other sport)
def _qb_log(pass_yds):
    return {"passing_yards": pass_yds, "attempts": 35}


def test_default_board_no_longer_clusters_different_streak_lengths_identically():
    # Same regression as every other sport's projections module — confirms the shrinkage fix was
    # actually wired into nfl_projections.py too, not just the basketball sports.
    short_log = [_qb_log(260) for _ in range(2)]     # 2/2 games clear any reasonable line
    long_log = [_qb_log(260) for _ in range(5)]      # 5/5 games clear the same line (max NFL window)
    rows = [
        {"Player": "Short Streak", "Team": "KC", "Opp": "LAC", "GameLabel": "KC @ LAC",
        "_game_date": "2025-09-05", "_recent_games": short_log, "_markets": ["player_pass_yds"]},
        {"Player": "Long Streak", "Team": "KC", "Opp": "LAC", "GameLabel": "KC @ LAC",
        "_game_date": "2025-09-05", "_recent_games": long_log, "_markets": ["player_pass_yds"]},
    ]
    index = NP.build_projection_index(rows, meta=[], sims=8000, seed=5)
    board = NP.default_board_from_index(index)
    short_pts = next(b for b in board if b["Player"] == "Short Streak")
    long_pts = next(b for b in board if b["Player"] == "Long Streak")
    assert short_pts["ModelProb"] != long_pts["ModelProb"]
    assert long_pts["ModelProb"] > short_pts["ModelProb"]   # more real games -> less shrinkage
    print("✓ NFL's default board also no longer clusters different streak lengths identically")


def test_build_best_bets_no_longer_clusters_different_streak_lengths_identically():
    short_log = [_qb_log(260) for _ in range(2)]
    long_log = [_qb_log(260) for _ in range(5)]
    rows = [
        {"Player": "Short Streak", "Team": "KC", "Opp": "LAC", "GameLabel": "KC @ LAC",
        "_pid": "p1", "_recent_games": short_log, "_markets": ["player_pass_yds"]},
        {"Player": "Long Streak", "Team": "KC", "Opp": "LAC", "GameLabel": "KC @ LAC",
        "_pid": "p2", "_recent_games": long_log, "_markets": ["player_pass_yds"]},
    ]
    plays = NP.build_best_bets(rows, sims=8000, seed=5)
    short_pts = next(p for p in plays if p["Player"] == "Short Streak")
    long_pts = next(p for p in plays if p["Player"] == "Long Streak")
    assert short_pts["ModelProb"] != long_pts["ModelProb"]
    assert short_pts["Conviction"] != long_pts["Conviction"]
    print("✓ NFL's build_best_bets Conviction ranking also no longer ties streak lengths together")


# ----------------------------------------------------------------- build_best_bets (position gating)
def test_build_best_bets_only_produces_plays_for_a_rows_own_markets():
    rb_row = {"Player": "Ground Only RB", "Team": "KC", "Opp": "LAC", "GameLabel": "KC @ LAC",
             "_pid": "p1", "_markets": ["player_rush_yds"],
             "_recent_games": [{"rushing_yards": 60, "receiving_yards": 0, "receptions": 0}] * 3}
    plays = NP.build_best_bets([rb_row], sims=2000, seed=1)
    assert {p["Market"] for p in plays} == {"Rush Yards"}
    print("✓ build_best_bets only produces plays for a row's own gated markets, no phantom markets")


# ----------------------------------------------------------------- explain_miss
def test_explain_miss_none_row_explains_not_on_slate():
    msg = NP.explain_miss(None, "Pass Yards")
    assert "never saw this player" in msg


def test_explain_miss_catchable_when_trending_up():
    row = {"_recent_games": [{"passing_yards": 320}, {"passing_yards": 310},
                             {"passing_yards": 180}, {"passing_yards": 170}]}
    msg = NP.explain_miss(row, "Pass Yards")
    assert "Catchable" in msg and "trending up" in msg


def test_explain_miss_genuine_outlier_when_no_recent_trend():
    row = {"_recent_games": [{"passing_yards": 200}] * 4}
    msg = NP.explain_miss(row, "Pass Yards")
    assert "Genuine outlier" in msg


def test_explain_miss_no_data_for_unknown_market():
    row = {"_recent_games": [{"passing_yards": 200}]}
    assert NP.explain_miss(row, "Not A Real Market") == "No recent-game data available for this player."


# ----------------------------------------------------------------- Matchup Lab support
def test_build_trend_series_reverses_to_chronological_order():
    log = [{"week": 6, "passing_yards": 250}, {"week": 5, "passing_yards": 300}]
    trend = NP.build_trend_series(log)
    assert [g["week"] for g in trend] == [5, 6]


def test_stat_key_for_is_identity_for_nfl():
    # Deliberate — NFL's _MARKET_SPEC already stores the real nflreadpy column name directly,
    # unlike basketball's separate short-name translation layer.
    assert NP.stat_key_for("passing_yards") == "passing_yards"


def test_build_matchup_profile_only_covers_a_rows_own_markets():
    qb_row = {"Player": "Test QB", "_markets": ["player_pass_yds"],
             "_recent_games": [{"passing_yards": 260}, {"passing_yards": 240}]}
    profile = NP.build_matchup_profile(qb_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    assert len(profile) == 1
    assert profile[0]["Market"] == "Pass Yards"
    assert profile[0]["Recent Avg"] == 250.0
    print("✓ build_matchup_profile only builds rows for a player's own gated markets")


def test_build_matchup_profile_honest_empty_h2h():
    qb_row = {"Player": "Test QB", "_markets": ["player_pass_yds"],
             "_recent_games": [{"passing_yards": 250}]}
    profile = NP.build_matchup_profile(qb_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    assert profile[0]["H2H Games"] == 0
    assert profile[0]["H2H Avg"] is None
    print("✓ build_matchup_profile reports an honest empty H2H rather than a guess")


def test_build_matchup_profile_defense_trend_tags():
    row = {"Player": "Test QB", "_markets": ["player_pass_yds"],
          "_recent_games": [{"passing_yards": 250}]}
    looser = NP.build_matchup_profile(row, [], {"passing_yards": 280.0}, {"passing_yards": 250.0})
    tighter = NP.build_matchup_profile(row, [], {"passing_yards": 220.0}, {"passing_yards": 250.0})
    steady = NP.build_matchup_profile(row, [], {"passing_yards": 255.0}, {"passing_yards": 250.0})
    assert "Looser" in looser[0]["Trend Tag"]
    assert "Tighter" in tighter[0]["Trend Tag"]
    assert "Steady" in steady[0]["Trend Tag"]


# ----------------------------------------------------------------- Anytime TD
def _td_row(position, games):
    return {"Player": f"Test {position}", "_pid": position, "Team": "KC", "Opp": "LAC",
           "GameLabel": "KC @ LAC", "Position": position, "_recent_games": games}


def test_anytime_td_board_only_eligible_positions():
    rows = [
        _td_row("QB", [{"rushing_tds": 1, "receiving_tds": 0}] * 3),
        _td_row("RB", [{"rushing_tds": 1, "receiving_tds": 0}] * 3),
        _td_row("OL", [{"rushing_tds": 0, "receiving_tds": 0}] * 3),   # not eligible at all
    ]
    board = NP.build_anytime_td_board(rows, seed=1)
    positions = {b["Position"] for b in board}
    assert positions == {"QB", "RB"}
    print("✓ build_anytime_td_board only includes TD-eligible positions (QB deliberately included)")


def test_anytime_td_board_ranked_by_raw_probability_not_conviction():
    rows = [
        _td_row("RB", [{"rushing_tds": 1, "receiving_tds": 0}] * 5),    # 5/5 -> high rate
        _td_row("WR", [{"rushing_tds": 0, "receiving_tds": 0}] * 5),    # 0/5 -> low rate
    ]
    board = NP.build_anytime_td_board(rows, seed=1)
    assert board[0]["Position"] == "RB"   # higher scoring rate ranked first
    assert "Conviction" not in board[0]   # deliberately no conviction ratio — see module docstring
    print("✓ build_anytime_td_board ranks by raw probability, no conviction ratio")


def test_anytime_td_board_shrinks_small_samples():
    # A 2/2 "perfect" streak shouldn't show 100% — same shrinkage discipline as everywhere else.
    rows = [_td_row("RB", [{"rushing_tds": 1, "receiving_tds": 0}] * 2)]
    board = NP.build_anytime_td_board(rows, seed=1)
    assert 0.5 < board[0]["ModelProb"] < 1.0
    print("✓ build_anytime_td_board shrinks a small-sample 'perfect' streak below 100%")


def test_anytime_td_board_skips_empty_game_log():
    rows = [_td_row("RB", [])]
    assert NP.build_anytime_td_board(rows) == []


def test_anytime_td_board_counts_either_rushing_or_receiving_td():
    rows = [_td_row("TE", [{"rushing_tds": 0, "receiving_tds": 1}, {"rushing_tds": 1, "receiving_tds": 0},
                           {"rushing_tds": 0, "receiving_tds": 0}])]
    board = NP.build_anytime_td_board(rows, seed=1)
    assert board[0]["TDGames"] == 2   # both a rushing-TD game and a receiving-TD game count


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
