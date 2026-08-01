"""
test_ncaaf_projections.py — offline tests for ncaaf_projections.py (no network).
"""

import numpy as np

import ncaaf_projections as P


def test_simulate_player_stat_parametric_centers_on_the_given_rate():
    rng = np.random.default_rng(7)
    sim = P.simulate_player_stat_parametric(rate=300.0, sims=50000, rng=rng)
    assert sim.size == 50000
    assert abs(sim.mean() - 300.0) < 5.0   # a parametric draw should land close to its own mean
    assert sim.min() >= 0                  # clipped non-negative
    print("✓ simulate_player_stat_parametric's samples center on the given rate and never go negative")


def test_simulate_player_stat_parametric_empty_for_non_positive_rate():
    rng = np.random.default_rng(1)
    assert P.simulate_player_stat_parametric(0, 1000, rng).size == 0
    assert P.simulate_player_stat_parametric(None, 1000, rng).size == 0
    assert P.simulate_player_stat_parametric(-5, 1000, rng).size == 0
    print("✓ simulate_player_stat_parametric returns empty for a non-positive or missing rate, "
         "not a nonsensical distribution around zero")


def test_simulate_player_stat_bootstrap_resamples_real_values():
    rng = np.random.default_rng(11)
    sim = P.simulate_player_stat_bootstrap([200, 250, 300, 280], sims=20000, rng=rng)
    assert sim.size == 20000
    # a bootstrap resample can only ever produce values from the original set (rounded)
    assert set(sim.tolist()) <= {200, 250, 300, 280}
    assert abs(sim.mean() - 257.5) < 10.0   # close to the true mean of [200,250,300,280]
    print("✓ simulate_player_stat_bootstrap resamples only from the real provided values")


def test_simulate_player_stat_bootstrap_empty_for_no_values():
    rng = np.random.default_rng(2)
    assert P.simulate_player_stat_bootstrap([], 1000, rng).size == 0
    print("✓ simulate_player_stat_bootstrap returns empty with no recent values to sample from")


def test_simulate_for_row_prefers_bootstrap_when_recent_games_exist():
    rng = np.random.default_rng(4)
    row_with_recent = {"PassYds": 300.0, "_recent_games": [
        {"passing_YDS": 250}, {"passing_YDS": 275}, {"passing_YDS": 260}]}
    sim = P._simulate_for_row(row_with_recent, "PassYds", 20000, rng)
    # bootstrap only ever produces the real observed values, never something wildly outside them
    assert set(sim.tolist()) <= {250, 275, 260}

    row_without_recent = {"PassYds": 300.0, "_recent_games": []}
    rng2 = np.random.default_rng(4)
    sim2 = P._simulate_for_row(row_without_recent, "PassYds", 20000, rng2)
    # parametric draws spread well beyond the tight bootstrap set above
    assert sim2.max() > 275 or sim2.min() < 250
    print("✓ _simulate_for_row uses the real bootstrap when recent games exist, and only falls "
         "back to the parametric model when they don't")


def test_build_best_bets_uses_bootstrap_with_correct_column_names_end_to_end():
    # Regression guard for the real bug caught while building this: _simulate_for_row and the
    # Why-text builder were both reading _recent_games entries using the ROW-level field name
    # ("PassYds") instead of the raw CFBD per-game column name ("passing_YDS") those entries
    # actually use -- every real game would silently read as 0, bootstrapping from a set of
    # zeros instead of the player's actual real values. This exercises the full production path
    # (build_best_bets itself, not just the isolated helper) with realistic per-game rows.
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "GameLabel": "Texas @ Ohio State",
        "Opp": "Texas", "Position": "QB", "PassYds": 300.0, "RushYds": 0.0,
        "Receptions": 0.0, "RecYds": 0.0, "_pid": "p1", "_game_date": None,
        "_team_games_played": 12, "_markets": ["player_pass_yds"],
        "_recent_games": [
            {"passing_YDS": 320}, {"passing_YDS": 280}, {"passing_YDS": 310}, {"passing_YDS": 290},
        ],
    }]
    plays = P.build_best_bets(rows, sims=20000, seed=13)
    assert len(plays) == 1
    play = plays[0]
    # If the column-name bug were present, ModelProb would reflect bootstrapping from zeros
    # (an extremely low probability of clearing any real line) instead of these real ~300-yard
    # games -- the Why text is the most direct, human-readable proof it used the real values.
    assert "cleared" in play["Why"] and "last 4 games" in play["Why"]
    assert "avg 300" in play["Why"] or "avg 30" in play["Why"]   # ~(320+280+310+290)/4 = 300.0
    print("✓ build_best_bets' full production path correctly bootstraps from real per-game "
         "values using the right column names, not a silent zero-filled fallback")


