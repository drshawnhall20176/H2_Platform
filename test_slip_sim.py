"""test_slip_sim.py — the slip pressure-test engine (numpy only, offline)."""

import math

import numpy as np
import pytest

import slip_sim as S


def leg(p, *, game="G1", player=None, side="Over", n_eff=10, **kw):
    return {"p": p, "game": game, "player": player or f"P{id(kw)}{p}{game}", "side": side, "n_eff": n_eff, **kw}


def parlay(*ps, d=None):
    return {"mode": "parlay", "decimal": d if d is not None else 1.0 / math.prod(ps)}


# --------------------------------------------------------------------------- numerics
def test_ndtri_matches_known_quantiles():
    assert S.ndtri(0.5) == pytest.approx(0.0, abs=1e-9)
    assert S.ndtri(0.975) == pytest.approx(1.959963985, abs=1e-6)
    assert S.ndtri(0.8413447461) == pytest.approx(1.0, abs=1e-6)
    assert S.ndtri(0.001) == pytest.approx(-3.090232306, abs=1e-6)     # lower-tail branch
    assert S.ndtri(0.999) == pytest.approx(3.090232306, abs=1e-6)      # upper-tail branch


def test_ndtri_is_monotone_and_symmetric_and_survives_extremes():
    xs = np.linspace(0.001, 0.999, 999)
    z = S.ndtri(xs)
    assert np.all(np.diff(z) > 0)
    assert np.allclose(S.ndtri(1 - xs), -z, atol=1e-8)
    assert np.all(np.isfinite(S.ndtri([0.0, 1.0])))


def test_parlay_decimal_multiplies():
    assert S.parlay_decimal([2.0, 1.5, 1.9091]) == pytest.approx(5.7273, abs=1e-3)
    assert S.parlay_decimal([]) == 1.0


def test_breakeven_leg_prob():
    assert S.breakeven_leg_prob(6.0, 3) == pytest.approx(6 ** (-1 / 3))
    assert S.breakeven_leg_prob(3.0, 2) == pytest.approx(0.5773, abs=1e-3)
    assert S.breakeven_leg_prob(None, 3) is None
    assert S.breakeven_leg_prob(0, 3) is None


# --------------------------------------------------------------------------- payouts
def test_return_multiple_parlay_and_table_and_vectorization():
    hits = np.array([0, 1, 2, 3])
    assert S.return_multiple("parlay", 3, hits, decimal_odds=7.0).tolist() == [0, 0, 0, 7.0]
    assert S.return_multiple("table", 3, hits, table={3: 3.0, 2: 1.0}).tolist() == [0, 0, 1.0, 3.0]
    assert S.return_multiple("table", 3, 2, table={3: 3.0, 2: 1.0}) == 1.0
    with pytest.raises(ValueError):
        S.return_multiple("nope", 3, hits)


def test_builtin_tables_are_internally_sane():
    for mode, tables in S.PAYOUT_TABLES.items():
        for k, tbl in tables.items():
            assert max(tbl) == k                       # the all-hit row exists and is the top tier
            assert all(0 <= h <= k for h in tbl)
            assert tbl[k] == max(tbl.values())         # more hits never pays less
    assert S.POWER_PLAY[3][3] == 6.0 and S.POWER_PLAY[6][6] == 37.5
    assert S.PICK6_BASE[3][3] == 6.0 and S.PICK6_BASE[4][4] == 10.0
    assert S.FLEX_PLAY[3] == {3: 3.0, 2: 1.0}
    hits = sorted(S.FLEX_PLAY[5], reverse=True)
    assert [S.FLEX_PLAY[5][h] for h in hits] == sorted(S.FLEX_PLAY[5].values(), reverse=True)


# --------------------------------------------------------------------------- correlation
def test_correlation_matrix_signs_and_scope():
    a = leg(0.6, game="G1", player="X", side="Over")
    b = leg(0.6, game="G1", player="X", side="Over")
    c = leg(0.6, game="G1", player="Y", side="Over")
    d = leg(0.6, game="G1", player="Z", side="Under")
    e = leg(0.6, game="G2", player="W", side="Over")
    R = S.correlation_matrix([a, b, c, d, e], rho_player=0.30, rho_game=0.08)
    assert R[0, 1] == pytest.approx(0.30)          # same player, same side
    assert R[0, 2] == pytest.approx(0.08)          # same game, different player
    assert R[0, 3] == pytest.approx(-0.08)         # Over vs Under in one game move against each other
    assert R[0, 4] == 0.0                          # different games: independent
    assert np.allclose(R, R.T) and np.allclose(np.diag(R), 1.0)


