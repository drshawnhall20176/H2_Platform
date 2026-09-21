"""
test_nhl_projections.py — offline tests for nhl_projections (pure logic, no network).

    python test_nhl_projections.py     # or: pytest test_nhl_projections.py
"""

import numpy as np
import pytest

import nhl_projections as NP
import basketball_projections as BB_P


def _g(pts=0.0, ast=0.0, goals=0.0, sog=0.0, blk=0.0, saves=0.0, toi=18.0):
    return {"pts": pts, "ast": ast, "goals": goals, "sog": sog, "blk": blk, "saves": saves,
            "toi": toi, "min": toi, "opp": "Vancouver Canucks", "date": "2026-10-15T00:00Z"}


def _skater_row(name="Nathan MacKinnon", log=None, pid=10):
    log = log if log is not None else [_g(pts=2, ast=1, goals=1, sog=5, blk=0) for _ in range(10)]
    return {"Player": name, "Team": "Colorado Avalanche", "Opp": "Vancouver Canucks",
            "GameLabel": "Vancouver Canucks @ Colorado Avalanche", "_pid": pid, "_role": "skater",
            "Role": "skater", "_game_log": log, "_game_date": "2026-10-21T23:00Z"}


def _goalie_row(name="Colorado Goalie", log=None, pid=95):
    log = log if log is not None else [_g(saves=s, toi=60.0) for s in (30, 28, 32, 26, 29, 31, 27, 33, 28, 30)]
    return {"Player": name, "Team": "Colorado Avalanche", "Opp": "Vancouver Canucks",
            "GameLabel": "Vancouver Canucks @ Colorado Avalanche", "_pid": pid, "_role": "goalie",
            "Role": "goalie", "_game_log": log, "_game_date": "2026-10-21T23:00Z"}


# ------------------------------------------------------------------- market spec
def test_six_markets_with_the_real_odds_api_keys():
    assert {m for m, _c, _d in NP.market_list()} == {
        "player_points", "player_assists", "player_goals", "player_shots_on_goal",
        "player_blocked_shots", "player_total_saves"}
    assert [d for _m, _c, d in NP.market_list()] == ["Points", "Assists", "Goals", "Shots on Goal",
                                                     "Blocked Shots", "Saves"]


def test_registry_market_map_agrees_with_the_projection_module():
    import sports
    nhl = sports.get("NHL")
    assert nhl.market_map == {disp: mkey for mkey, _c, disp in NP.market_list()}
    assert set(nhl.markets) == set(nhl.market_map.values())


def test_markets_are_split_by_role():
    assert NP.markets_for_role("goalie") == ["player_total_saves"]
    skater = NP.markets_for_role("skater")
    assert "player_total_saves" not in skater and len(skater) == 5


def test_stat_key_and_default_line():
    assert NP.stat_key_for("SOG") == "sog" and NP.stat_key_for("G") == "goals" and NP.stat_key_for("SV") == "saves"
    assert NP.default_line("player_goals") == 0.5 and NP.default_line("player_shots_on_goal") == 2.5
    assert NP.default_line("player_total_saves") == 25.5
    assert NP.default_line("nope") is None


def test_build_trend_series_is_chronological():
    log = [{"date": "b", "sog": 3}, {"date": "a", "sog": 1}]
    assert [g["date"] for g in NP.build_trend_series(log)] == ["a", "b"]


# ------------------------------------------------------------------- simulate
def test_simulate_player_stat_empty_and_nonnegative_ints():
    rng = np.random.default_rng(1)
    assert NP.simulate_player_stat([], 100, rng).size == 0
    sim = NP.simulate_player_stat([0.0, 1.0, 2.0, 5.0], 500, rng)
    assert sim.dtype == np.int64 and sim.min() >= 0 and set(np.unique(sim)) <= {0, 1, 2, 5}


def test_simulate_only_produces_values_the_player_actually_had():
    rng = np.random.default_rng(3)
    assert set(np.unique(NP.simulate_player_stat([1.0, 1.0, 1.0], 300, rng))) == {1}


# ------------------------------------------------------------------- projection index
def test_projection_index_prices_each_role_only_for_its_own_markets():
    idx = NP.build_projection_index([_skater_row(), _goalie_row()], [], sims=2000, seed=1)
    skater_keys = {m for (n, m) in idx if n == "nathan mackinnon"}
    goalie_keys = {m for (n, m) in idx if n == "colorado goalie"}
    assert skater_keys == set(NP.markets_for_role("skater"))
    assert goalie_keys == {"player_total_saves"}
    entry = idx[("nathan mackinnon", "player_shots_on_goal")]
    assert entry["mean"] == pytest.approx(5.0) and entry["n_games"] == 10
    assert entry["dist"].sum() == pytest.approx(1.0)
    assert entry["ctx"]["team"] == "Colorado Avalanche"


