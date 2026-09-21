"""test_slip_suggest.py — leg scorecard and suggested tickets (offline, deterministic)."""

import itertools
import math

import pytest

import odds_api as O
import slip_lab as SL
import slip_suggest as SS


def leg(i, p=0.60, price=-110, game=None, n_eff=20, side="Over", player=None, source="board", **kw):
    l = SL.manual_leg(player=player or f"Player {i}", market="Points", side=side, line=20.5 + i, p=p,
                      price=price, game=game if game is not None else f"G{i}", n_eff=n_eff, book="draftkings")
    l["source"] = source
    l["at_book"] = True
    l.update(kw)
    return l


def pool_mixed(n=14):
    """Deterministic pool with a spread of probabilities, prices and evidence."""
    out = []
    for i in range(n):
        out.append(leg(i, p=0.45 + 0.02 * i, price=[-130, -115, -105, 100, 120][i % 5],
                       n_eff=[6, 12, 25, 40][i % 4], game=f"G{i % 5}"))
    return out


# --------------------------------------------------------------------------- is_model_priced
def test_model_priced_rules():
    assert SS.is_model_priced(leg(1))                                           # board / hand-typed
    assert not SS.is_model_priced(leg(1, source="menu", p_source="market"))
    assert not SS.is_model_priced(leg(1, source="menu", p_source="implied"))
    assert SS.is_model_priced(leg(1, source="menu", p_source="model"))
    assert SS.is_model_priced(leg(1, source="menu", p_source="yours"))


# --------------------------------------------------------------------------- scorecard
def test_scorecard_band_brackets_the_hit_chance_and_ranks_by_floor():
    rows = SS.leg_scorecard(pool_mixed())
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    for r in rows:
        assert r["floor"] < r["p"] < r["ceiling"]
    floors = [r["floor"] for r in rows]
    assert floors == sorted(floors, reverse=True)


def test_more_evidence_raises_the_floor_at_the_same_probability():
    thin, solid = leg(1, p=0.62, n_eff=5), leg(2, p=0.62, n_eff=60)
    rows = {r["id"]: r for r in SS.leg_scorecard([thin, solid])}
    assert rows[solid["id"]]["floor"] > rows[thin["id"]]["floor"]
    assert rows[thin["id"]]["evidence"] == "thin" and rows[solid["id"]]["evidence"] == "solid"
    # ...and it can outrank a leg the model likes slightly MORE
    hot_thin = leg(3, p=0.66, n_eff=5)
    order = [r["id"] for r in SS.leg_scorecard([hot_thin, solid])]
    assert order[0] == solid["id"]


def test_evidence_multiplier_widens_the_band():
    l = leg(1, p=0.6, n_eff=20)
    a = SS.leg_scorecard([l], evidence_mult=1.0)[0]
    b = SS.leg_scorecard([l], evidence_mult=0.5)[0]
    assert b["floor"] < a["floor"] and b["ceiling"] > a["ceiling"]


def test_scorecard_ev_fields_match_hand_calculation_and_none_without_a_price():
    l = leg(1, p=0.60, price=100, n_eff=30)
    r = SS.leg_scorecard([l])[0]
    assert r["ev_pct"] == pytest.approx((0.60 * 2.0 - 1) * 100)
    assert r["ev_floor_pct"] == pytest.approx((r["floor"] * 2.0 - 1) * 100)
    assert 0.0 <= r["p_ev_pos"] <= 1.0
    r2 = SS.leg_scorecard([leg(2, price=None)])[0]
    assert r2["ev_pct"] is None and r2["ev_floor_pct"] is None and r2["p_ev_pos"] is None


def test_p_ev_positive_rises_with_the_probability():
    lo = SS.leg_scorecard([leg(1, p=0.48, price=100, n_eff=30)])[0]["p_ev_pos"]
    hi = SS.leg_scorecard([leg(2, p=0.62, price=100, n_eff=30)])[0]["p_ev_pos"]
    assert hi > lo and hi > 0.9 and lo < 0.5      # 0.48 vs a 0.50 break-even: under half the worlds