def test_build_projection_index_uses_team_games_played_as_sample_size():
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "GameLabel": "Texas @ Ohio State",
        "Opp": "Texas", "Position": "QB", "PassYds": 300.0, "RushYds": 20.0,
        "Receptions": 0.0, "RecYds": 0.0, "_pid": "p1", "_game_date": "2026-08-29T19:30:00Z",
        "_team_games_played": 12, "_markets": ["player_pass_yds", "player_rush_yds"],
    }]
    index = P.build_projection_index(rows, meta=[], sims=5000, seed=3)
    key = ("star qb", "player_pass_yds")
    assert key in index
    assert index[key]["n_games"] == 12
    assert abs(index[key]["mean"] - 300.0) < 15.0
    assert index[key]["ctx"]["team"] == "Ohio State"
    print("✓ build_projection_index carries the team's games-played count as n_games (the "
         "shrink_prob sample-size input) and centers the distribution on the row's own rate")


def test_build_projection_index_skips_rows_with_zero_games_played():
    rows = [{
        "Player": "X", "Team": "T", "GameLabel": "G", "Opp": "O", "Position": "QB",
        "PassYds": 300.0, "RushYds": 0.0, "Receptions": 0.0, "RecYds": 0.0, "_pid": "p1",
        "_game_date": None, "_team_games_played": 0, "_markets": ["player_pass_yds"],
    }]
    index = P.build_projection_index(rows, meta=[], sims=1000, seed=1)
    assert index == {}
    print("✓ build_projection_index skips a row with zero team games played (no meaningful "
         "rate to project from)")


def test_default_board_from_index_uses_default_line_without_real_lines():
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "GameLabel": "Texas @ Ohio State",
        "Opp": "Texas", "Position": "QB", "PassYds": 300.0, "RushYds": 0.0,
        "Receptions": 0.0, "RecYds": 0.0, "_pid": "p1", "_game_date": None,
        "_team_games_played": 12, "_markets": ["player_pass_yds"],
    }]
    index = P.build_projection_index(rows, meta=[], sims=20000, seed=5)
    board = P.default_board_from_index(index)
    assert len(board) == 1
    assert board[0]["Market"] == "Pass Yards"
    assert board[0]["Line"] == P.default_line("player_pass_yds")
    assert board[0]["LineSource"] == "default"
    # 300/game average vs a 219.5 default line should clearly favor the Over
    assert board[0]["Side"] == "Over"
    print("✓ default_board_from_index uses the placeholder default line when no real lines are "
         "supplied, and correctly favors the Over for a rate well above that line")


def test_default_board_from_index_prefers_real_line_when_available():
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "GameLabel": "Texas @ Ohio State",
        "Opp": "Texas", "Position": "QB", "PassYds": 300.0, "RushYds": 0.0,
        "Receptions": 0.0, "RecYds": 0.0, "_pid": "p1", "_game_date": None,
        "_team_games_played": 12, "_markets": ["player_pass_yds"],
    }]
    index = P.build_projection_index(rows, meta=[], sims=5000, seed=5)
    real_lines = {(P.normalize_name("Star QB"), "player_pass_yds"): 275.5}
    board = P.default_board_from_index(index, real_lines=real_lines)
    assert board[0]["Line"] == 275.5
    assert board[0]["LineSource"] == "book"
    print("✓ default_board_from_index uses the real book line when supplied, not the default")