def test_projection_index_skips_a_player_with_no_log():
    assert NP.build_projection_index([_skater_row(log=[])], [], sims=100, seed=1) == {}


def test_projection_index_is_seed_reproducible():
    rows = [_skater_row(log=[_g(sog=s) for s in (1, 4, 2, 6, 3, 2, 5, 1, 0, 4)])]
    a = NP.build_projection_index(rows, [], sims=500, seed=9)
    b = NP.build_projection_index(rows, [], sims=500, seed=9)
    assert np.allclose(a[("nathan mackinnon", "player_shots_on_goal")]["dist"],
                       b[("nathan mackinnon", "player_shots_on_goal")]["dist"])


def test_default_board_favors_a_side_and_stays_inside_zero_one():
    idx = NP.build_projection_index([_skater_row(), _goalie_row()], [], sims=2000, seed=1)
    board = NP.default_board_from_index(idx)
    assert len(board) == len(idx)
    for p in board:
        assert p["Side"] in ("Over", "Under") and 0.5 <= p["ModelProb"] < 1.0
        assert p["FairAm"] is not None and p["Market"] in {d for _m, _c, d in NP.market_list()}


# ------------------------------------------------------------------- shrinkage toward the market's own rate
def test_goal_props_shrink_toward_the_typical_goal_rate_not_fifty_fifty():
    # A 10-game log with ZERO goals: shrinking toward 50/50 would make Under look enormous;
    # shrinking toward the typical ~20% over rate keeps the Over probability near reality.
    over = NP._shrunk_over(0.0, 10, "Goals")
    assert over == pytest.approx(BB_P.shrink_prob(0.0, 10, reference=0.20))
    assert 0.02 <= over < 0.20
    assert over < BB_P.shrink_prob(0.0, 10, reference=0.5)        # a 50/50 target would be far higher
    # ...and a thin sample is pulled further toward the market rate than a thick one
    thin, thick = NP._shrunk_over(0.9, 3, "Goals"), NP._shrunk_over(0.9, 30, "Goals")
    assert 0.20 < thin < thick < 0.98


def test_clip_prob_keeps_prices_defined():
    assert NP._clip_prob(0.0) == 0.02 and NP._clip_prob(1.0) == 0.98 and NP._clip_prob(0.4) == 0.4


# ------------------------------------------------------------------- build_best_bets
def test_best_bets_schema_matches_the_shared_play_contract():
    plays = NP.build_best_bets([_skater_row(), _goalie_row()], sims=3000, seed=2)
    assert plays
    required = {"Player", "PlayerId", "Team", "Game", "Opp", "Versus", "Market", "Side", "Line",
                "LineSource", "ModelProb", "Fair", "RealPrice", "RealPriceBook", "PriceSource",
                "Conviction", "ConvictionSource", "_ceiling", "Why"}
    for p in plays:
        assert required <= set(p)
        assert p["LineSource"] == "default" and p["PriceSource"] == "model_fair"
        assert p["ConvictionSource"] == "model_typical"
        assert 0.0 < p["ModelProb"] < 1.0 and p["Conviction"] > 0
        assert p["_ceiling"] == pytest.approx(round(1 / (p["ModelProb"] / p["Conviction"]), 2), abs=0.05)
    assert [p["Conviction"] for p in plays] == sorted((p["Conviction"] for p in plays), reverse=True)


def test_best_bets_role_split_and_market_names():
    plays = NP.build_best_bets([_skater_row(), _goalie_row()], sims=2000, seed=2)
    by_player = {}
    for p in plays:
        by_player.setdefault(p["Player"], set()).add(p["Market"])
    assert by_player["Colorado Goalie"] == {"Saves"}
    assert by_player["Nathan MacKinnon"] == {"Points", "Assists", "Goals", "Shots on Goal", "Blocked Shots"}
    assert all(p["PlayerId"] == 95 for p in plays if p["Player"] == "Colorado Goalie")


