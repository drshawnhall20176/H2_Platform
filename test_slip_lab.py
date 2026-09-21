"""test_slip_lab.py — leg pool, slip pricing, headline math, hand-off to the Bet Log (offline)."""

import math

import pytest

import odds_api as O
import projections as P
import quick_log
import slip_lab as SL

MARKET_MAP = {"Points": "player_points", "Batter HR": "batter_home_runs"}
NORM = P.normalize_name


def play(player="A Guy", market="Points", line=20.5, prob=0.60, side="Over", game="AAA @ BBB", **kw):
    d = {"Player": player, "PlayerId": 11, "Team": "AAA", "Game": game, "Opp": "BBB", "Market": market,
         "Side": side, "Line": line, "ModelProb": prob, "Conviction": 1.2, "Why": "because",
         "_game_log": [{"pts": 20}] * 8}
    d.update(kw)
    return d


def offer(player="A Guy", market="player_points", point=20.5, over=None, under=None, pickem=None):
    o = {"market": market, "player": player, "point": point,
         "over": over if over is not None else {"draftkings": -115, "fanduel": -110, "hardrockbet": -120},
         "under": under if under is not None else {"draftkings": -105, "fanduel": -110, "hardrockbet": 100}}
    if pickem:
        o["pickem"] = pickem
    return o


def pool_of(plays, offers, book="draftkings", **kw):
    return SL.build_leg_pool(plays, offers, book, MARKET_MAP, NORM, **kw)


def by_side(pool):
    return {l["side"]: l for l in pool}


# --------------------------------------------------------------------------- pool: sportsbook
def test_pool_has_both_sides_priced_at_the_chosen_book():
    legs = by_side(pool_of([play()], [offer()], "draftkings"))
    assert set(legs) == {"Over", "Under"}
    assert legs["Over"]["p"] == 0.60 and legs["Under"]["p"] == pytest.approx(0.40)
    assert legs["Over"]["price"] == -115 and legs["Under"]["price"] == -105
    assert legs["Over"]["at_book"] and legs["Under"]["at_book"]


def test_switching_book_changes_the_price_not_the_probability():
    hr = by_side(pool_of([play()], [offer()], "hardrockbet"))
    assert hr["Over"]["price"] == -120 and hr["Under"]["price"] == 100
    assert hr["Over"]["p"] == 0.60


def test_ev_is_computed_at_this_books_price():
    over = by_side(pool_of([play()], [offer()], "draftkings"))["Over"]
    assert over["ev_pct"] == pytest.approx((0.60 * O.american_to_decimal(-115) - 1) * 100, abs=0.01)


def test_best_price_and_market_probability_and_edge():
    over = by_side(pool_of([play()], [offer()], "draftkings"))["Over"]
    assert over["best_book"] == "fanduel" or over["best_price"] == -110      # highest payout across books
    assert O.american_to_decimal(over["best_price"]) == max(O.american_to_decimal(x) for x in (-115, -110, -120))
    dk_novig = O.devig_two_way(-115, -105)
    assert over["p_mkt"] == pytest.approx(dk_novig, abs=1e-4)
    assert over["edge"] == pytest.approx(0.60 - dk_novig, abs=1e-4)


def test_market_probability_falls_back_to_the_average_when_the_book_posted_one_side_only():
    off = offer(over={"draftkings": -115, "fanduel": -110}, under={"fanduel": -110})
    over = by_side(pool_of([play()], [off], "draftkings"))["Over"]
    assert over["price"] == -115 and over["p_mkt"] == pytest.approx(0.5)      # fanduel's own no-vig


def test_book_that_did_not_post_the_prop_gives_an_unpriced_leg_that_still_shows_the_market():
    leg = by_side(pool_of([play()], [offer(over={"fanduel": -110}, under={"fanduel": -110})], "draftkings"))["Over"]
    assert leg["price"] is None and leg["at_book"] is False and leg["ev_pct"] is None
    assert leg["best_price"] == -110 and leg["p_mkt"] == pytest.approx(0.5)


def test_no_offers_at_all_still_yields_legs_from_the_model_board():
    pool = pool_of([play()], [], "draftkings")
    assert len(pool) == 2 and all(l["price"] is None and l["p_mkt"] is None for l in pool)


def test_offer_at_a_different_line_is_not_matched():
    leg = by_side(pool_of([play(line=20.5)], [offer(point=21.5)], "draftkings"))["Over"]
    assert leg["price"] is None


def test_under_favorite_play_gets_complementary_probabilities():
    legs = by_side(pool_of([play(side="Under", prob=0.7)], [offer()], "draftkings"))
    assert legs["Under"]["p"] == 0.7 and legs["Over"]["p"] == pytest.approx(0.3)
    assert legs["Under"]["conviction"] == 1.2 and legs["Over"]["conviction"] is None


