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