def test_correlation_matrix_is_always_positive_semidefinite():
    legs = [leg(0.5, game="G", player=f"p{i}", side="Over" if i % 2 else "Under") for i in range(8)]
    R = S.correlation_matrix(legs, rho_player=0.9, rho_game=0.9)
    assert np.linalg.eigvalsh(R).min() > -1e-9
    assert np.allclose(np.diag(R), 1.0)


def test_draw_normals_reproduces_the_correlation():
    R = np.array([[1, 0.5], [0.5, 1]])
    Z = S.draw_normals(R, 200_000, np.random.default_rng(1))
    assert np.corrcoef(Z.T)[0, 1] == pytest.approx(0.5, abs=0.01)


# --------------------------------------------------------------------------- worlds
def test_sample_worlds_center_on_p_and_shrink_with_evidence():
    p = np.array([0.6, 0.4])
    rng = np.random.default_rng(3)
    thin = S.sample_worlds(p, np.array([4, 4]), 20000, rng)
    thick = S.sample_worlds(p, np.array([200, 200]), 20000, rng)
    assert thin.mean(axis=0) == pytest.approx(p, abs=0.01)
    assert thick.std(axis=0).max() < thin.std(axis=0).min()
    flat = S.sample_worlds(p, np.array([4, 4]), 5, rng, uncertainty=False)
    assert np.allclose(flat, p)


# --------------------------------------------------------------------------- evaluate
def test_independent_legs_reproduce_the_analytic_answer():
    legs = [leg(0.6, game="G1", player="A"), leg(0.55, game="G2", player="B"), leg(0.7, game="G3", player="C")]
    pay = parlay(0.6, 0.55, 0.7, d=5.0)
    r = S.evaluate(legs, pay, n_sims=60000, n_worlds=1, seed=5, uncertainty=False)
    p_all = 0.6 * 0.55 * 0.7
    assert r["p_all"] == pytest.approx(p_all, abs=0.006)
    assert r["p_all_independent"] == pytest.approx(p_all)
    assert r["ev"] == pytest.approx(p_all * 5.0 - 1.0, abs=0.04)
    assert sum(r["hit_dist"]) == pytest.approx(1.0)
    assert r["leg_hit_rate"] == pytest.approx([0.6, 0.55, 0.7], abs=0.01)


def test_positive_correlation_lifts_the_joint_hit_rate_and_negative_lowers_it():
    same_over = [leg(0.6, player="A"), leg(0.6, player="B")]
    over_under = [leg(0.6, player="A", side="Over"), leg(0.6, player="B", side="Under")]
    kw = dict(n_sims=80000, n_worlds=1, seed=2, uncertainty=False, rho_game=0.4)
    pay = parlay(0.6, 0.6)
    up = S.evaluate(same_over, pay, **kw)["p_all"]
    down = S.evaluate(over_under, pay, **kw)["p_all"]
    assert up > 0.36 + 0.02
    assert down < 0.36 - 0.02


def test_zero_correlation_setting_matches_independence_even_in_one_game():
    legs = [leg(0.6, player="A"), leg(0.6, player="B")]
    r = S.evaluate(legs, parlay(0.6, 0.6), n_sims=80000, n_worlds=1, seed=4, uncertainty=False,
                   rho_player=0.0, rho_game=0.0)
    assert r["p_all"] == pytest.approx(0.36, abs=0.006)


def test_haircut_lowers_ev_monotonically_and_uses_same_draws():
    legs = [leg(0.62, game=f"G{i}", player=f"P{i}") for i in range(3)]
    pay = parlay(0.55, 0.55, 0.55)
    Z = S.draw_normals(S.correlation_matrix(legs), 20000, np.random.default_rng(9))
    worlds = np.tile([0.62, 0.62, 0.62], (1, 1))
    evs = [S.evaluate(legs, pay, haircut=h, _Z=Z, _worlds=worlds)["ev"] for h in (0.0, 0.03, 0.05, 0.08)]
    assert evs == sorted(evs, reverse=True) and evs[0] > evs[-1]