def test_plays_missing_a_player_line_or_probability_are_skipped():
    plays = [play(player=None), play(line=None), play(prob=None), play()]
    assert len(pool_of(plays, [])) == 2


def test_name_matching_uses_the_sports_normalizer():
    off = offer(player="Álex Guy")
    legs = pool_of([play(player="Alex Guy")], [off], "draftkings")
    assert legs[0]["price"] == -115


def test_leg_ids_are_unique_and_stable():
    pool = pool_of([play(), play(market="Points", line=22.5)], [offer()], "draftkings")
    assert len({l["id"] for l in pool}) == 4
    assert SL.leg_id("A", "Points", "Over", 20.5) == "A|Points|Over|20.5"


def test_game_log_length_becomes_the_evidence_weight():
    assert pool_of([play()], [])[0]["n_eff"] == 8
    assert pool_of([play(_game_log=[])], [])[0]["n_eff"] == 10


# --------------------------------------------------------------------------- pool: pick'em
def test_pickem_book_marks_legs_by_whether_the_app_posts_the_line_and_never_prices_them():
    pk = {"prizepicks": {"over": {"price": None}, "under": {"price": None}}}
    pool = pool_of([play()], [offer(pickem=pk)], "prizepicks")
    assert all(l["at_book"] for l in pool) and all(l["price"] is None for l in pool)
    assert all(l["best_price"] is not None for l in pool)           # sportsbook reference still shown
    assert all(l["p_mkt"] is not None for l in pool)                # market consensus from sportsbooks
    other = pool_of([play()], [offer(pickem={"pick6": {"over": {"price": None}}})], "prizepicks")
    assert not any(l["at_book"] for l in other)


def test_pickem_price_column_never_leaks_a_dfs_payout_as_a_sportsbook_price():
    pk = {"prizepicks": {"over": {"price": 900}, "under": {"price": 900}}}
    assert all(l["price"] is None for l in pool_of([play()], [offer(pickem=pk)], "prizepicks"))
    # defense in depth: even if a DFS entry ever appeared in over/under, a pick'em leg carries no price
    leaky = offer(over={"prizepicks": 900, "draftkings": -110}, under={"prizepicks": 900, "draftkings": -110}, pickem=pk)
    assert all(l["price"] is None for l in pool_of([play()], [leaky], "prizepicks"))


# --------------------------------------------------------------------------- pool: Yes-only (HR / TD)
def test_yes_only_market_gets_a_single_yes_leg_with_no_line():
    hr = play(market="Batter HR", line=None, side="Yes", prob=0.18)
    off = offer(market="batter_home_runs", point=0.5, over={"draftkings": 420, "fanduel": 450}, under={})
    pool = pool_of([hr], [off], "fanduel", single_line_markets={"batter_home_runs"})
    assert len(pool) == 1
    leg = pool[0]
    assert leg["side"] == "Yes" and leg["line"] is None and leg["p"] == 0.18
    assert leg["price"] == 450 and leg["id"].endswith("|Yes|-")
    assert SL.leg_label(leg) == "A Guy · Batter HR Yes"
    assert leg["p_mkt"] is None                          # one-sided market: no no-vig probability


def test_yes_only_market_without_the_single_line_hint_is_skipped_like_any_lineless_play():
    hr = play(market="Batter HR", line=None, side="Yes")
    assert pool_of([hr], []) == []


def test_yes_leg_round_trips_to_a_bet_log_play_keeping_its_side():
    hr = play(market="Batter HR", line=None, side="Yes", prob=0.18)
    off = offer(market="batter_home_runs", point=0.5, over={"draftkings": 420}, under={})
    leg = pool_of([hr], [off], "draftkings", single_line_markets={"batter_home_runs"})[0]
    (pl,) = SL.legs_to_plays([leg])
    assert pl["Side"] == "Yes" and pl["Line"] is None and pl["RealPrice"] == 420


# --------------------------------------------------------------------------- manual legs
def test_manual_leg_shape_and_ev():
    leg = SL.manual_leg(player="B Guy", market="Points", side="over", line=24.5, p=0.58, price=-120,
                        game="X @ Y", book="bet365")
    assert leg["side"] == "Over" and leg["source"] == "manual" and leg["book"] == "bet365"
    assert leg["ev_pct"] == pytest.approx((0.58 * O.american_to_decimal(-120) - 1) * 100, abs=0.01)
    assert leg["at_book"] is True
    no_price = SL.manual_leg(player="B", market="Points", side="Under", line=5.5, p=0.5)
    assert no_price["price"] is None and no_price["ev_pct"] is None and no_price["side"] == "Under"


