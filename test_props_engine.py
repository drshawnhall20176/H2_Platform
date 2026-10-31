"""
test_props_engine.py — offline tests for the shared Player props modelling core (props_engine.py).

    python -m pytest test_props_engine.py
"""

import math

import props_engine as PE
import player_props as PPR
import position_matchups as PM


# --------------------------------------------------------------------------- recency + opportunity
def test_recency_weights_favor_new_games():
    w = PE.recency_weights(9)
    assert w[0] == 1.0 and abs(w[4] - 0.5) < 1e-12 and w[8] < w[4]
    assert PE.wmean([10, 10, 10]) == 10
    assert PE.wmean([20, 10, 10, 10]) > 12.5                       # the newest game counts most


def test_rate_and_opportunity_skips_dnps():
    rate, opp = PE.rate_and_opportunity([30, 0, 20], [30, 0, 20])
    assert abs(rate - 1.0) < 1e-12 and 20 < opp < 30


# --------------------------------------------------------------------------- distributions
def test_k_needed_handles_half_and_alt_lines():
    assert PE.k_needed(1.5) == 2 and PE.k_needed(2) == 2 and PE.k_needed(0.5) == 1


def test_count_sf_matches_poisson_and_widens_with_variance():
    lam = 1.2
    poisson_2plus = 1 - math.exp(-lam) * (1 + lam)
    assert abs(PE.count_sf(lam, lam, 2) - poisson_2plus) < 1e-9
    assert PE.count_sf(lam, 3.0, 4) > PE.count_sf(lam, lam, 4)       # fatter tail
    assert PE.count_sf(lam, 3.0, 1) < PE.count_sf(lam, lam, 1)       # more zeros


def test_low_count_market_is_not_a_normal_curve_question():
    vals = [1, 0, 2, 1, 1, 0, 3, 1]
    p_count = PE.prob_over(1.1, vals, 0.5, "count")
    p_norm = PE.prob_over(1.1, vals, 0.5, "normal")
    assert 0.55 < p_count < 0.75 and abs(p_count - p_norm) > 0.03


# --------------------------------------------------------------------------- prices, market, blend
def test_devig_and_one_sided_prices():
    assert abs(PE.devig(-110, -110) - 0.5) < 1e-12
    assert PE.devig(-150, 120) > 0.55
    assert abs(PE.market_prob(-110, None) - (110 / 210) / 1.045) < 1e-12
    assert PE.implied(50) is None and PE.decimal(-200) == 1.5


def test_shop_picks_the_main_line_best_prices_and_consensus():
    offers = [
        {"market": "player_points", "player": "Jayson Tatum", "point": 27.5,
         "over": {"draftkings": -115, "fanduel": -105, "betmgm": -110}, "under": {"draftkings": -105, "fanduel": -115, "betmgm": -110}},
        {"market": "player_points", "player": "Jayson Tatum", "point": 29.5, "over": {"draftkings": 140}, "under": {}},
        {"market": "player_points", "player": "Jaylen Brown", "point": 24.5, "over": {"fanduel": -110}, "under": {"fanduel": -110}},
    ]
    mine = PE.offers_for(offers, "jayson tatum", "player_points")
    s = PE.shop(mine)
    assert s["line"] == 27.5 and s["best_over"] == ("fanduel", -105) and s["best_under"] == ("draftkings", -105)
    assert abs(s["p_market"] - 0.5) < 0.01 and s["books"] == 3
    alt = PE.shop(mine, 29.5)
    assert alt["line"] == 29.5 and alt["best_under"] is None and alt["p_market"] < 0.42
    assert PE.shop(mine, 31.5) is None


def test_read_line_needs_value_at_the_real_price():
    vals = [30, 28, 31, 29, 30, 32, 27, 30]
    strong = PE.read_line(32.0, vals, 27.5, "normal", over_price=-110, under_price=-110)
    assert strong["lean"] == "Over" and strong["ev"] > PE.MIN_EV
    # the market already prices it in: the blend pulls toward 50/50, no bet at -200
    pricey = PE.read_line(32.0, vals, 27.5, "normal", over_price=-300, under_price=240)
    assert pricey["lean"] == "No lean"
    # no price: the old projection-vs-line rule
    bare = PE.read_line(32.0, vals, 27.5, "normal")
    assert bare["lean"] == "Over" and bare["p_market"] is None


def test_calibration_shrinks_toward_even():
    assert abs(PE.calibrate(0.7, 0.5) - 0.6) < 1e-12 and PE.calibrate(0.7, 1.0) == 0.7