def test_best_bets_side_follows_the_market_reference():
    # a sniper who scores in 8 of 10 games is an Over on Goals; a player who never scores is an Under
    hot = _skater_row("Hot", [_g(goals=1) for _ in range(8)] + [_g(goals=0)] * 2)
    cold = _skater_row("Cold", [_g(goals=0) for _ in range(10)], pid=11)
    plays = NP.build_best_bets([hot, cold], sims=4000, seed=4)
    goals = {p["Player"]: p for p in plays if p["Market"] == "Goals"}
    assert goals["Hot"]["Side"] == "Over" and goals["Hot"]["Conviction"] > 1.5
    assert goals["Cold"]["Side"] == "Under"


def test_best_bets_uses_a_real_line_when_supplied():
    plays = NP.build_best_bets([_skater_row()], sims=3000, seed=5,
                               real_lines={("nathan mackinnon", "player_shots_on_goal"): 3.5})
    sog = next(p for p in plays if p["Market"] == "Shots on Goal")
    assert sog["Line"] == 3.5 and sog["LineSource"] == "book"
    assert next(p for p in plays if p["Market"] == "Points")["LineSource"] == "default"


def test_best_bets_real_price_and_reference_when_offers_cover_the_player():
    offers = [{"player": "Nathan MacKinnon", "market": "player_shots_on_goal", "point": 3.5,
               "over": {"draftkings": -130}, "under": {"draftkings": 110}}]
    plays = NP.build_best_bets([_skater_row()], sims=4000, seed=5,
                               real_lines={("nathan mackinnon", "player_shots_on_goal"): 3.5},
                               offers=offers, preferred_book="draftkings")
    sog = next(p for p in plays if p["Market"] == "Shots on Goal")
    assert sog["Side"] == "Over" and sog["RealPrice"] == -130.0 and sog["RealPriceBook"] == "draftkings"
    assert sog["PriceSource"] == "book" and sog["ConvictionSource"] == "book"
    assert sog["Fair"] != sog["RealPrice"]                       # Fair keeps meaning the model's own price
    # a market the offers don't cover falls back honestly
    pts = next(p for p in plays if p["Market"] == "Points")
    assert pts["RealPrice"] is None and pts["PriceSource"] == "model_fair"
    assert pts["ConvictionSource"] == "model_typical"


def test_best_bets_skips_players_with_no_log():
    assert NP.build_best_bets([_skater_row(log=[])], sims=100, seed=1) == []


def test_goalie_why_text_says_the_starter_is_unconfirmed():
    plays = NP.build_best_bets([_goalie_row()], sims=2000, seed=1)
    assert "starter unconfirmed until game day" in plays[0]["Why"]
    skater = NP.build_best_bets([_skater_row()], sims=2000, seed=1)
    assert all("unconfirmed" not in p["Why"] for p in skater)


# ------------------------------------------------------------------- reasons / explain_miss
def test_player_reasons_counts_real_games_and_flags_a_trend():
    text = NP._player_reasons([3, 3, 3, 1, 1, 1, 1, 1, 1, 1], 2.5, "Over", "Shots on Goal")
    assert "cleared 2.5 in 3 of last 10 games" in text and "trending up" in text
    under = NP._player_reasons([0, 0, 1], 0.5, "Under", "Goals")
    assert under.startswith("stayed under 0.5 in 2 of last 3 games")
    assert NP._player_reasons([], 0.5, "Over") == "no recent-game data available"


def test_explain_miss_variants():
    assert "Not on the projected slate" in NP.explain_miss(None)
    assert "No recent-game data" in NP.explain_miss(_skater_row(log=[]), "Goals")
    assert "No recent-game data" in NP.explain_miss(_skater_row(), "Not A Market")
    rising = _skater_row(log=[_g(goals=2), _g(goals=2), _g(goals=2)] + [_g(goals=0)] * 7)
    assert "Catchable" in NP.explain_miss(rising, "Goals")
    flat = _skater_row(log=[_g(goals=0)] * 10)
    assert "Genuine outlier" in NP.explain_miss(flat, "Goals")


# ------------------------------------------------------------------- the shared contract
def test_sport_agnostic_helpers_are_the_shared_ones():
    import projections
    for name in ("prob_over", "prob_for_side", "normalize_name", "format_et",
                 "prob_to_decimal", "prob_to_american", "curate_selections"):
        assert getattr(NP, name) is getattr(projections, name)


def test_nhl_best_bets_flow_through_shared_curation():
    plays = NP.build_best_bets([_skater_row(), _goalie_row()], sims=2000, seed=2)
    picks = NP.curate_selections(plays, n=4, per_market_cap=1)
    assert len(picks) == 4 and len({p["Market"] for p in picks}) == 4     # varied, one per market


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