def test_scorecard_is_deterministic_and_handles_empty():
    assert SS.leg_scorecard([]) == []
    a, b = SS.leg_scorecard(pool_mixed()), SS.leg_scorecard(pool_mixed())
    assert [(r["id"], r["floor"]) for r in a] == [(r["id"], r["floor"]) for r in b]


def test_grade_words():
    assert SS.grade({"ev_pct": 8.0, "ev_floor_pct": 1.0, "p": 0.6}) == "Value"
    assert SS.grade({"ev_pct": 8.0, "ev_floor_pct": -4.0, "p": 0.6}) == "Lean"
    assert SS.grade({"ev_pct": -3.0, "ev_floor_pct": -9.0, "p": 0.6}) == "Priced in"
    assert SS.grade({"ev_pct": None, "p": 0.70}) == "Strong"
    assert SS.grade({"ev_pct": None, "p": 0.58}) == "Lean"
    assert SS.grade({"ev_pct": None, "p": 0.50}) == "Coin flip"


# --------------------------------------------------------------------------- fast maths
def test_dist_matches_brute_force_enumeration():
    ps = [0.6, 0.55, 0.7, 0.4]
    dist = SS._dist(ps)
    brute = [0.0] * 5
    for combo in itertools.product([0, 1], repeat=4):
        pr = math.prod(p if c else 1 - p for p, c in zip(ps, combo))
        brute[sum(combo)] += pr
    assert dist == pytest.approx(brute) and sum(dist) == pytest.approx(1.0)


def test_stats_for_a_parlay_and_a_flex_table():
    mean, sd, p_pay = SS._stats([0.6, 0.6], [0, 0, 4.0])
    assert mean == pytest.approx(0.36 * 4.0) and p_pay == pytest.approx(0.36)
    assert sd == pytest.approx(math.sqrt(0.36 * 16 - (1.44) ** 2))
    mean, _, p_pay = SS._stats([0.6, 0.6], [0, 0.5, 2.0])          # 2-pick Flex
    assert mean == pytest.approx(0.48 * 0.5 + 0.36 * 2.0) and p_pay == pytest.approx(0.36)


def test_combo_constraints():
    a, b = leg(1, game="X"), leg(2, game="X")
    c = leg(3, game="X")
    assert SS._combo_ok([a, b], 2) and not SS._combo_ok([a, b, c], 2) and SS._combo_ok([a, b, c], 3)
    assert not SS._combo_ok([a, leg(9, player=a["player"], game="Y")], 2)      # one leg per player
    assert not SS._combo_ok([a, b], 1) and SS._combo_ok([a, leg(4, game="Y")], 1)


# --------------------------------------------------------------------------- suggestions
def test_market_only_legs_are_never_suggested_and_the_user_is_told():
    good = [leg(i, p=0.62, price=110) for i in range(6)]
    junk = [leg(20 + i, p=0.7, price=-110, source="menu", p_source="market") for i in range(5)]
    r = SS.suggest_tickets(good + junk, "draftkings", simulate=False)
    used = {l["id"] for t in r["tickets"] for l in t["legs"]}
    assert used and not used & {j["id"] for j in junk}
    assert not {s["leg"]["id"] for grp in r["singles"].values() for s in grp} & {j["id"] for j in junk}
    assert r["excluded_market_only"] == 5 and any("market-only" in n for n in r["notes"])


def test_singles_likely_is_by_floor_and_value_only_contains_positive_ev():
    r = SS.suggest_tickets(pool_mixed(), "draftkings", simulate=False, n_singles=4)
    likely = r["singles"]["likely"]
    assert len(likely) == 4
    floors = [s["score"]["floor"] for s in likely]
    assert floors == sorted(floors, reverse=True)
    value = r["singles"]["value"]
    assert value and all(s["score"]["ev_pct"] > 0 for s in value)
    ev_floors = [s["score"]["ev_floor_pct"] for s in value]
    assert ev_floors == sorted(ev_floors, reverse=True)
    assert all(s["stake"] <= 0.02 * 1000 + 1e-9 for grp in r["singles"].values() for s in grp)