def test_build_best_bets_ranks_by_conviction_and_includes_why_text():
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "GameLabel": "Texas @ Ohio State",
        "Opp": "Texas", "Position": "QB", "PassYds": 400.0, "RushYds": 10.0,
        "Receptions": 0.0, "RecYds": 0.0, "_pid": "p1", "_game_date": None,
        "_team_games_played": 12, "_markets": ["player_pass_yds", "player_rush_yds"],
    }]
    plays = P.build_best_bets(rows, sims=20000, seed=9)
    assert len(plays) == 2
    convictions = [p["Conviction"] for p in plays]
    assert convictions == sorted(convictions, reverse=True)
    assert all("parametric model" in p["Why"] for p in plays)
    assert all(p["_team_games_played"] == 12 for p in plays)
    print("✓ build_best_bets ranks plays by conviction descending and every play's Why text "
         "honestly states the parametric (not bootstrap) basis")


def test_explain_miss_handles_missing_row_and_missing_stat():
    assert "never saw this player" in P.explain_miss(None)
    row = {"PassYds": 0.0, "_team_games_played": 12}
    assert "No season stat data" in P.explain_miss(row, market="Pass Yards")
    row2 = {"PassYds": 300.0, "_team_games_played": 12}
    msg = P.explain_miss(row2, market="Pass Yards")
    assert "300.0" in msg and "12" in msg
    print("✓ explain_miss handles a missing slate row and a missing stat honestly, without "
         "fabricating a per-game trend narrative")


def test_build_qb_matchup_projections_scales_by_opponent_relative_to_league_average():
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "Opp": "Michigan",
        "GameLabel": "Michigan @ Ohio State", "Position": "QB", "_pid": "p1",
        "_markets": ["player_pass_yds", "player_rush_yds"],
        "_recent_games": [
            {"passing_YDS": 300, "rushing_YDS": 20}, {"passing_YDS": 280, "rushing_YDS": 15},
        ],
    }]
    out = P.build_qb_matchup_projections(
        rows, opp_pass_yards_allowed={"Michigan": 320.0}, league_avg_pass_yards_allowed=250.0,
        opp_rush_yards_allowed={"Michigan": 90.0}, league_avg_rush_yards_allowed=100.0)
    assert len(out) == 1
    row = out[0]
    assert row["Recent Avg"] == 290.0
    assert row["Matchup Factor"] == 1.28   # 320/250, a softer-than-average pass defense
    assert row["Proj Pass Yds"] == 371.2   # 290 * 1.28
    assert row["Rush Matchup Factor"] == 0.9   # 90/100, a tougher-than-average rush defense
    print("✓ build_qb_matchup_projections scales a QB's real recent average by real "
         "opponent-vs-league-average allowed rates for both pass and rush yards")


def test_build_qb_matchup_projections_neutral_factor_without_opponent_data():
    rows = [{
        "Player": "X", "Team": "T", "Opp": "NoDataTeam", "GameLabel": "G", "Position": "QB",
        "_pid": "p1", "_markets": ["player_pass_yds"],
        "_recent_games": [{"passing_YDS": 250, "rushing_YDS": 10}],
    }]
    out = P.build_qb_matchup_projections(rows, opp_pass_yards_allowed={}, league_avg_pass_yards_allowed=0.0)
    assert out[0]["Matchup Factor"] == 1.0   # no fabricated boost/penalty with no real data
    assert out[0]["Opp Pass Yds Allowed (season)"] is None
    print("✓ build_qb_matchup_projections uses a neutral 1.0x factor, not a fabricated "
         "adjustment, when there's no real opponent/league data yet")


def test_build_qb_matchup_projections_skips_non_qb_and_no_recent_games():
    rb_row = {"Player": "RB", "Position": "RB", "_markets": ["player_rush_yds"], "_recent_games": [{}]}
    qb_no_log = {"Player": "QB2", "Position": "QB", "_markets": ["player_pass_yds"], "_recent_games": []}
    out = P.build_qb_matchup_projections([rb_row, qb_no_log], {}, 0.0)
    assert out == []
    print("✓ build_qb_matchup_projections skips non-QB rows and QBs with no recent-game data")


