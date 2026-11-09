import coach as CO


def _b(i, res, mp=None, odds=-110, stake=4, market="Points", sport="NBA", ticket=None, day="2026-11-07", real=1):
    return {"id": i, "result": res, "model_prob": mp, "entry_odds": odds, "stake": stake, "market": market,
            "sport": sport, "ticket": ticket, "slate_date": day, "is_real_bet": real}


def test_breakeven():
    assert round(CO.breakeven(-110), 3) == 0.524 and round(CO.breakeven(150), 3) == 0.4 and CO.breakeven(None) is None


def test_report_card_and_rules():
    bets = [_b(i, "loss" if i % 3 else "win", 0.45) for i in range(12)]           # against the model: 4-8
    bets += [_b(100 + i, "win" if i % 2 else "loss", 0.62, odds=-180) for i in range(12)]   # 60%+: 6-6 at -180
    bets += [_b(200, "win", None, odds=400, stake=10, market="Parlay", ticket="T"),
             _b(201, "loss", 0.7, ticket="T", stake=0)]
    card = {r["What"]: r for r in CO.report_card(bets)}
    assert card["Against the model (under 50%)"]["Record"] == "4–8"
    assert card["Against the model (under 50%)"]["Verdict"].startswith("🔴")
    assert card["Parlays (each ticket once)"]["Record"] == "1–0"
    assert card["Model liked it a lot (60%+)"]["Record"] == "6–7"                 # the parlay leg counts as a pick
    text = " ".join(CO.rules(bets))
    assert "Don't bet against the model" in text and "Avoid −151 to −200" in text
    prices = {r["What"]: r for r in CO.price_check(bets)}
    assert prices["−151 to −200"]["Bets"] == 12


def test_fake_bets_and_period_ignored():
    bets = [_b(1, "win", real=0), _b(2, "win", day="2026-01-01")]
    assert CO.report_card(CO.in_period(bets, 30, today=__import__("datetime").date(2026, 11, 8)))[0]["Bets"] == 0


def test_judge_verdicts():
    h = CO._history([])
    good = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.62, "price": -110, "use": "🎯 Single only"}, h, (60, 100))
    assert good["verdict"] == "🟢 Good bet" and round(good["edge"], 3) == round(0.60 - 110 / 210, 3)
    pricey = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.60, "price": -180, "use": "🎯 Single only"}, h)
    assert pricey["verdict"] == "🔴 Skip" and "too expensive" in pricey["why"]
    against = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.45, "price": 150}, h)
    assert against["verdict"] == "🔴 Skip"
    losing_tag = CO.judge({"sport": "NFL", "market": "Receptions", "chance": 0.62, "price": -110, "use": "🎯 Single only"},
                          h, (59, 138))
    assert losing_tag["verdict"] == "🔴 Skip" and "59–79" in losing_tag["why"]
    thin = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.54, "price": -110}, h)
    assert thin["verdict"] == "🟡 Maybe"


def test_finder_orders_and_lean_rules():
    c = [{"sport": "NBA", "market": "Spread", "pick": "A -3", "game": "g1", "tested": False, "lean_verdict": "losing"},
         {"sport": "NBA", "market": "Points", "pick": "P o20.5", "game": "g2", "chance": 0.63, "price": -105},
         {"sport": "NBA", "market": "Points", "pick": "Q o9.5", "game": "g2", "chance": 0.545, "price": -110}]
    out = CO.finder(c, [])
    assert [r["verdict"] for r in out] == ["🟢 Good bet", "🟡 Maybe", "🔴 Skip"]


def test_realistic_chance_uses_the_real_hit_rate():
    h = CO._history([])
    j = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.63, "price": -110, "use": "🎯 Single only"}, h, (199, 382))
    assert round(j["real_chance"], 3) == round(199 / 382, 3) and j["model_chance"] == 0.63
    assert j["verdict"] == "🔴 Skip"                         # 52% real vs 52.4% needed
    j = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.63, "price": -110, "use": "🎟️ Parlay leg"}, h, (46, 79))
    assert j["verdict"] == "🟢 Good bet"                     # 58% real beats -110


