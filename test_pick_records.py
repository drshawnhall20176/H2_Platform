import pick_records as PR


def test_verdicts():
    assert PR.verdict(5, 10) == "new"
    assert PR.verdict(38, 97) == "fade"
    assert PR.verdict(59, 138) == "losing"
    assert PR.verdict(199, 382) == "ok"
    assert PR.verdict(47, 100, line_market=True) == "losing" and PR.verdict(48, 100, line_market=True) == "ok"


def test_game_lab_line_is_the_home_margin_and_stored_result_wins():
    rec = {"home": "Akron", "away": "Ohio", "line": -13.5, "model_margin": -4.64, "pick": "home",
           "final_home": 20, "final_away": 28, "result": None, "line_total": 51.5, "model_total": 54.5}
    g = PR.grade_lean(rec)
    assert g["Spread"] == "win"          # Akron +13.5, lost by 8
    assert g["Total"] == "loss"          # model over 51.5, 48 scored
    assert g["Moneyline"] == "win"       # model had Ohio winning; Ohio won
    rec["result"] = "loss"
    assert PR.grade_lean(rec)["Spread"] == "loss"


def test_home_spread_records():
    rec = {"home_spread": -7.5, "model_margin": 10, "final_home": 30, "final_away": 20}
    assert PR.grade_lean(rec)["Spread"] == "win"
    rec["final_home"] = 25
    assert PR.grade_lean(rec)["Spread"] == "loss"


def test_annotate_hides_losing_types():
    rows = [{"sport": "NHL", "use": "🎯 Single only", "kind": "Prop"}, {"sport": "NHL", "use": "🔒 🎟️ Parlay leg"}]
    PR.annotate_props(rows, lambda sp: {"🎯 Single only": (38, 97), "🎟️ Parlay leg": (24, 43)})
    assert rows[0]["verdict"] == "fade" and "59–38" in rows[0]["record"]
    assert rows[1]["verdict"] == "ok" and rows[1]["record"].startswith("24–19")


def test_your_picks_bands():
    bets = [{"is_real_bet": 1, "result": "win", "model_prob": 0.62, "stake": 4, "entry_odds": -110, "market": "Points"},
            {"is_real_bet": 1, "result": "loss", "model_prob": 0.45, "stake": 4, "entry_odds": -110, "market": "Points"},
            {"is_real_bet": 1, "result": "loss", "model_prob": 0.45, "stake": 4, "market": "Points", "ticket": "t"},
            {"is_real_bet": 1, "result": "win", "stake": 10, "entry_odds": 300, "market": "Parlay"},
            {"is_real_bet": 0, "result": "win", "model_prob": 0.7, "stake": 4, "market": "Points"}]
    out = {(r["Bets"], r["Band"]): r for r in PR.your_picks(bets)}
    assert out[("Single", "Model 60%+")]["P/L"] == round(4 * 100 / 110, 2)
    assert out[("Single", "Against the model (<50%)")]["P/L"] == -4
    assert out[("Parlay leg", "Against the model (<50%)")]["P/L"] is None
    assert out[("Parlay", "All")]["P/L"] == 30
    assert len(out) == 4


# ------------------------------------------------------------------ Nov 16: a Why that differs game to game
def _g(edge, home_spread=-5.0):
    return {"model_margin": -home_spread + edge, "home_spread": home_spread, "edge": edge, "home": "H", "away": "A"}


def test_spread_why_says_this_games_gap_and_how_that_size_has_done():
    recs = {"Spread": (30, 60), ("Spread", 0): (10, 22), ("Spread", 2): (14, 23)}
    close = PR.spread_why("NCAAMB", _g(1.1), recs, 0.508)
    mid = PR.spread_why("NCAAMB", _g(3.9), recs, 0.508)
    big = PR.spread_why("NCAAMB", _g(-19.1), recs, 0.508)
    assert len({close, mid, big}) == 3                                        # no longer one sentence on every row
    assert close.startswith("Close to the book (1.1 pts) · 0–3 pt gaps, last 30 days: 10–12 (45%")
    assert "losing" in close and close.endswith("long backtest 51%")
    assert mid == "Moderate gap (3.9 pts) · 3–6 pt gaps: none graded in the last 30 days · long backtest 51%"
    assert big.startswith("Big gap (19.1 pts) · 6+ pt gaps, last 30 days: 14–9 (61%")
    assert PR.spread_why("NBA", _g(7.0), {}, None) == "Big gap (7.0 pts) · 7+ pt gaps: none graded in the last 30 days"
    assert PR.spread_why("NCAAMB", {"edge": None}, recs, 0.508) == "long backtest: the model's side covered 51%"
    assert PR.spread_why("NBA", {}, None, None) == "no tested edge in this league"


