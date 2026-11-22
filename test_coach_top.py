"""Nov 22: the coach's top 15 (coach.rule_filters / rules_check / coach_top)."""
import coach as CO


def _j(**kw):
    r = {"sport": "NBA", "market": "Points", "verdict": "🟢 Good bet", "signal": "🟢 Go", "real_chance": 0.57,
         "price": -110, "edge": 0.05, "pick": "x", "time": "7:00 PM", "game": "g", "why": ""}
    r.update(kw)
    return r


F = {"no_against": True, "strong_max_price": -125, "avoid_prices": ["−151 to −200", "Worse than −200"],
     "leak": "TENNIS · Moneyline", "best": "NBA · parlays"}


def test_rules_check():
    assert CO.rules_check(_j(), F) is None
    assert CO.rules_check(_j(real_chance=0.45), F) == "against the model"
    assert "60%+" in CO.rules_check(_j(real_chance=0.64, price=-140), F)
    assert CO.rules_check(_j(real_chance=0.64, price=-120), F) is None
    assert "−151 to −200" in CO.rules_check(_j(real_chance=0.58, price=-160), F)
    assert "leak" in CO.rules_check(_j(sport="TENNIS", market="Moneyline"), F)


def test_coach_top_keeps_rule_abiding_go_bets_and_caps_a_sport():
    js = [_j(pick=f"n{i}", edge=0.03 + i / 100) for i in range(7)]
    js += [_j(sport="NHL", pick="h", edge=0.02, verdict="🟡 Maybe", signal="🟢 Small stake OK")]
    js += [_j(sport="NHL", pick="tiny", verdict="🟡 Maybe", signal="🟡 Tiny stake only")]
    js += [_j(pick="skip", verdict="🔴 Skip"), _j(pick="exp", price=-170)]
    top = CO.coach_top(js, F)
    picks = [r["pick"] for r in top]
    assert sum(p.startswith("n") for p in picks) == 5 and "h" in picks
    assert not {"tiny", "skip", "exp"} & set(picks)
    assert picks[0] == "n6"                                     # good bets first, biggest edge
    assert len(CO.coach_top(js, F, per_sport=None)) == 8