def test_empirical_over_prob_counts_pushes_half_and_shrinks_small_samples():
    p_small = SL.empirical_over_prob([25, 26, 27, 28], 20.5)          # 4/4 raw
    p_large = SL.empirical_over_prob([25, 26, 27, 28] * 10, 20.5)     # 40/40 raw
    assert 0.5 < p_small < p_large < 1.0
    assert SL.empirical_over_prob([20, 20], 20) == pytest.approx(0.5)
    assert SL.empirical_over_prob([], 20.5) is None
    assert SL.empirical_over_prob([None, 3], 2.5) is not None


def test_poisson_binomial_matches_hand_math():
    d = SL.poisson_binomial([0.5, 0.5])
    assert d == pytest.approx([0.25, 0.5, 0.25])
    assert sum(SL.poisson_binomial([0.6, 0.7, 0.55])) == pytest.approx(1.0)
    assert SL.poisson_binomial([0.6, 0.7])[2] == pytest.approx(0.42)
    assert SL.poisson_binomial([]) == [1.0]


# --------------------------------------------------------------------------- pricing a slip
def L(p, price=-110, **kw):
    return SL.manual_leg(player=kw.pop("player", f"P{p}{price}"), market="Points", side="Over",
                         line=kw.pop("line", 10.5), p=p, price=price, game=kw.pop("game", None), **kw)


def test_parlay_is_the_product_of_leg_prices_or_the_typed_price():
    legs = [L(0.6, -110), L(0.6, +100), L(0.6, -150)]
    pay = SL.slip_payout("parlay", legs)
    assert pay["decimal"] == pytest.approx((1 + 100 / 110) * 2.0 * (1 + 100 / 150))
    typed = SL.slip_payout("parlay", legs, decimal_override=O.american_to_decimal(500))
    assert typed["decimal"] == 6.0


def test_parlay_needs_two_priced_legs():
    assert SL.slip_payout("parlay", [L(0.6)]) is None
    assert SL.slip_payout("parlay", [L(0.6), L(0.6, price=None)]) is None
    assert SL.slip_payout("parlay", [L(0.6), L(0.6, price=None)], decimal_override=3.0)["decimal"] == 3.0
    assert SL.slip_payout("parlay", []) is None


def test_singles_need_every_price_and_carry_stakes():
    legs = [L(0.6, -110), L(0.55, +120)]
    pay = SL.slip_payout("singles", legs, stakes=[10, 20])
    assert pay["mode"] == "singles" and pay["stakes"] == [10, 20]
    assert pay["decimals"] == pytest.approx([1 + 100 / 110, 2.2])
    assert SL.slip_payout("singles", [L(0.6), L(0.6, price=None)]) is None
    assert SL.slip_payout("singles", legs)["stakes"] == [1.0, 1.0]


def test_pickem_tables_default_override_and_missing_size():
    legs3 = [L(0.6) for _ in range(3)]
    assert SL.slip_payout("power", legs3)["table"] == {3: 6.0}
    assert SL.slip_payout("flex", legs3)["table"] == {3: 3.0, 2: 1.0}
    assert SL.slip_payout("flex", legs3, table={3: 2.5, 2: 1.25})["table"] == {3: 2.5, 2: 1.25}
    assert SL.slip_payout("power", [L(0.6)]) is None                       # no 1-pick entry
    assert SL.slip_payout("pick6", [L(0.6) for _ in range(9)]) is None
    assert SL.slip_payout("pick6", [L(0.6) for _ in range(9)], table={9: 100.0})["table"] == {9: 100.0}
    with pytest.raises(ValueError):
        SL.slip_payout("bogus", legs3)


def test_default_table_is_a_copy():
    t = SL.default_table("power", 3)
    t[3] = 99
    assert SL.default_table("power", 3) == {3: 6.0}


# --------------------------------------------------------------------------- headline math
def test_headline_parlay():
    legs = [L(0.6, -110), L(0.6, -110)]
    pay = SL.slip_payout("parlay", legs)
    h = SL.headline(legs, pay)
    assert h["p_all_independent"] == pytest.approx(0.36)
    assert h["fair_decimal"] == pytest.approx(1 / 0.36)
    assert h["ev_per_dollar"] == pytest.approx(0.36 * pay["decimal"] - 1)
    assert h["breakeven_leg_prob"] == pytest.approx(pay["decimal"] ** -0.5)
    assert h["hit_dist"] == pytest.approx([0.16, 0.48, 0.36])