def test_single_stake_is_quarter_kelly_at_the_floor_and_zero_without_an_edge_there():
    strong = leg(1, p=0.75, price=100, n_eff=60)
    weak = leg(2, p=0.52, price=-110, n_eff=8)
    r = SS.suggest_tickets([strong, weak], "draftkings", simulate=False, bankroll=1000)
    by = {s["leg"]["id"]: s for s in r["singles"]["likely"]}
    fl = by[strong["id"]]["score"]["floor"]
    assert by[strong["id"]]["stake"] == pytest.approx(O.kelly_stake(fl, 100, 1000, 0.25, 0.02))
    assert by[weak["id"]]["stake"] == 0.0


def test_pickem_books_get_no_singles_and_power_flex_or_pick6_tickets():
    pool = [leg(i, p=0.62 + 0.01 * (i % 4), price=None, n_eff=25) for i in range(8)]
    for l in pool:
        l["book"] = "prizepicks"
    pp = SS.suggest_tickets(pool, "prizepicks", sizes=(2, 3), simulate=False)
    assert pp["singles"] == {"likely": [], "value": []}
    assert {t["mode"] for t in pp["tickets"]} <= {"power", "flex"} and pp["tickets"]
    assert {t["mode"] for t in SS.suggest_tickets(pool, "pick6", sizes=(2, 3), simulate=False)["tickets"]} == {"pick6"}


def test_every_ticket_honours_the_constraints_and_is_positive_ev_as_modelled():
    pool = pool_mixed(16)
    r = SS.suggest_tickets(pool, "draftkings", sizes=(2, 3, 4), max_per_game=1, simulate=False)
    assert r["tickets"]
    for t in r["tickets"]:
        games = [l["game"] for l in t["legs"]]
        assert len(set(games)) == len(games)                       # max one leg per game
        assert len({l["player"] for l in t["legs"]}) == t["k"]
        assert t["ev_indep"] > 0
        assert all(l["p"] >= 0.45 for l in t["legs"])


def _one_game_pool(n=6):
    return [leg(i, p=0.60, price=100, game="BOS @ NYK", n_eff=25) for i in range(n)]


def test_the_per_game_cap_blocks_big_tickets_from_one_game_and_no_cap_allows_them():
    pool = _one_game_pool()
    capped = SS.suggest_tickets(pool, "draftkings", sizes=(2, 3, 4), max_per_game=2, simulate=False)
    assert {t["k"] for t in capped["tickets"]} == {2}                        # 3- and 4-leg tickets would break the cap
    free = SS.suggest_tickets(pool, "draftkings", sizes=(2, 3, 4), max_per_game=SS.NO_GAME_CAP, simulate=False)
    assert {t["k"] for t in free["tickets"]} == {2, 3, 4}
    for t in free["tickets"]:
        assert {l["game"] for l in t["legs"]} == {"BOS @ NYK"}
        assert len({l["player"] for l in t["legs"]}) == t["k"]               # still one leg per player


def test_no_game_cap_is_bigger_than_any_ticket_size():
    assert SS.NO_GAME_CAP > 12


def test_min_leg_probability_filters_candidates():
    r = SS.suggest_tickets(pool_mixed(), "draftkings", min_leg_p=0.60, simulate=False)
    assert all(l["p"] >= 0.60 for t in r["tickets"] for l in t["legs"])


def test_best_value_ticket_is_the_brute_force_optimum_of_conservative_ev():
    pool = [leg(i, p=0.50 + 0.03 * i, price=[100, 110, -105, 120, -120, 105][i], n_eff=[10, 30, 20, 40, 15, 25][i],
                game=f"G{i}") for i in range(6)]
    r = SS.suggest_tickets(pool, "draftkings", sizes=(3,), simulate=False, min_leg_p=0.0, n_candidates=6)
    tk = next(t for t in r["tickets"] if "Best value" in t["strategies"])
    score = SS.score_lookup(pool)
    best = None
    for combo in itertools.combinations(pool, 3):
        dec = math.prod(SL.leg_decimal(l) for l in combo)
        mean, _, _ = SS._stats([l["p"] for l in combo], [0, 0, 0, dec])
        if mean <= 1:
            continue
        mf, _, _ = SS._stats([score[l["id"]]["floor"] for l in combo], [0, 0, 0, dec])
        if best is None or mf > best[0]:
            best = (mf, {l["id"] for l in combo})
    assert best is not None and {l["id"] for l in tk["legs"]} == best[1]


