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


def test_is_td_eligible_position():
    assert NP.is_td_eligible_position("RB") is True
    assert NP.is_td_eligible_position("QB") is True
    assert NP.is_td_eligible_position("OL") is False


def test_build_matchup_profile_adds_touchdowns_row_for_eligible_position():
    rb_row = {"Player": "Test RB", "Position": "RB", "_markets": ["player_rush_yds"],
             "_recent_games": [{"rushing_yards": 60, "rushing_tds": 1, "receiving_tds": 0},
                               {"rushing_yards": 40, "rushing_tds": 0, "receiving_tds": 0}]}
    profile = NP.build_matchup_profile(rb_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       opp_recent_tds_allowed=2.5, opp_season_tds_allowed=2.0)
    markets = [p["Market"] for p in profile]
    assert "Touchdowns" in markets
    td_row = next(p for p in profile if p["Market"] == "Touchdowns")
    assert td_row["Recent Avg"] == 0.5   # 1 TD in 2 games
    assert td_row["Opp Recent Allowed"] == 2.5
    assert "Looser" in td_row["Trend Tag"]   # 2.5/2.0 = 1.25 >= 1.08
    print("✓ build_matchup_profile adds a Touchdowns row for a TD-eligible position")


def test_build_matchup_profile_no_touchdowns_row_for_ineligible_position():
    ol_row = {"Player": "Test OL", "Position": "OL", "_markets": [], "_recent_games": []}
    profile = NP.build_matchup_profile(ol_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    assert profile == []
    print("✓ build_matchup_profile adds no Touchdowns row for a non-eligible position")


def test_build_matchup_profile_touchdowns_row_not_suppressed_by_yardage_market_logic():
    # The Touchdowns row is deliberately excluded from the ratio-based Suppressed flagging that
    # compares the yardage markets against each other.
    row = {"Player": "Test RB", "Position": "RB", "_markets": ["player_rush_yds"],
          "_recent_games": [{"rushing_yards": 5, "rushing_tds": 0, "receiving_tds": 0}] * 3}
    profile = NP.build_matchup_profile(row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       opp_recent_tds_allowed=1.0, opp_season_tds_allowed=1.0)
    td_row = next(p for p in profile if p["Market"] == "Touchdowns")
    assert td_row["Suppressed"] is False


# ----------------------------------------------------------------- QB Lab
def _qb_row(name, opp, log):
    return {"Player": name, "Position": "QB", "Team": "KC", "Opp": opp, "GameLabel": f"KC @ {opp}",
           "_pid": name, "_markets": ["player_pass_yds"], "_recent_games": log}


def test_qb_matchup_projections_scales_by_opponent_relative_to_league_average():
    rows = [_qb_row("Test QB", "LAC", [{"passing_yards": 250}, {"passing_yards": 250}])]
    # opponent allows 20% more than league average -> projection should scale up ~20%
    proj = NP.build_qb_matchup_projections(rows, {"LAC": 300.0}, league_avg_pass_yards_allowed=250.0)
    assert proj[0]["Matchup Factor"] == 1.2
    assert proj[0]["Proj Pass Yds"] == 300.0   # 250 * 1.2
    print("✓ build_qb_matchup_projections correctly scales the projection by the matchup factor")


def test_qb_matchup_projections_neutral_when_no_opponent_data():
    rows = [_qb_row("Test QB", "LAC", [{"passing_yards": 250}])]
    proj = NP.build_qb_matchup_projections(rows, {}, league_avg_pass_yards_allowed=250.0)
    assert proj[0]["Matchup Factor"] == 1.0   # no fabricated boost/penalty without real data
    assert proj[0]["Proj Pass Yds"] == 250.0


def test_qb_matchup_projections_only_includes_qbs_with_pass_yards_market():
    rb_row = {"Player": "Test RB", "Position": "RB", "Team": "KC", "Opp": "LAC",
             "GameLabel": "KC @ LAC", "_markets": ["player_rush_yds"],
             "_recent_games": [{"passing_yards": 0}]}
    assert NP.build_qb_matchup_projections([rb_row], {}, 250.0) == []


def test_qb_efficiency_table_flags_trending_above_season_norm():
    log = [{"passing_tds": 3, "passing_interceptions": 0}] * 3   # recent TD-INT diff = 3.0
    season_log = [{"passing_tds": 1, "passing_interceptions": 0.5}] * 10   # season diff = 0.5
    row = _qb_row("Test QB", "LAC", log)
    eff = NP.build_qb_efficiency_table([row], {"Test QB": season_log})
    assert eff[0]["TD-INT Delta (recent vs season)"] == 2.5
    assert "above season norm" in eff[0]["Tag"]
    print("✓ build_qb_efficiency_table correctly flags a QB trending well above their season norm")


def test_qb_efficiency_table_in_line_with_season_norm():
    log = [{"passing_tds": 2, "passing_interceptions": 1}] * 3
    season_log = [{"passing_tds": 2, "passing_interceptions": 1}] * 10
    row = _qb_row("Test QB", "LAC", log)
    eff = NP.build_qb_efficiency_table([row], {"Test QB": season_log})
    assert eff[0]["TD-INT Delta (recent vs season)"] == 0.0
    assert "In line" in eff[0]["Tag"]


def test_qb_efficiency_table_honest_none_without_season_log():
    row = _qb_row("Test QB", "LAC", [{"passing_tds": 2, "passing_interceptions": 0}])
    eff = NP.build_qb_efficiency_table([row], {})   # no season log available for this player
    assert eff[0]["Season Passing TD Rate"] is None
    assert eff[0]["TD-INT Delta (recent vs season)"] is None
    assert eff[0]["Tag"] == "—"
    print("✓ build_qb_efficiency_table honestly reports no delta when no season log is available")


def test_qb_efficiency_table_skips_non_qb_rows():
    rb_row = {"Player": "Test RB", "Position": "RB", "_recent_games": [{"passing_tds": 0}]}
    assert NP.build_qb_efficiency_table([rb_row], {}) == []


def test_build_matchup_profile_qb_gets_split_rows_not_combined_touchdowns():
    qb_row = {"Player": "Test QB", "Position": "QB", "_markets": ["player_pass_yds"],
             "_recent_games": [
                 {"passing_yards": 250, "rushing_yards": 20, "passing_tds": 2, "rushing_tds": 0},
                 {"passing_yards": 230, "rushing_yards": 40, "passing_tds": 1, "rushing_tds": 1},
             ]}
    profile = NP.build_matchup_profile(qb_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    markets = [p["Market"] for p in profile]
    assert "Touchdowns" not in markets   # QB gets split rows, never the combined one
    assert "Rush Yards" in markets
    assert "Passing TDs" in markets
    assert "Rushing TDs" in markets
    print("✓ build_matchup_profile gives a QB split Rush Yards/Passing TDs/Rushing TDs rows, never a combined Touchdowns row")


def test_build_matchup_profile_qb_rush_yards_uses_opp_recent_allowed_dict():
    # QB Rush Yards reuses the SAME opp_recent_allowed/opp_season_allowed dicts already fetched
    # for the yardage markets — no separate opponent-rushing-yards-allowed call needed.
    qb_row = {"Player": "Test QB", "Position": "QB", "_markets": ["player_pass_yds"],
             "_recent_games": [{"passing_yards": 250, "rushing_yards": 30}]}
    profile = NP.build_matchup_profile(qb_row, h2h_log=[],
                                       opp_recent_allowed={"rushing_yards": 140.0},
                                       opp_season_allowed={"rushing_yards": 100.0})
    rush_row = next(p for p in profile if p["Market"] == "Rush Yards")
    assert rush_row["Recent Avg"] == 30.0
    assert rush_row["Opp Recent Allowed"] == 140.0
    assert "Looser" in rush_row["Trend Tag"]   # 140/100 = 1.4 >= 1.08
    print("✓ build_matchup_profile's QB Rush Yards row correctly reuses the existing opponent-allowed dicts")


def test_build_matchup_profile_qb_passing_tds_vs_rushing_tds_correctly_split():
    qb_row = {"Player": "Test QB", "Position": "QB", "_markets": ["player_pass_yds"],
             "_recent_games": [{"passing_tds": 3, "rushing_tds": 0}, {"passing_tds": 1, "rushing_tds": 1}]}
    profile = NP.build_matchup_profile(qb_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={},
                                       opp_recent_passing_tds_allowed=2.0, opp_season_passing_tds_allowed=1.5,
                                       opp_recent_rushing_tds_allowed=0.5, opp_season_rushing_tds_allowed=0.8)
    passing_row = next(p for p in profile if p["Market"] == "Passing TDs")
    rushing_row = next(p for p in profile if p["Market"] == "Rushing TDs")
    assert passing_row["Recent Avg"] == 2.0   # (3+1)/2
    assert rushing_row["Recent Avg"] == 0.5   # (0+1)/2
    assert passing_row["Opp Recent Allowed"] == 2.0
    assert rushing_row["Opp Recent Allowed"] == 0.5
    print("✓ build_matchup_profile correctly splits Passing TDs and Rushing TDs into independent rows")


def test_build_matchup_profile_non_qb_still_gets_combined_touchdowns_row():
    # Regression guard: the refactor to add QB's split rows must not change RB/WR/TE/FB's
    # existing combined Touchdowns row behavior.
    rb_row = {"Player": "Test RB", "Position": "RB", "_markets": ["player_rush_yds"],
             "_recent_games": [{"rushing_yards": 60, "rushing_tds": 1, "receiving_tds": 0}]}
    profile = NP.build_matchup_profile(rb_row, h2h_log=[], opp_recent_allowed={}, opp_season_allowed={})
    markets = [p["Market"] for p in profile]
    assert "Touchdowns" in markets
    assert "Passing TDs" not in markets and "Rushing TDs" not in markets
    print("✓ RB/WR/TE/FB still get the combined Touchdowns row, unaffected by the QB-specific split")


# ----------------------------------------------------------------- QB Lab: rushing extensions
def test_qb_matchup_projections_includes_rush_yards_projection():
    rows = [_qb_row("Test QB", "LAC", [{"passing_yards": 250, "rushing_yards": 25}] * 2)]
    proj = NP.build_qb_matchup_projections(rows, {"LAC": 250.0}, 250.0, {"LAC": 150.0}, 100.0)
    assert proj[0]["Recent Rush Yds"] == 25.0
    assert proj[0]["Rush Matchup Factor"] == 1.5   # 150/100
    assert proj[0]["Proj Rush Yds"] == 37.5         # 25 * 1.5
    print("✓ build_qb_matchup_projections correctly adds a matchup-adjusted rushing projection")


def test_qb_matchup_projections_rush_neutral_without_rush_data():
    rows = [_qb_row("Test QB", "LAC", [{"passing_yards": 250, "rushing_yards": 25}])]
    proj = NP.build_qb_matchup_projections(rows, {"LAC": 250.0}, 250.0)   # no rush args at all
    assert proj[0]["Rush Matchup Factor"] == 1.0
    assert proj[0]["Proj Rush Yds"] == 25.0


def test_qb_efficiency_table_includes_rushing_td_rate_alongside_passing():
    log = [{"passing_tds": 2, "passing_interceptions": 0, "rushing_tds": 1},
          {"passing_tds": 2, "passing_interceptions": 0, "rushing_tds": 0}]
    row = _qb_row("Test QB", "LAC", log)
    eff = NP.build_qb_efficiency_table([row], {})
    assert eff[0]["Recent Rushing TD Rate"] == 0.5
    # renamed keys, not the old ambiguous "Recent TD Rate"/"Season TD Rate"
    assert "Recent Passing TD Rate" in eff[0] and "Recent TD Rate" not in eff[0]
    print("✓ build_qb_efficiency_table includes Rushing TD Rate alongside the renamed Passing TD Rate")


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