def test_headline_singles_is_stake_weighted():
    legs = [L(0.6, -110), L(0.5, +120)]
    pay = SL.slip_payout("singles", legs, stakes=[10, 30])
    h = SL.headline(legs, pay)
    ev1, ev2 = 0.6 * (1 + 100 / 110) - 1, 0.5 * 2.2 - 1
    assert h["ev_per_dollar"] == pytest.approx((10 * ev1 + 30 * ev2) / 40)
    assert h["leg_ev"] == pytest.approx([ev1, ev2])


def test_headline_flex_sums_over_hit_counts():
    legs = [L(0.6) for _ in range(3)]
    h = SL.headline(legs, SL.slip_payout("flex", legs))
    p = 0.6
    assert h["ev_per_dollar"] == pytest.approx(p ** 3 * 3 + 3 * p * p * (1 - p) * 1 - 1)
    assert h["breakeven_leg_prob"] is None                       # two-tier table: no single break-even
    pw = SL.headline(legs, SL.slip_payout("power", legs))
    assert pw["breakeven_leg_prob"] == pytest.approx(6 ** (-1 / 3))


# --------------------------------------------------------------------------- subset pricing (leg drop)
def test_payout_for_subset_reprices_smaller_slips():
    legs = [L(0.6, -110, player="a"), L(0.6, -110, player="b"), L(0.6, -110, player="c")]
    f = SL.payout_for_subset_factory("parlay", decimal_override=None, tables=None)
    assert f(legs[:2])["decimal"] == pytest.approx((1 + 100 / 110) ** 2)
    with pytest.raises(ValueError):
        f(legs[:1])                                              # a 1-leg "parlay" can't be priced
    g = SL.payout_for_subset_factory("power", decimal_override=None, tables=None)
    assert g(legs[:2])["table"] == {2: 3.0}
    with pytest.raises(KeyError):
        g(legs[:1])


# --------------------------------------------------------------------------- Bet Log hand-off
def test_legs_to_plays_carry_the_tested_price_and_probability_into_the_bet_log():
    leg = pool_of([play()], [offer()], "draftkings")[0]
    leg = dict(leg, p=0.66)                                     # the user edited the probability
    (pl,) = SL.legs_to_plays([leg])
    fields = quick_log.bet_log_fields_from_play(pl, "2026-09-21", "NBA", stake=10.0)
    assert fields["entry_odds"] == -115 and fields["entry_odds_source"] == "book"
    assert fields["model_prob"] == pytest.approx(0.66)
    assert fields["player"] == "A Guy" and fields["market"] == "Points" and fields["side"] == "Over"
    assert fields["line"] == 20.5 and fields["player_id"] == 11


def test_unpriced_leg_logs_at_the_models_fair_price():
    leg = pool_of([play()], [], "draftkings")[0]
    (pl,) = SL.legs_to_plays([leg])
    fields = quick_log.bet_log_fields_from_play(pl, "2026-09-21", "NBA", stake=5.0)
    assert fields["entry_odds_source"] == "model_fair"
    assert fields["entry_odds"] == pytest.approx(-150, abs=1)   # 60% -> -150


def test_manual_leg_with_a_typed_price_logs_that_price_and_no_player_id():
    leg = SL.manual_leg(player="B Guy", market="Points", side="Under", line=5.5, p=0.55, price=+105, book="bet365")
    (pl,) = SL.legs_to_plays([leg])
    fields = quick_log.bet_log_fields_from_play(pl, "2026-09-21", "NBA", stake=5.0)
    assert fields["entry_odds"] == 105 and fields["entry_odds_source"] == "book"
    assert fields["side"] == "Under" and fields["player_id"] is None


def test_legs_to_plays_does_not_mutate_the_board_play():
    leg = pool_of([play()], [offer()], "draftkings")[0]
    before = dict(leg["play"])
    SL.legs_to_plays([leg])
    assert leg["play"] == before


# --------------------------------------------------------------------------- pressure test orchestration
def _test_slip(mode="parlay"):
    legs = [L(0.62, -110, player="a", game="G1", n_eff=20), L(0.60, -110, player="b", game="G1", n_eff=20),
            L(0.65, -120, player="c", game="G2", n_eff=20)]
    for l in legs:
        l["p_mkt"] = 0.52
    return legs