def test_uncertainty_widens_the_ev_band_and_thin_samples_widen_it_more():
    pay = parlay(0.6, 0.6, 0.6, d=5.5)
    def band(n_eff):
        legs = [leg(0.6, game=f"G{i}", player=f"P{i}", n_eff=n_eff) for i in range(3)]
        r = S.evaluate(legs, pay, n_sims=4000, n_worlds=300, seed=1)
        return r["ev_p95"] - r["ev_p05"]
    assert band(5) > band(50) > 0


def test_p_ev_positive_is_a_probability_and_extremes_behave():
    legs = [leg(0.9, game=f"G{i}", player=f"P{i}", n_eff=200) for i in range(2)]
    good = S.evaluate(legs, {"mode": "parlay", "decimal": 4.0}, n_sims=4000, n_worlds=100, seed=1)
    bad = S.evaluate(legs, {"mode": "parlay", "decimal": 1.05}, n_sims=4000, n_worlds=100, seed=1)
    assert good["p_ev_positive"] == 1.0 and bad["p_ev_positive"] == 0.0


def test_table_payout_flex_ev_matches_hand_calculation():
    legs = [leg(0.6, game=f"G{i}", player=f"P{i}") for i in range(3)]
    pay = {"mode": "table", "table": S.FLEX_PLAY[3]}
    r = S.evaluate(legs, pay, n_sims=100000, n_worlds=1, seed=3, uncertainty=False)
    p = 0.6
    expected = p ** 3 * 3.0 + 3 * p ** 2 * (1 - p) * 1.0 - 1.0
    assert r["ev"] == pytest.approx(expected, abs=0.02)
    assert r["p_total_loss"] == pytest.approx(1 - p ** 3 - 3 * p ** 2 * (1 - p), abs=0.01)


def test_singles_mode_is_stake_weighted_and_pays_each_leg_at_its_own_price():
    legs = [leg(0.6, game="G1", player="A"), leg(0.5, game="G2", player="B")]
    pay = {"mode": "singles", "decimals": [1.9, 2.1], "stakes": [10.0, 30.0]}
    r = S.evaluate(legs, pay, n_sims=100000, n_worlds=1, seed=8, uncertainty=False)
    expected = (10 * 0.6 * 1.9 + 30 * 0.5 * 2.1) / 40 - 1
    assert r["ev"] == pytest.approx(expected, abs=0.02)


def test_singles_with_zero_total_stake_is_a_push_not_a_crash():
    legs = [leg(0.6)]
    r = S.evaluate(legs, {"mode": "singles", "decimals": [1.9], "stakes": [0.0]}, n_sims=500, n_worlds=2, seed=1)
    assert r["ev"] == 0.0


def test_evaluate_is_reproducible_with_a_seed():
    legs = [leg(0.6, game="G", player="A"), leg(0.55, game="G", player="B")]
    a = S.evaluate(legs, parlay(0.6, 0.55), n_sims=2000, n_worlds=20, seed=42)
    b = S.evaluate(legs, parlay(0.6, 0.55), n_sims=2000, n_worlds=20, seed=42)
    assert a["ev"] == b["ev"] and a["hit_dist"] == b["hit_dist"]


# --------------------------------------------------------------------------- scenarios / drops / repeat
def test_stress_scenarios_names_order_and_monotonicity():
    legs = [leg(0.65, game=f"G{i}", player=f"P{i}", p_mkt=0.5) for i in range(3)]
    rows = S.stress_scenarios(legs, parlay(0.5, 0.5, 0.5), n_sims=6000, n_worlds=100, seed=3)
    names = [r["scenario"] for r in rows]
    assert names[0] == "Model as-is"
    assert names[1:4] == ["Model 3 pts too bullish", "Model 5 pts too bullish", "Model 8 pts too bullish"]
    assert names[-1] == "If the book's no-vig price is right"
    evs = [r["ev"] for r in rows[:4]]
    assert evs == sorted(evs, reverse=True)
    assert rows[-1]["ev"] < rows[0]["ev"]           # the market at 50% is worse than the model at 65%


def test_stress_scenarios_omits_book_scenario_without_market_probabilities():
    legs = [leg(0.65, game=f"G{i}", player=f"P{i}") for i in range(2)]
    rows = S.stress_scenarios(legs, parlay(0.5, 0.5), n_sims=2000, n_worlds=20, seed=3)
    assert all("no-vig" not in r["scenario"] for r in rows)