# --------------------------------------------------------------------------- game environment
def test_implied_team_totals_and_environment():
    home, away = PE.implied_team_totals(230, -6)
    assert home == 118 and away == 112
    f = PE.env_factor(118, 110)
    assert abs(f - 118 / 110) < 1e-12 and PE.env_factor(160, 110) == PE.ENV_RANGE[1]
    m_pts = PE.env_multiplier(1.1, {"pts": 20}, PPR.ENV_WEIGHTS)
    m_reb = PE.env_multiplier(1.1, {"reb": 10}, PPR.ENV_WEIGHTS)
    assert abs(m_pts - 1.1) < 1e-12 and 1.0 < m_reb < m_pts


# --------------------------------------------------------------------------- rest + blowouts
def test_back_to_back_and_rested_opponents():
    star = PE.rest_effect(1, 2, 34, "basketball")
    assert star["opp_mult"] < 1 and star["rate_mult"] < 1 and "B2B: rest risk" in star["flags"]
    bench = PE.rest_effect(1, 2, 18, "basketball")
    assert bench["opp_mult"] == 1 and "B2B" in bench["flags"]
    tired_opp = PE.rest_effect(2, 1, 30, "basketball")
    assert tired_opp["rate_mult"] > 1 and "Opp on B2B" in tired_opp["flags"]
    assert PE.rest_effect(None, None, 34, "basketball") == {"opp_mult": 1.0, "rate_mult": 1.0, "flags": []}
    assert "B2B: backup goalie likely" in PE.rest_effect(1, 2, 60, "hockey", role="goalie")["flags"]


def test_blowout_cuts_starters_and_lifts_bench():
    starter = PE.blowout_effect(-13.5, 34)
    bench = PE.blowout_effect(13.5, 14)
    assert starter["opp_mult"] < 0.97 and bench["opp_mult"] > 1
    assert PE.blowout_effect(-5, 34)["opp_mult"] == 1.0


# --------------------------------------------------------------------------- next man up
def test_fresh_absence_only():
    assert PE.fresh_absence(["g3", "g2"], ["g3", "g2", "g1"])
    assert not PE.fresh_absence(["g0"], ["g3", "g2", "g1"])              # he's been out: already priced in


def test_redistribute_moves_minutes_to_his_position_first_and_bumps_usage():
    players = [
        {"pid": 1, "name": "Star", "slot": "F", "opp": 36, "rate": 1.2, "out": True, "fresh": True},
        {"pid": 2, "name": "Wing", "slot": "F", "opp": 28, "rate": 0.8, "out": False},
        {"pid": 3, "name": "Guard", "slot": "G", "opp": 32, "rate": 0.9, "out": False},
        {"pid": 4, "name": "Big", "slot": "C", "opp": 24, "rate": 0.8, "out": False},
    ]
    res = PE.redistribute(players, cap=40)
    assert res[2]["opp_add"] > res[3]["opp_add"] > 0                   # same position group gets the most
    assert res[2]["opp_add"] + 28 <= 40                                 # capped
    assert all(res[p]["rate_mult"] > 1 for p in (2, 3, 4))              # the lost production isn't all minutes
    assert max(res[p]["rate_mult"] for p in (2, 3, 4)) <= 1 + PE.USAGE_RATE_CAP
    assert "Star" in res[2]["from"]
    stale = [dict(players[0], fresh=False)] + players[1:]
    assert all(v["opp_add"] == 0 and v["rate_mult"] == 1 for v in PE.redistribute(stale).values())


def test_basketball_rows_raise_teammates_when_a_starter_is_freshly_out():
    def g(game, order, pid, name, pos, mins, pts):
        return dict(game=game, order=order, team="BOS", opp="X", pid=pid, name=name, pos=pos,
                    stats={"min": mins, "pts": pts, "reb": 5, "ast": 3})
    cur = []
    for i, d in enumerate(("2026-10-21", "2026-10-23", "2026-10-25")):
        cur += [g(f"g{i}", d, 1, "Tatum", "SF", 36, 30), g(f"g{i}", d, 2, "Hauser", "SF", 22, 10),
                g(f"g{i}", d, 3, "White", "PG", 32, 16)]
    rot = [{"pid": 1, "name": "Tatum", "slot": "F", "avg_min": 36, "status": "Out"},
           {"pid": 2, "name": "Hauser", "slot": "F", "avg_min": 22, "status": None},
           {"pid": 3, "name": "White", "slot": "G", "avg_min": 32, "status": None}]
    healthy = [dict(r, status=None) for r in rot]
    base = {r["pid"]: r for r in PPR.player_rows(healthy, "D", "Points", {}, None, cur, [], mode="season",
                                                 context={"team": "BOS"})}
    out = {r["pid"]: r for r in PPR.player_rows(rot, "D", "Points", {}, None, cur, [], mode="season",
                                                context={"team": "BOS"})}
    assert out[1]["projection"] is None
    assert out[2]["projection"] > base[2]["projection"] * 1.2 and out[2]["opp"] > base[2]["opp"]
    assert any("usage bump" in f for f in out[2]["flags"])