def test_run_pressure_test_parlay_returns_everything_the_page_needs():
    legs = _test_slip()
    pay = SL.slip_payout("parlay", legs)
    r = SL.run_pressure_test(legs, "parlay", pay, stake=10, bankroll=1000, n_sims=6000, n_slips=50)
    assert r["k"] == 3 and r["mode"] == "parlay" and r["stake"] == 10
    assert len(r["hit_dist"]) == 4 and sum(r["hit_dist"]) == pytest.approx(1.0)
    assert len(r["hit_dist_independent"]) == 4
    assert r["scenarios"][0]["scenario"] == "Model as-is" and len(r["scenarios"]) == 5
    assert len(r["leg_drop"]) == 3 and r["repeat"]["n_slips"] == 50
    assert r["breakeven_leg_prob"] == pytest.approx(pay["decimal"] ** (-1 / 3))
    assert r["repeat"]["stake_fraction"] == pytest.approx(0.01)
    assert isinstance(r["verdict"], list) and all(lvl in ("good", "warn", "bad", "info") for lvl, _ in r["verdict"])
    assert 0 <= r["p_ev_positive"] <= 1 and r["avg_n_eff"] == pytest.approx(20)


def test_run_pressure_test_result_is_json_serializable_without_the_big_arrays():
    import json
    legs = _test_slip()
    r = SL.run_pressure_test(legs, "parlay", SL.slip_payout("parlay", legs), stake=10, bankroll=500, n_sims=3000, n_slips=20)
    json.dumps(r)                                              # no numpy arrays leaked into session state
    assert "R" not in r and "Z" not in r


def test_run_pressure_test_flex_and_singles_modes():
    legs = _test_slip()
    flex = SL.run_pressure_test(legs, "flex", SL.slip_payout("flex", legs), stake=10, bankroll=1000, n_sims=4000, n_slips=20)
    assert flex["k"] == 3 and len(flex["leg_drop"]) == 3
    assert {d["leg"] for d in flex["leg_drop"]}                # 2-leg Flex tables exist, so drops are priced
    assert all(d["delta_ev"] is not None for d in flex["leg_drop"])
    stakes = [5, 10, 15]
    singles = SL.run_pressure_test(legs, "singles", SL.slip_payout("singles", legs, stakes=stakes), stake=0,
                                   bankroll=1000, stakes=stakes, n_sims=4000, n_slips=20)
    assert singles["stake"] == 30 and singles["repeat"]["stake_fraction"] == pytest.approx(0.03)
    exp = [l["p"] * O.american_to_decimal(l["price"]) - 1 for l in legs]
    assert [d["delta_ev"] for d in singles["leg_drop"]] == pytest.approx(exp)


def test_correlated_slip_beats_the_independent_estimate_in_the_pressure_test():
    legs = _test_slip()
    pay = SL.slip_payout("parlay", legs)
    r = SL.run_pressure_test(legs, "parlay", pay, stake=10, bankroll=1000, n_sims=40000, n_slips=10,
                             rho_player=0.3, rho_game=0.3)
    ind = SL.headline(legs, pay)["p_all_independent"]
    assert r["p_all"] > ind


def test_evidence_multiplier_widens_the_uncertainty_band():
    legs = _test_slip()
    pay = SL.slip_payout("parlay", legs)
    wide = SL.run_pressure_test(legs, "parlay", pay, stake=10, bankroll=1000, n_sims=4000, n_slips=10, evidence_mult=0.25)
    tight = SL.run_pressure_test(legs, "parlay", pay, stake=10, bankroll=1000, n_sims=4000, n_slips=10, evidence_mult=2.0)
    assert (wide["ev_p95"] - wide["ev_p05"]) > (tight["ev_p95"] - tight["ev_p05"])


def test_kelly_fraction_is_reported_for_single_payout_slips():
    legs = _test_slip()
    r = SL.run_pressure_test(legs, "parlay", SL.slip_payout("parlay", legs), stake=10, bankroll=1000, n_sims=3000, n_slips=10)
    assert "kelly_fraction" in r
    f = SL.run_pressure_test(legs, "flex", SL.slip_payout("flex", legs), stake=10, bankroll=1000, n_sims=3000, n_slips=10)
    assert "kelly_fraction" not in f                          # two-tier table has no single Kelly


def test_decimal_to_american_round_trips():
    for am in (-250, -110, +100, +150, +900):
        assert SL.decimal_to_american(O.american_to_decimal(am)) == pytest.approx(am, abs=1)
    assert SL.decimal_to_american(1.0) is None and SL.decimal_to_american(None) is None


# --------------------------------------------------------------------------- verdict rules
def _res(**over):
    base = {"ev": 0.10, "k": 3, "mode": "parlay", "p_all": 0.2, "p_all_independent": 0.2, "p_ev_positive": 0.8,
            "avg_n_eff": 20, "leg_drop": [], "repeat": {"p_ahead": None, "n_slips": 100},
            "scenarios": [{"scenario": "Model 3 pts too bullish", "ev": 0.05},
                          {"scenario": "Model 5 pts too bullish", "ev": 0.02}]}
    base.update(over)
    return base