def test_why_numbers_match_the_table_and_signals():
    h = CO._history([])
    j = CO.judge({"sport": "NFL", "market": "Tackles + Assists", "chance": 0.6411, "price": -146,
                  "use": "🎟️ Parlay + Single"}, h, (11, 20))
    assert CO.pct(j["model_chance"]) == "64.1%" and "model 64.1% → edge" in j["why"]
    assert CO.pct(j["need"]) in j["why"] and CO.pts(j["edge"]) in j["why"]
    assert j["signal"] == "🟢 Go"
    r = CO.judge({"sport": "NBA", "market": "Points", "chance": 0.63, "price": -110, "use": "🎯 Single only"}, h, (199, 382))
    assert "realistic chance 52.1%" in r["why"] and "model 63" not in r["why"].split(";")[0][:10]
    assert r["signal"] == "🔴 No"
    assert CO.signal("🟡 Maybe", 0.025, 0) == "🟢 Small stake OK"
    assert CO.signal("🟡 Maybe", 0.025, 1) == "🟡 Tiny stake only"
    assert CO.signal("🟡 Maybe", 0.008, 0) == "🟠 Lean pass"
    assert CO.signal("🟡 Maybe", None, 0) == "🟠 Lean pass"


def test_untagged_props_cannot_be_good_bets():
    h = CO._history([])
    j = CO.judge({"sport": "NBA", "kind": "Prop", "market": "Blocks+Steals", "chance": 0.787, "price": -115, "use": ""}, h)
    assert j["verdict"] == "🟡 Maybe" and "no track record" in j["why"]


def test_ticket_check_flags_a_nov8_style_parlay():
    legs = [{"sport": "NBA", "pick": f"P{i} Pts+Ast Under 15.5", "player": f"P{i}", "market": "Pts+Ast", "side": "Under",
             "line": 15.5, "game": "LAL @ DET", "chance": 0.70, "price": -110, "use": ""} for i in range(5)]
    lim = dict(CO.DEFAULT_LIMITS)
    out = CO.ticket_check(legs, "Parlay", 0, 20, 3400, [], "2026-11-08", lim=lim)
    text = " ".join(m for _, m in out["flags"])
    assert out["grade"] in ("D", "F") and "5 legs" in text and "same game" in text and "$20 on a parlay" in text
    assert "no checked chance" in text and out["hit_chance"] is None


def test_ticket_check_clean_singles_get_an_a():
    legs = [{"sport": "NFL", "pick": "A Rush Attempts Over 15.5", "player": "A", "market": "Rush Attempts", "side": "Over",
             "line": 15.5, "game": "TB @ CHI", "chance": 0.62, "price": -110, "use": "🎟️ Parlay + Single"}]
    out = CO.ticket_check(legs, "Singles", 5, 0, None, [], "2026-11-09", lim=dict(CO.DEFAULT_LIMITS))
    assert out["grade"] == "A", out["flags"]


def test_stop_loss_and_lessons():
    day = "2026-11-08"
    bets = [_b(1, "loss", 0.45, stake=20, odds=3400, market="Parlay", ticket="T", day=day),
            _b(2, "loss", 0.45, stake=5, day=day), _b(3, "loss", None, stake=5, day=day),
            _b(4, "win", 0.62, stake=5, odds=-160, day=day)]
    import betlog as B
    orig = B.is_parlay_header
    B.is_parlay_header = lambda b: b.get("market") == "Parlay"
    try:
        out = CO.ticket_check([], "Singles", 5, 0, None, bets, day, lim=dict(CO.DEFAULT_LIMITS))
        assert any("stop-loss" in m for _, m in out["flags"])
        les = " ".join(CO.lessons(bets, day))
        assert "Parlays were the leak" in les and "no model support" in les and "Heavy prices" in les
    finally:
        B.is_parlay_header = orig