def test_basketball_rows_use_book_lines_and_typed_prices():
    cur = [dict(game=f"t{i}", order=f"2026-10-2{i}", team="BOS", opp="X", pid=7, name="Jayson Tatum", pos="SF",
                stats={"min": 36, "pts": 30, "reb": 8, "ast": 5}) for i in range(5)]
    rot = [{"pid": 7, "name": "Jayson Tatum", "slot": "F", "avg_min": 36, "status": None}]
    offers = [{"market": "player_points_rebounds_assists", "player": "Jayson Tatum", "point": 41.5,
               "over": {"draftkings": -110, "fanduel": -105}, "under": {"draftkings": -110, "fanduel": -115}}]
    r = PPR.player_rows(rot, "D", "PRA", {}, None, cur, [], mode="season", context={"offers": offers})[0]
    assert r["line"] == 41.5 and r["line_src"] == "book" and r["over_price"] == -105 and r["price_src"] == "book"
    assert r["p_market"] is not None and r["p_final"] != r["p_model"]
    typed = PPR.player_rows(rot, "D", "PRA", {}, None, cur, [], lines={7: 42.5}, mode="season",
                            context={"offers": offers, "prices": {7: {"over": 120}}})[0]
    assert typed["line"] == 42.5 and typed["over_price"] == 120 and typed["price_src"] == "manual"
    play = PPR.plays_for_log([typed], "PRA", "X @ BOS")[0]
    if play["Side"] == "Over":
        assert play["RealPrice"] == 120 and play["PriceSource"] == "manual"


def test_basketball_rows_flag_back_to_back_and_blowouts():
    cur = [dict(game=f"t{i}", order=f"2026-10-2{i}", team="BOS", opp="X", pid=7, name="Tatum", pos="SF",
                stats={"min": 36, "pts": 30, "reb": 8, "ast": 5}) for i in range(5)]
    rot = [{"pid": 7, "name": "Tatum", "slot": "F", "avg_min": 36, "status": None}]
    plain = PPR.player_rows(rot, "D", "PRA", {}, None, cur, [], mode="season")[0]
    tired = PPR.player_rows(rot, "D", "PRA", {}, None, cur, [], mode="season",
                            context={"rest_days": 1, "spread": -14.5})[0]
    assert tired["projection"] < plain["projection"] * 0.93
    assert "B2B: rest risk" in tired["flags"] and any(f.startswith("Blowout risk") for f in tired["flags"])
    hot = PPR.player_rows(rot, "D", "PRA", {}, None, cur, [], mode="season", context={"env": 1.08})[0]
    assert hot["projection"] > plain["projection"] and hot["env"] > 1


# --------------------------------------------------------------------------- same-game parlays
def test_sgp_correlation_lifts_same_direction_legs():
    legs = [{"player": "A", "game": "G", "side": "Over", "p": 0.55},
            {"player": "B", "game": "G", "side": "Over", "p": 0.55},
            {"player": "A", "game": "G", "side": "Over", "p": 0.60}]
    r = PE.sgp(legs, book_price=450)
    assert r["p_joint"] > r["p_independent"] and r["lift"] > 1.05 and r["ev"] is not None
    mixed = PE.sgp([{"player": "A", "game": "G", "side": "Over", "p": 0.55},
                    {"player": "B", "game": "G", "side": "Under", "p": 0.55}])
    assert mixed["p_joint"] < mixed["p_independent"]
    assert PE.sgp(legs[:1]) is None


# --------------------------------------------------------------------------- scorecard maths
def test_calibration_tools():
    over_confident = [(0.8, i % 10 < 6) for i in range(100)] + [(0.2, i % 10 < 4) for i in range(100)]
    slope = PE.fitted_slope(over_confident)
    assert 0.3 < slope < 0.7
    b = PE.calibration_buckets(over_confident)
    assert [x["n"] for x in b] == [100, 100] and abs(b[1]["actual"] - 0.6) < 1e-12
    assert PE.fitted_slope(over_confident[:10]) is None
    assert PE.brier([(1.0, True), (0.0, False)]) == 0.0