def test_verdict_negative_ev_is_bad():
    (lvl, txt), *_ = SL.verdict(_res(ev=-0.05))
    assert lvl == "bad" and "losing money" in txt


def test_verdict_robust_moderate_and_fragile_tiers():
    assert SL.verdict(_res())[0][0] == "good"
    moderate = _res(scenarios=[{"scenario": "Model 3 pts too bullish", "ev": 0.03},
                               {"scenario": "Model 5 pts too bullish", "ev": -0.02}])
    assert SL.verdict(moderate)[0][0] == "warn" and "survives" in SL.verdict(moderate)[0][1]
    fragile = _res(scenarios=[{"scenario": "Model 3 pts too bullish", "ev": -0.01},
                              {"scenario": "Model 5 pts too bullish", "ev": -0.06}])
    assert SL.verdict(fragile)[0][0] == "warn" and "Fragile" in SL.verdict(fragile)[0][1]
    unsure = _res(p_ev_positive=0.4)                             # positive after a 5pt cut but shaky worlds
    assert SL.verdict(unsure)[0][0] == "warn"


def test_verdict_calls_out_correlation_thin_evidence_and_the_weakest_leg():
    r = _res(p_all=0.26, p_all_independent=0.20, avg_n_eff=4,
             leg_drop=[{"leg": "good one", "delta_ev": 0.10}, {"leg": "bad one", "delta_ev": -0.04}])
    text = " | ".join(t for _, t in SL.verdict(r))
    assert "Correlation matters" in text and "Thin evidence" in text and "Weakest leg: bad one" in text


def test_verdict_book_scenario_wording_flips_with_the_sign():
    neg = _res(scenarios=_res()["scenarios"] + [{"scenario": "If the book's no-vig price is right", "ev": -0.03}])
    pos = _res(scenarios=_res()["scenarios"] + [{"scenario": "If the book's no-vig price is right", "ev": 0.02}])
    assert any(l == "info" and "only if the model beats the market" in t for l, t in SL.verdict(neg))
    assert any(l == "good" and "isn't just" in t for l, t in SL.verdict(pos))


def test_verdict_is_quiet_about_correlation_when_it_is_negligible_and_for_singles():
    assert not any("Correlation" in t for _, t in SL.verdict(_res(p_all=0.205)))
    singles = _res(mode="singles", leg_drop=[{"leg": "x", "delta_ev": -0.5}, {"leg": "y", "delta_ev": 0.1}])
    assert not any("Weakest" in t for _, t in SL.verdict(singles))


# --------------------------------------------------------------------------- build 206: menu legs on a slip
def team_leg(team="DAL", kind="moneyline", market="Moneyline", side="Win", line=None, game="NYG @ DAL", mk="h2h", price=-150, p=0.6):
    return {"id": SL.leg_id(team, market, side, line), "player": team, "player_id": None, "team": team, "game": game,
            "opp": None, "market": market, "side": side, "line": line, "p": p, "n_eff": 40.0, "price": price,
            "best_price": price, "best_book": "draftkings", "p_mkt": p, "edge": 0.0, "ev_pct": -3.0, "at_book": True,
            "book": "draftkings", "conviction": None, "why": "menu", "game_date": None, "line_source": "menu",
            "source": "menu", "play": None, "kind": kind, "event_id": "E1", "market_key": mk, "p_source": "market"}


def test_conflicts_blocks_same_leg_other_side_and_opposing_team_results():
    over = SL.manual_leg(player="A Guy", market="Points", side="Over", line=20.5, p=0.6, game="g")
    under = SL.manual_leg(player="A Guy", market="Points", side="Under", line=20.5, p=0.4, game="g")
    other_line = SL.manual_leg(player="A Guy", market="Points", side="Under", line=24.5, p=0.4, game="g")
    assert SL.conflicts([over], over) == "that leg is already on the slip"
    assert "other side" in SL.conflicts([over], under)
    assert SL.conflicts([over], other_line) is None                      # a different line is a different bet
    dal, nyg = team_leg("DAL"), team_leg("NYG")
    assert "opposes" in SL.conflicts([dal], nyg)
    sp_dal = team_leg("DAL", "spread", "Spread", "Cover", -3.5, mk="spreads")
    sp_nyg = team_leg("NYG", "spread", "Spread", "Cover", 3.5, mk="spreads")
    assert "opposes" in SL.conflicts([sp_dal], sp_nyg)
    assert SL.conflicts([dal], sp_dal) is None                           # ML + spread, same team: allowed (correlated, not contradictory)
    assert SL.conflicts([dal], team_leg("NYG", game="A @ B")) is None    # another game entirely
    over_t = team_leg("NYG @ DAL", "total", "Game Total", "Over", 44.5, mk="totals")
    under_t = team_leg("NYG @ DAL", "total", "Game Total", "Under", 47.5, mk="totals")
    assert SL.conflicts([over_t], under_t) is None                       # a middle is a deliberate bet