def test_build_qb_efficiency_table_flags_trending_above_season_norm():
    rows = [{
        "Player": "Star QB", "Team": "Ohio State", "Opp": "Michigan", "Position": "QB", "_pid": "p1",
        "_recent_games": [
            {"passing_TD": 3, "passing_INT": 1, "rushing_TD": 1},
            {"passing_TD": 2, "passing_INT": 0, "rushing_TD": 0},
        ],
    }]
    season_logs = {"p1": [
        {"passing_TD": 2, "passing_INT": 1, "rushing_TD": 0},
        {"passing_TD": 1, "passing_INT": 1, "rushing_TD": 0},
        {"passing_TD": 3, "passing_INT": 0, "rushing_TD": 1},
    ]}
    out = P.build_qb_efficiency_table(rows, season_logs)
    assert len(out) == 1
    row = out[0]
    assert row["Recent Passing TD Rate"] == 2.5 and row["Recent INT Rate"] == 0.5
    assert row["Season Passing TD Rate"] == 2.0
    assert row["TD-INT Delta (recent vs season)"] == 0.67
    assert "Trending above season norm" in row["Tag"]
    print("✓ build_qb_efficiency_table correctly computes recent-vs-season TD:INT rates and "
         "flags a real, meaningful divergence")


def test_build_qb_efficiency_table_no_season_log_yet():
    rows = [{
        "Player": "New QB", "Team": "T", "Opp": "O", "Position": "QB", "_pid": "p2",
        "_recent_games": [{"passing_TD": 1, "passing_INT": 0, "rushing_TD": 0}],
    }]
    out = P.build_qb_efficiency_table(rows, season_logs_by_pid={})
    assert out[0]["Season Passing TD Rate"] is None
    assert out[0]["TD-INT Delta (recent vs season)"] is None
    assert out[0]["Tag"] == "—"
    print("✓ build_qb_efficiency_table handles a QB with no season log yet without crashing, "
         "no fabricated delta or tag")


# ----------------------------------------------------------------- real price/reference wiring
def _ncaaf_row(player="Star QB", pid="p1"):
    return {
        "Player": player, "Team": "Ohio State", "GameLabel": "Texas @ Ohio State",
        "Opp": "Texas", "Position": "QB", "PassYds": 300.0, "RushYds": 0.0,
        "Receptions": 0.0, "RecYds": 0.0, "_pid": pid, "_game_date": None,
        "_team_games_played": 12, "_markets": ["player_pass_yds"],
        "_recent_games": [
            {"passing_YDS": 320}, {"passing_YDS": 280}, {"passing_YDS": 310}, {"passing_YDS": 290},
        ],
    }


def test_build_best_bets_matches_original_behavior_with_no_offers():
    plays = P.build_best_bets([_ncaaf_row()], sims=8000, seed=13)
    assert plays[0]["RealPrice"] is None
    assert plays[0]["PriceSource"] == "model_fair"
    assert plays[0]["ConvictionSource"] == "model_typical"
    print("✓ NCAAF build_best_bets matches the exact original behavior when no offers are supplied")


def test_build_best_bets_real_price_and_reference_used_when_offers_available():
    real_lines = {(P.normalize_name("Star QB"), "player_pass_yds"): 275.5}
    offers = [{"player": "Star QB", "market": "player_pass_yds", "point": 275.5,
              "over": {"draftkings": -115}, "under": {"draftkings": -105}}]
    plays = P.build_best_bets([_ncaaf_row()], sims=8000, seed=13, real_lines=real_lines,
                             offers=offers, preferred_book="draftkings")
    assert plays[0]["RealPrice"] == -115.0
    assert plays[0]["RealPriceBook"] == "draftkings"
    assert plays[0]["PriceSource"] == "book"
    assert plays[0]["ConvictionSource"] == "book"
    assert plays[0]["Fair"] != plays[0]["RealPrice"]
    print("✓ NCAAF build_best_bets attaches a real captured price and a real market reference when "
         "offers cover this player, without altering what Fair itself means")


def test_build_best_bets_falls_back_honestly_when_offers_dont_cover_this_player():
    offers = [{"player": "A Totally Different Player", "market": "player_pass_yds",
              "point": 200.5, "over": {"draftkings": -110}, "under": {"draftkings": -110}}]
    plays = P.build_best_bets([_ncaaf_row(player="Some Bench QB", pid="p2")], sims=8000, seed=13,
                             offers=offers, preferred_book="draftkings")
    assert plays[0]["RealPrice"] is None
    assert plays[0]["PriceSource"] == "model_fair"
    assert plays[0]["ConvictionSource"] == "model_typical"
    print("✓ NCAAF build_best_bets falls back honestly when offers exist but don't cover this specific player")


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