def test_display_and_log_shapes():
    row = {"pid": 1, "player": "A", "slot": "G", "status": None, "out": False, "opp": 33.2, "form": 30.1, "games": 8,
           "filled": False, "factor": 1.05, "env": 1.03, "projection": 31.4, "line": 29.5, "over_price": -110,
           "under_price": -110, "book": {"best_over": ("fanduel", -105), "best_under": None}, "hit": (6, 8),
           "p_final": 0.58, "ev": 0.107, "lean": "Over", "side": "Over", "price_src": "book", "flags": ["B2B"]}
    d = PE.display([row])[0]
    assert d["Best price"] == "O -105 fanduel" and d["Lean"] == "🟢 Over" and d["Notes"] == "B2B"
    assert d["Matchup"] == "+5%" and d["Game env"] == "+3%"
    p = PE.plays_for_log([row], "Points", "X @ Y")[0]
    assert p["RealPrice"] == -110 and p["PriceSource"] == "book" and p["Side"] == "Over"
    assert PM.SUPPORTED_SPORTS  # module import sanity


def test_typed_prices_log_as_manual_and_count_toward_clv():
    import betlog as B
    import quick_log
    play = {"Player": "A", "PlayerId": 1, "Game": "X @ Y", "Market": "PRA", "Side": "Over", "Line": 40.5,
            "ModelProb": 0.58, "Fair": -138, "RealPrice": 120, "PriceSource": "manual"}
    f = quick_log.bet_log_fields_from_play(play, "2026-10-28", "NBA", stake=5)
    assert f["entry_odds"] == 120 and f["entry_odds_source"] == "manual"
    clv = B.real_price_clv_summary([{"entry_odds": 120, "close_odds": 100, "entry_odds_source": "manual"},
                                    {"entry_odds": -110, "close_odds": -120, "entry_odds_source": "book"},
                                    {"entry_odds": -110, "close_odds": -150, "entry_odds_source": "model_fair"}])
    assert clv["n_real_price"] == 2 and clv["n_manual"] == 1 and clv["n_book"] == 1 and clv["clv_n"] == 2


def test_compact_view_orders_leans_first_and_never_leaves_a_cell_blank():
    rows = [{"pid": 1, "player": "NoLine", "slot": "G", "out": False, "line": None, "projection": 9.0, "flags": []},
            {"pid": 2, "player": "Lean", "slot": "F", "out": False, "line": 20.5, "side": "Over", "p_final": 0.62,
             "over_price": -110, "under_price": -110, "ev": 0.18, "lean": "Over", "projection": 24.0, "hit": (3, 4),
             "book": {"best_over": ("fanduel", -110)}, "flags": ["B2B"]},
            {"pid": 3, "player": "Hurt", "slot": "C", "out": True, "status": "Out", "line": None, "projection": None}]
    view = PE.display_compact(rows)
    assert [v["Player"].split()[0] for v in view] == ["Lean", "NoLine", "Hurt"]
    assert view[0]["Pick"] == "Over 20.5" and view[0]["Chance"] == "62%" and view[0]["Price"] == "-110 fanduel"
    assert view[1]["Pick"] == "No line posted" and view[2]["Lean"] == "Out tonight"
    assert all(str(v).strip() for row in view for v in row.values())
    reads = PE.best_reads(rows, {2: "ATL"})
    assert len(reads) == 1 and reads[0]["Team"] == "ATL" and reads[0]["Why"].startswith("projects 24.0")
    assert "Form" in PE.display_compact(rows, details=True)[0]


def test_a_fresh_absence_bump_is_dampened_and_capped():
    """Oct 28: the bumps ran far past the books (Jay Huff 7.6 -> 14.4). Only part of the minutes reach the rotation,
    and no teammate's minutes jump more than 35% of his own or 8."""
    players = [
        {"pid": 1, "name": "Starter C", "slot": "C", "opp": 32, "rate": 0.5, "out": True, "fresh": True},
        {"pid": 2, "name": "Backup C", "slot": "C", "opp": 15, "rate": 0.5, "out": False},
        {"pid": 3, "name": "Guard", "slot": "G", "opp": 34, "rate": 0.6, "out": False},
    ]
    res = PE.redistribute(players, cap=42)
    assert res[2]["opp_add"] <= min(PE.BUMP_MAX_ABS, PE.BUMP_MAX_FRAC * 15) + 1e-9      # 5.25, not ~19
    assert res[3]["opp_add"] <= PE.BUMP_MAX_ABS + 1e-9
    assert sum(r["opp_add"] for r in res.values()) <= 32 * PE.REDISTRIBUTE_SHARE + 1e-9
    assert all(r["rate_mult"] <= 1 + PE.USAGE_RATE_CAP + 1e-9 for r in res.values())
    proj = (15 + res[2]["opp_add"]) * 0.5 * res[2]["rate_mult"]
    assert proj < 7.5 * 1.5                                                           # a bump, not a doubling