def test_leg_drop_flags_the_dragging_leg():
    legs = [leg(0.75, game="G1", player="A", label="strong1"),
            leg(0.75, game="G2", player="B", label="strong2"),
            leg(0.40, game="G3", player="C", label="weak")]

    def payout_for(sub):
        return {"mode": "parlay", "decimal": math.prod(1 / 0.55 for _ in sub)}

    rows = S.leg_drop_table(legs, payout_for, n_sims=8000, n_worlds=40, seed=6)
    by = {r["leg"]: r for r in rows}
    assert by["weak"]["delta_ev"] < 0                  # slip is better WITHOUT it
    assert by["strong1"]["delta_ev"] > by["weak"]["delta_ev"]
    assert len(rows) == 3


def test_leg_drop_reports_none_when_a_smaller_slip_cannot_be_priced():
    legs = [leg(0.6, game="G1", player="A", label="a"), leg(0.6, game="G2", player="B", label="b")]

    def payout_for(sub):
        if len(sub) < 2:
            raise KeyError(len(sub))            # only the 2-leg slip has a price
        return {"mode": "parlay", "decimal": 3.0}

    rows = S.leg_drop_table(legs, payout_for, n_sims=500, n_worlds=5, seed=1)
    assert all(r["delta_ev"] is None for r in rows)


def test_repeat_play_positive_ev_grows_and_negative_ev_shrinks():
    legs = [leg(0.7, game="G1", player="A", n_eff=400)]
    good = S.evaluate(legs, {"mode": "parlay", "decimal": 1.8}, n_sims=4000, n_worlds=50, seed=1)
    bad = S.evaluate(legs, {"mode": "parlay", "decimal": 1.2}, n_sims=4000, n_worlds=50, seed=1)
    up = S.repeat_play(good["R"], stake_fraction=0.02, n_slips=200, n_paths=1000, seed=1)
    dn = S.repeat_play(bad["R"], stake_fraction=0.02, n_slips=200, n_paths=1000, seed=1)
    assert up["final_p50"] > 1.0 > dn["final_p50"]
    assert up["p_ahead"] > 0.8 > 0.2 > dn["p_ahead"]
    assert 0.0 <= up["p_ruin"] <= 1.0
    assert set(up["fan"]) == {5, 25, 50, 75, 95}
    assert up["final_p05"] <= up["final_p25"] <= up["final_p50"] <= up["final_p75"] <= up["final_p95"]
    dd = up["p_drawdown"]
    assert dd[0.2] >= dd[0.4]                          # deeper drawdowns are rarer


def test_repeat_play_zero_stake_never_moves():
    R = np.array([[0.0, 2.0, 0.0, 2.0]])
    r = S.repeat_play(R, stake_fraction=0.0, n_slips=20, n_paths=50, seed=1)
    assert r["final_p05"] == r["final_p95"] == 1.0 and r["p_ahead"] == 0.0


# --------------------------------------------------------------------------- build 206: team / game legs
def _leg(kind=None, side="Over", team=None, game="A @ B", player="P", **kw):
    d = {"player": player, "game": game, "side": side, "p": 0.5, "n_eff": 30}
    if kind:
        d["kind"] = kind
    if team is not None:
        d["team"] = team
    d.update(kw)
    return d


def _rho(a, b):
    return S.correlation_matrix([a, b])[0, 1]


def test_player_only_slips_are_unchanged_by_the_team_rules():
    """No 'kind' anywhere -> exactly the original same-player / same-game / sign behaviour."""
    a, b, c = _leg(player="X"), _leg(player="X", side="Over"), _leg(player="Y", side="Under")
    R = S.correlation_matrix([a, b, c], rho_player=0.4, rho_game=0.1)
    assert R[0, 1] == pytest.approx(0.4) and R[0, 2] == pytest.approx(-0.1) and R[1, 2] == pytest.approx(-0.1)
    assert S.correlation_matrix([_leg(kind="player"), _leg(player="Q")])[0, 1] == pytest.approx(0.08)


def test_moneyline_and_spread_on_the_same_team_move_together_and_opposite_teams_against():
    ml_a, sp_a, ml_b = (_leg("moneyline", "Win", "AAA", player="AAA"), _leg("spread", "Cover", "AAA", player="AAA"),
                        _leg("moneyline", "Win", "BBB", player="BBB"))
    assert _rho(ml_a, sp_a) == pytest.approx(S.RHO_SAME_MARGIN)
    assert _rho(ml_a, ml_b) == pytest.approx(-S.RHO_SAME_MARGIN)