def test_team_level_legs_are_logged_playerless_like_game_watch_moneylines():
    dal = team_leg("DAL")
    sp = team_leg("DAL", "spread", "Spread", "Cover", -3.5, mk="spreads")
    tt = team_leg("DAL", "team_total", "Team Total", "Over", 24.5, mk="team_totals")
    tot = team_leg("NYG @ DAL", "total", "Game Total", "Under", 44.5, mk="totals")
    ml, spread, team_total, total = SL.legs_to_plays([dal, sp, tt, tot])
    assert ml["Player"] is None and ml["PlayerId"] is None and ml["Side"] == "DAL" and ml["Market"] == "Moneyline"
    assert spread["Player"] is None and spread["Side"] == "DAL" and spread["Line"] == -3.5
    assert team_total["Player"] is None and team_total["Side"] == "DAL Over" and team_total["Line"] == 24.5
    assert total["Player"] is None and total["Side"] == "Under" and total["Line"] == 44.5
    for pl in (ml, spread, team_total, total):
        assert pl["PriceSource"] == "book" and pl["RealPrice"] == -150
    f = quick_log.bet_log_fields_from_play(ml, "2026-09-21", "NFL", stake=5)
    assert f["player"] is None and f["side"] == "DAL" and f["entry_odds"] == -150 and f["entry_odds_source"] == "book"
    assert quick_log.format_play_label(ml).startswith("Moneyline DAL")


def test_player_legs_are_still_logged_with_their_player():
    leg = SL.manual_leg(player="A Guy", market="Points", side="Over", line=20.5, p=0.6, price=-110, game="g")
    (pl,) = SL.legs_to_plays([leg])
    assert pl["Player"] == "A Guy" and pl["Side"] == "Over"


def _vres(**kw):
    base = dict(ev=-0.04, k=2, scenarios=[{"scenario": "Model as-is", "ev": -0.04}], p_ev_positive=0.1, p_all=0.3,
                p_all_independent=0.3, leg_drop=[], mode="parlay", avg_n_eff=40.0,
                repeat={"p_ahead": None, "n_slips": 10})
    base.update(kw)
    return base


def test_verdict_for_an_all_market_slip_does_not_blame_the_model():
    v = SL.verdict(_vres(n_market_prob=2))
    assert v[0][0] == "info" and "book's own probabilities" in v[0][1]
    assert not any("The model itself" in t for _, t in v)


def test_verdict_notes_partial_market_legs_and_stays_silent_without_them():
    v = SL.verdict(_vres(n_market_prob=1))
    assert any("1 of 2 leg use" in t or "1 of 2 legs use" in t for _, t in v)
    assert not any("use the book's own probability" in t for _, t in SL.verdict(_vres()))
    assert any("The model itself" in t for _, t in SL.verdict(_vres(n_market_prob=0)))


def test_pressure_test_counts_market_probability_legs():
    a = team_leg("DAL", p=0.6)
    b = SL.manual_leg(player="A Guy", market="Points", side="Over", line=20.5, p=0.6, price=-110, game="NYG @ DAL", team="DAL")
    b["source"] = "board"
    payout = SL.slip_payout("parlay", [a, b])
    r = SL.run_pressure_test([a, b], "parlay", payout, stake=10, bankroll=1000, n_sims=3000, n_slips=10)
    assert r["n_market_prob"] == 1
    assert any("1 of 2 legs" in t for _, t in r["verdict"])


# --------------------------------------------------------------------------- time slot / game filter
def _dleg(pid, game, game_date):
    return {"id": pid, "player": pid, "game": game, "game_date": game_date}


AFTERNOON = "2026-09-21T18:05:00Z"     # 2:05 PM ET
EVENING = "2026-09-21T22:30:00Z"       # 6:30 PM ET
LATE = "2026-09-22T00:30:00Z"          # 8:30 PM ET
DATED = [_dleg("a", "LAL @ DEN", LATE), _dleg("b", "BOS @ NYK", EVENING), _dleg("c", "BOS @ NYK", EVENING),
         _dleg("d", "MIA @ ATL", AFTERNOON), _dleg("e", "TBD @ TBD2", None)]


def test_slots_present_are_in_clock_order_and_include_unknown_times():
    assert SL.slots_present(DATED) == ["Afternoon", "Evening", "Late", "TBD"]
    assert SL.slots_present([DATED[1]]) == ["Evening"]
    assert SL.slots_present([]) == []