def test_star_out_gives_top_options_more_usage_and_flags_their_unders():
    # Oct 31: with a star freshly out, Unders on the players who take over his shots went 0-8 (Oct 29-30). The top two
    # by production get a bigger share of the leftover usage (higher rate cap) and are marked primary.
    team = [{"pid": "star", "name": "Star", "slot": "G", "opp": 36, "rate": 0.80, "out": True, "fresh": True},
            {"pid": "a", "name": "A", "slot": "G", "opp": 34, "rate": 0.60},
            {"pid": "b", "name": "B", "slot": "F", "opp": 32, "rate": 0.55},
            {"pid": "c", "name": "C", "slot": "F", "opp": 22, "rate": 0.40},
            {"pid": "d", "name": "D", "slot": "C", "opp": 18, "rate": 0.35}]
    old = PE.redistribute(team, cap=42.0)
    new = PE.redistribute(team, cap=42.0, primary_n=PE.PRIMARY_N)
    assert new["a"].get("primary") and new["b"].get("primary") and not new["c"].get("primary")
    assert new["a"]["rate_mult"] > old["a"]["rate_mult"] and new["a"]["rate_mult"] <= 1 + PE.USAGE_RATE_CAP_PRIMARY
    assert new["d"]["rate_mult"] <= old["d"]["rate_mult"]                     # bench share shrinks, never grows
    assert not old["a"].get("primary")                                        # hockey / default callers unchanged
    row = {"projection": 18.0, "line": 20.5, "absorbs": True}
    assert any("star freshly out" in w for w in PE.leg_warnings(row, "Under", 20.5))
    assert not any("star freshly out" in w for w in PE.leg_warnings(row, "Over", 20.5))


def test_same_game_picks_are_flagged():
    picks = [{"game": "ORL @ TOR", "label": "Bane U19.5"}, {"game": "ORL @ TOR", "label": "Murray-Boyles U10.5"},
             {"game": "NYK @ PHI", "label": "Embiid U28.5"}]
    assert PE.same_game_stacks(picks) == {"ORL @ TOR": ["Bane U19.5", "Murray-Boyles U10.5"]}
    assert "ORL @ TOR" in PE.stack_warning(picks) and PE.stack_warning(picks[1:]) is None
    assert PE.stack_warning([{"Game": "A", "Player": "x"}, {"Game": "A", "Player": "y"}], "Game", "Player")


def test_hockey_rates_are_pulled_toward_the_position_group():
    # Oct 31: a forward with no goal in 10 games projected 0.0 goals. Now his rate leans on the forward group's.
    import hockey_props as HP
    pg = [{"role": "skater", "pos": "C", "stats": {"toi": 18.0, "g": 1.0}},
          {"role": "skater", "pos": "C", "stats": {"toi": 18.0, "g": 0.0}},
          {"role": "skater", "pos": "D", "stats": {"toi": 22.0, "g": 0.0}}]
    pri = HP.group_rates(pg, "g")
    assert abs(pri["F"] - 1 / 36) < 1e-9 and pri["D"] == 0.0
    cold = HP.shrunk_rate(0.0, [17.0] * 10, "g", pri["F"])
    assert 0 < cold < pri["F"]                                     # no longer zero, still below the group
    hot = HP.shrunk_rate(0.06, [17.0] * 10, "g", pri["F"])
    assert pri["F"] < hot < 0.06                                   # a hot streak is tempered, not erased
    assert HP.shrunk_rate(0.4, [30.0], "saves", 0.9) == 0.4        # goalies' save rate is left alone


def test_a_line_far_from_the_projection_needs_a_news_check_even_without_a_price():
    # Oct 31: an opening-week college guard projected 4.7 (last season's bench minutes) vs a pick'em line of 16.5
    # showed "Under 99%" -- the gap check only ran when there was a price.
    vals = [4.0, 6.0, 3.0, 5.0, 5.0]
    r = PE.read_line(4.7, vals, 16.5, "normal")
    assert r["gap"] == "big" and r["lean"] == "Check news"
    assert PE.read_line(4.7, vals, 16.5, "normal", news_checked=True)["lean"] == "Under"
    assert PE.read_line(15.9, [15, 17, 14, 16, 18], 16.5, "normal")["gap"] != "big"