def test_band_table_lists_every_gap_size_with_its_record():
    rows = PR.band_table("NCAAMB", {("Spread", 0): (10, 22), ("Spread", 2): (3, 5)})
    assert [r["Gap size"] for r in rows] == ["Close to the book: 0–3 pt gap", "Moderate gap: 3–6 pt gap",
                                             "Big gap: 6+ pt gap"]
    assert [(r["Record"], r["Graded"], r["Read"]) for r in rows] == [
        ("10–12", 22, "Losing"), ("—", 0, "No games yet"), ("3–2", 5, "Too few to judge")]
    assert rows[0]["Hit rate"] == 0.455 and rows[1]["Hit rate"] is None


def test_likely_range_is_honest_about_small_samples():
    lo, hi = PR.likely_range(11, 14)
    assert 0.6 < lo < 0.65 and 0.87 < hi < 0.91
    lo2, hi2 = PR.likely_range(110, 140)
    assert hi2 - lo2 < (hi - lo) / 2
    assert PR.range_text(0, 0) == "—" and PR.likely_range(0, 0) is None


def test_money_pick_rule_and_record(monkeypatch):
    """Nov 20 rule: edge 3-20% at a sportsbook price, chance 40%+, the price within 3% of the books' no-vig fair."""
    import props_engine as PE, postgame as PG
    monkeypatch.setitem(PE.MONEY_TEST, "to", "2000-01-01")             # outside the live test: NBA only (default)
    monkeypatch.setattr(PE, "money_sports", lambda now=None, day=None: ("NBA",))
    ok = dict(chance=0.47, mev=-0.01)
    assert PE.is_money("NBA", 0.08, **ok) and PE.is_money("NBA", 0.03, **ok) and not PE.is_money("NBA", 0.02, **ok)
    assert not PE.is_money("NBA", 0.20, **ok)
    assert not PE.is_money("NBA", 0.08, chance=0.35, mev=0.0)           # a long shot
    assert not PE.is_money("NBA", 0.08, chance=0.47, mev=-0.05)         # a juiced price
    assert not PE.is_money("NBA", 0.08)                                 # no chance / market check: never
    assert not PE.is_money("NHL", 0.08, **ok) and not PE.is_money("NBA", 0.08, book="prizepicks", **ok)
    assert not PE.play_is_money("NBA", {"EV": 0.08, "RealPrice": None, "ModelProb": 0.47, "MarketProb": 0.47})
    # +110 at a 47% no-vig: 0.47 * 2.1 - 1 = -1.3% -> fair enough
    assert PE.play_is_money("NBA", {"EV": 0.08, "RealPrice": 110, "PricedAt": "draftkings", "ModelProb": 0.51,
                                    "MarketProb": 0.47})
    assert not PE.play_is_money("NBA", {"EV": 0.08, "RealPrice": -150, "PricedAt": "draftkings", "ModelProb": 0.64,
                                        "MarketProb": 0.55})               # 0.55 * 1.667 - 1 = -8%: juiced
    rows = [{"sport": "NBA", "ev": 0.08, "price": 110, "result": "hit", "chance": 0.51, "side": "Over",
             "p_market": 0.47, "book": "draftkings"},
            {"sport": "NBA", "ev": 0.07, "price": -110, "result": "miss", "chance": 0.56, "side": "Under",
             "p_market": 0.48, "book": "fanduel"},
            {"sport": "NBA", "ev": 0.02, "price": -110, "result": "hit", "chance": 0.55, "side": "Over",
             "p_market": 0.5}]
    r = PG.money_record(rows)
    assert r["Graded"] == 2 and r["Hits"] == 1 and abs(r["Profit per $1"] - 0.05) < 1e-9