def test_game_total_over_and_under_oppose_and_two_overs_agree():
    o1, o2, u = _leg("total", "Over", player="G"), _leg("total", "Over", player="G"), _leg("total", "Under", player="G")
    assert _rho(o1, o2) == pytest.approx(S.RHO_TOTAL_TOTAL)
    assert _rho(o1, u) == pytest.approx(-S.RHO_TOTAL_TOTAL)


def test_a_teams_win_barely_says_anything_about_the_game_total():
    assert _rho(_leg("moneyline", "Win", "AAA", player="AAA"), _leg("total", "Over", player="G")) == 0.0


def test_team_total_links():
    tt_a = _leg("team_total", "Over", "AAA", player="AAA")
    tt_b = _leg("team_total", "Over", "BBB", player="BBB")
    tot = _leg("total", "Over", player="G")
    win_a = _leg("moneyline", "Win", "AAA", player="AAA")
    win_b = _leg("moneyline", "Win", "BBB", player="BBB")
    assert _rho(tt_a, tt_b) == pytest.approx(S.RHO_TEAMTOT_OPP)
    assert _rho(tt_a, _leg("team_total", "Over", "AAA", player="AAA")) == pytest.approx(S.RHO_TEAMTOT_SAME)
    assert _rho(tot, tt_a) == pytest.approx(S.RHO_TOTAL_TEAMTOT)
    assert _rho(win_a, tt_a) == pytest.approx(S.RHO_MARGIN_TEAMTOT)
    assert _rho(win_b, tt_a) < 0                       # the OTHER team winning is against my team's total going over
    assert _rho(win_a, _leg("team_total", "Under", "AAA", player="AAA")) == pytest.approx(-S.RHO_MARGIN_TEAMTOT)


def test_a_player_prop_links_to_its_own_teams_result_more_than_the_opponents():
    win_a = _leg("moneyline", "Win", "AAA", player="AAA")
    mine, theirs = _leg(player="Q1", team="AAA"), _leg(player="Q2", team="BBB")
    assert _rho(win_a, mine) == pytest.approx(S.RHO_MARGIN_PLAYER)
    assert _rho(win_a, theirs) == pytest.approx(-S.RHO_MARGIN_PLAYER * 0.7)
    # unknown team on the player -> no rule, never a guess
    assert _rho(win_a, _leg(player="Q3")) == 0.0
    # an Under flips the sign
    assert _rho(win_a, _leg(player="Q1", team="AAA", side="Under")) == pytest.approx(-S.RHO_MARGIN_PLAYER)


def test_total_vs_player_prop_and_different_games_are_independent():
    assert _rho(_leg("total", "Over", player="G"), _leg(player="Q")) == pytest.approx(S.RHO_TOTAL_PLAYER)
    assert _rho(_leg("total", "Over", player="G"), _leg(player="Q", game="C @ D")) == 0.0


def test_mixed_team_and_player_matrix_is_a_valid_correlation_matrix():
    legs = [_leg("moneyline", "Win", "AAA", player="AAA"), _leg("spread", "Cover", "AAA", player="AAA"),
            _leg("total", "Over", player="G"), _leg("total", "Under", player="G"),
            _leg("team_total", "Over", "BBB", player="BBB"), _leg(player="Q1", team="AAA"),
            _leg(player="Q2", team="BBB", side="Under")]
    R = S.correlation_matrix(legs)
    assert np.allclose(R, R.T) and np.allclose(np.diag(R), 1.0)
    assert np.linalg.eigvalsh(R).min() > -1e-8


def test_ml_plus_spread_same_team_hit_together_far_more_often_than_independent():
    ml = dict(_leg("moneyline", "Win", "AAA", player="AAA"), p=0.6)
    sp = dict(_leg("spread", "Cover", "AAA", player="AAA"), p=0.5)
    r = S.evaluate([ml, sp], {"mode": "parlay", "decimal": 4.0}, n_sims=40000, n_worlds=1, seed=3, uncertainty=False)
    assert r["p_all_independent"] == pytest.approx(0.30)
    assert r["p_all"] > 0.42                          # a 0.85-correlated pair is nowhere near independent
