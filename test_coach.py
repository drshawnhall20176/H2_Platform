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