def test_money_live_test_turns_every_sport_on_for_its_dates(monkeypatch):
    import model_store as MS
    import props_engine as PE
    PE._MONEY_CACHE.clear()
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: {"sports": {"NBA": {"on": False}}})
    monkeypatch.setattr(PE, "MONEY_TEST", {"from": "2026-11-20", "to": "2026-11-23", "sports": ("NBA", "NHL")})
    assert PE.money_sports(day="2026-11-21") == ("NBA", "NHL")
    assert PE.money_sports(day="2026-11-24") == () and PE.money_sports(day="2026-11-19") == ()
    s = {"sport": "NHL", "slate_date": "2026-11-21", "ev": 0.05, "price": 120, "chance": 0.49, "side": "Over",
         "p_market": 0.45, "book": "draftkings", "market": "Shots on Goal"}
    assert PE.snapshot_is_money("NHL", s) and not PE.snapshot_is_money("NHL", dict(s, slate_date="2026-11-25"))
    PE._MONEY_CACHE.clear()


def test_money_scoreboard_adds_up_the_test_slates():
    import money_scoreboard as MSB
    reviews = {("NBA", "2026-11-21"): {"slates": {"2026-11-20": {"money": {"hits": 3, "misses": 2, "profit": 0.10,
                                                                            "needed": 0.45}}}},
               ("NBA", "2026-11-22"): {"slates": {"2026-11-21": {"money": {"hits": 1, "misses": 3, "profit": -0.5,
                                                                            "needed": 0.5}}}},
               ("NHL", "2026-11-22"): {"slates": {"2026-11-20": {"money": {"hits": 2, "misses": 0, "profit": 1.0,
                                                                            "needed": 0.48}}}}}
    b = MSB.scoreboard(load=lambda sp, m: reviews.get((sp, m)), today="2026-11-22",
                       test={"from": "2026-11-20", "to": "2026-11-23", "sports": ("NBA", "NHL")})
    nba, nhl = b["sports"]
    assert (nba["hits"], nba["misses"], round(nba["units"], 2)) == (4, 5, -1.5)
    assert (nhl["hits"], nhl["misses"], nhl["units"]) == (2, 0, 2.0)          # finished on a later morning
    assert b["total"]["n"] == 11 and abs(b["total"]["units"] - 0.5) < 1e-9
    rows = MSB.table(b, {"NBA": 4})
    assert rows[0]["Record"] == "4–5" and rows[0]["Today"] == 4


def test_money_picks_reach_today_even_tagged_no_edge():
    import props_engine as PE, todays_best as TB
    p = {"Player": "A", "Market": "Points", "Side": "Over", "Line": 20.5, "ModelProb": 0.55, "EV": 0.09,
         "RealPrice": -110, "PricedAt": "draftkings", "Use": PE.USE_PASS, "Cushion": 0.05, "MarketProb": 0.51}
    rows = TB.props_rows("NBA", [p, dict(p, Player="B", EV=0.02)])
    assert [r["player"] for r in rows] == ["A"] and rows[0]["money"]


def test_untested_markets_are_not_money_picks():
    import props_engine as PE
    ok = dict(chance=0.45, mev=0.0)
    assert not PE.is_money("NBA", 0.10, market="Steals", **ok) and PE.is_money("NBA", 0.10, market="Threes Made", **ok)
    assert not PE.play_is_money("NBA", {"EV": 0.13, "RealPrice": 182, "Market": "Steals", "ModelProb": 0.4,
                                        "MarketProb": 0.36})


def test_money_record_text(monkeypatch):
    import model_store as MS, props_engine as PE
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: {"sports": {"NBA": {"n": 1483, "hit": 0.5172, "roi": 0.0439}}})
    assert PE.money_record_text("NBA") == "💰 767–716 (52%, +4.4%/$1)"
    assert PE.money_record_text("NFL") is None


def test_lock_needs_a_price_that_pays_and_stakes_are_quarter_kelly():
    """Nov 20: 🔒 only where the price pays (NHL 🔒 hit as stated but lost 6.2% at their prices)."""
    import props_engine as PE
    assert PE.is_lock(0.65, 0.2) and PE.is_lock(0.65, 0.2, ev=0.01) and not PE.is_lock(0.65, 0.2, ev=-0.03)
    assert PE.play_is_lock({"ModelProb": 0.65, "Cushion": 0.2, "EV": -0.05, "RealPrice": None})   # no price: no gate
    assert not PE.play_is_lock({"ModelProb": 0.65, "Cushion": 0.2, "EV": -0.05, "RealPrice": -200})
    # 55% at +100: Kelly 10% -> quarter 2.5% -> capped 2u; 50% at +110: Kelly 4.5% -> 1.25u (rounded to .25)
    assert PE.stake_units(0.55, 100) == 2.0 and PE.stake_units(0.50, 110) == 1.25
    assert PE.stake_units(0.45, -110) is None and PE.stake_units(None, 100) is None