def test_identical_tickets_across_strategies_are_merged():
    pool = [leg(i, p=0.70, price=110, n_eff=40) for i in range(2)]
    r = SS.suggest_tickets(pool, "draftkings", sizes=(2,), simulate=False, min_leg_p=0.0)
    assert len(r["tickets"]) == 1
    assert set(r["tickets"][0]["strategies"]) == {"Safest", "Best value", "Balanced"}


def test_no_positive_ev_ticket_means_no_ticket_and_a_note_never_a_bad_suggestion():
    pool = [leg(i, p=0.40, price=-150) for i in range(6)]
    r = SS.suggest_tickets(pool, "draftkings", sizes=(2, 3), simulate=False, min_leg_p=0.0)
    assert r["tickets"] == [] and any("No +EV" in n for n in r["notes"])
    assert r["singles"]["value"] == [] and any("No single is +EV" in n for n in r["notes"])


def test_too_few_legs_and_empty_pool_explain_themselves():
    assert SS.suggest_tickets([], "draftkings")["tickets"] == []
    assert SS.suggest_tickets([], "draftkings")["notes"]
    r = SS.suggest_tickets([leg(1)], "draftkings", simulate=False)
    assert r["tickets"] == [] and any("Fewer than two" in n for n in r["notes"])


def test_legs_the_book_does_not_post_are_skipped_and_reported():
    a = [leg(i, p=0.65, price=110) for i in range(4)]
    a[0]["at_book"] = False
    r = SS.suggest_tickets(a, "draftkings", simulate=False, min_leg_p=0.0)
    assert a[0]["id"] not in {l["id"] for t in r["tickets"] for l in t["legs"]}
    assert any("doesn't post" in n for n in r["notes"])


def test_simulated_fields_and_same_game_correlation_are_reflected():
    pool = [leg(i, p=0.68, price=115, n_eff=40, game="SAME") for i in range(3)]
    r = SS.suggest_tickets(pool, "draftkings", sizes=(2,), max_per_game=2, simulate=True, min_leg_p=0.0)
    t = r["tickets"][0]
    assert t["p_all"] is not None and t["p_all"] > t["p_all_indep"]          # same-game Overs move together
    assert t["ev_haircut"] < t["ev"]                                        # the haircut costs EV
    assert 0.0 <= t["p_ev_positive"] <= 1.0
    assert t["stake"] is not None and t["stake"] <= 20.0 + 1e-9


def test_flex_ticket_has_no_kelly_stake_but_power_does():
    pool = [leg(i, p=0.70, price=None, n_eff=40) for i in range(6)]
    r = SS.suggest_tickets(pool, "prizepicks", sizes=(3,), simulate=True, min_leg_p=0.0)
    by_mode = {t["mode"]: t for t in r["tickets"]}
    assert by_mode["flex"]["stake"] is None
    assert by_mode["power"]["stake"] is not None


def test_suggestions_are_reproducible():
    a = SS.suggest_tickets(pool_mixed(), "draftkings", simulate=True)
    b = SS.suggest_tickets(pool_mixed(), "draftkings", simulate=True)
    assert [(t["mode"], t["k"], [l["id"] for l in t["legs"]], t["ev"]) for t in a["tickets"]] == \
           [(t["mode"], t["k"], [l["id"] for l in t["legs"]], t["ev"]) for t in b["tickets"]]


def test_ticket_titles():
    assert SS.ticket_title({"k": 3, "mode": "parlay"}) == "3-leg parlay"
    assert SS.ticket_title({"k": 5, "mode": "flex"}) == "5-leg Flex Play"
    assert SS.ticket_title({"k": 2, "mode": "pick6"}) == "2-leg Pick6"
