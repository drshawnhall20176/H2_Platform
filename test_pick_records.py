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