def test_game_choices_are_chronological_with_the_eastern_start_time():
    ch = SL.game_choices(DATED)
    assert [k for k, _ in ch] == ["MIA @ ATL", "BOS @ NYK", "LAL @ DEN", "TBD @ TBD2"]   # unknown time last
    labels = dict(ch)
    assert labels["MIA @ ATL"] == "2:05 PM ET — MIA @ ATL"
    assert labels["BOS @ NYK"] == "6:30 PM ET — BOS @ NYK"
    assert labels["LAL @ DEN"] == "8:30 PM ET — LAL @ DEN"
    assert labels["TBD @ TBD2"] == "TBD @ TBD2"                                        # no time to show


def test_a_slot_narrows_the_game_list_and_the_legs():
    late = SL.filter_slot_game(DATED, "Late")
    assert [l["id"] for l in late] == ["a"]
    assert [k for k, _ in SL.game_choices(late)] == ["LAL @ DEN"]
    assert [l["id"] for l in SL.filter_slot_game(DATED, "Evening", "BOS @ NYK")] == ["b", "c"]
    assert SL.filter_slot_game(DATED, "Evening", "LAL @ DEN") == []                     # game outside the slot


def test_defaults_keep_every_leg_and_legs_without_a_game_label_only_survive_all_games():
    assert SL.filter_slot_game(DATED) == DATED
    legs = DATED + [{"id": "z", "player": "z", "game": "", "game_date": None}]
    assert "z" in [l["id"] for l in SL.filter_slot_game(legs)]
    assert "z" not in [l["id"] for l in SL.filter_slot_game(legs, SL.ALL_SLOTS, "BOS @ NYK")]
    assert SL.game_choices(legs) == SL.game_choices(DATED)                              # unlabelled leg adds no game


def test_a_doubleheader_keeps_its_two_games_separate():
    legs = [_dleg("g1a", "NYY @ BOS", AFTERNOON), _dleg("g1b", "NYY @ BOS", AFTERNOON),
            _dleg("g2a", "NYY @ BOS", LATE), _dleg("o", "SEA @ HOU", EVENING)]
    dh = SL.dh_labels(legs)
    assert dh == {"NYY @ BOS"}
    ch = SL.game_choices(legs, dh)
    assert [label for _, label in ch] == ["2:05 PM ET — NYY @ BOS (Game 1)", "6:30 PM ET — SEA @ HOU",
                                          "8:30 PM ET — NYY @ BOS (Game 2)"]
    assert [l["id"] for l in SL.filter_slot_game(legs, SL.ALL_SLOTS, ch[0][0], dh)] == ["g1a", "g1b"]
    assert [l["id"] for l in SL.filter_slot_game(legs, SL.ALL_SLOTS, ch[2][0], dh)] == ["g2a"]
    assert [l["id"] for l in SL.filter_slot_game(legs, "Late", ch[2][0], dh)] == ["g2a"]


def test_a_game_label_with_one_start_time_is_not_a_doubleheader():
    assert SL.dh_labels(DATED) == frozenset()
    assert SL.game_key(DATED[1]) == "BOS @ NYK" and SL.game_key({"id": "x", "game": ""}) is None


def test_the_same_instant_written_two_ways_is_still_one_game():
    a = _dleg("a", "BOS @ NYK", "2026-09-21T22:30:00Z")
    b = _dleg("b", "BOS @ NYK", "2026-09-21T22:30:00+00:00")
    assert SL.dh_labels([a, b]) == frozenset()


def test_the_board_and_the_menu_are_checked_for_doubleheaders_separately():
    board = [_dleg("a", "BOS @ NYK", "2026-09-21T22:30:00Z")]
    menu = [_dleg("m", "BOS @ NYK", "2026-09-21T22:35:00Z")]      # the odds feed's clock is a few minutes off
    assert SL.dh_labels(board, menu) == frozenset()                # not two games
    assert SL.dh_labels(board + menu) == {"BOS @ NYK"}            # (which is what pooling them would have said)


def test_the_filter_works_on_real_pool_and_menu_legs():
    plays = [play(player="P1", game="AAA @ BBB", GameDate=AFTERNOON), play(player="P2", game="CCC @ DDD", GameDate=LATE)]
    pool = SL.build_leg_pool(plays, [offer(player="P1"), offer(player="P2")], "draftkings", MARKET_MAP, NORM)
    assert SL.slots_present(pool) == ["Afternoon", "Late"]
    assert {l["player"] for l in SL.filter_slot_game(pool, "Late")} == {"P2"}
    assert {l["game"] for l in SL.filter_slot_game(pool, SL.ALL_SLOTS, "AAA @ BBB")} == {"AAA @ BBB"}
