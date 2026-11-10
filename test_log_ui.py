import log_ui as LU
import todays_best as TB


def test_picked_keeps_order_and_ignores_bad_rows():
    items = [{"pick": "a"}, {"pick": "b"}, {"pick": "c"}]
    assert [x["pick"] for x in LU.picked(items, [2, 0, 9])] == ["c", "a"]


def test_coach_and_desk_items_make_bet_rows():
    prop = {"sport": "NFL", "pick": "Daiyan Henley Tackles + Assists Under 6.5", "player": "Daiyan Henley",
            "market": "Tackles + Assists", "side": "Under", "line": 6.5, "game": "HOU @ LAC", "chance": 0.63,
            "price": -136, "book": "draftkings", "pid": "x"}
    rows = TB.bet_rows([prop], 4.0, True, "my-coach", "2026-11-08")
    assert rows[0]["player"] == "Daiyan Henley" and rows[0]["side"] == "Under" and rows[0]["line"] == 6.5
    assert rows[0]["entry_odds"] == -136 and rows[0]["model_prob"] == 0.63 and rows[0]["notes"] == "my-coach"
    assert TB.bet_rows([dict(prop, price=None)], 4.0, True, "", "2026-11-08") == []


def test_props_missing_player_or_side_are_not_logged():
    bad = {"sport": "NFL", "pick": "x", "market": "Tackles + Assists", "price": -139, "chance": 0.64}
    assert TB.bet_rows([bad], 2.0, True, "", "2026-11-08") == []


def test_parlay_vs_singles_uses_saved_leg_prices_and_never_nan():
    import betlog as B
    legs = [{"id": 1, "market": "Parlay", "ticket": "T", "stake": 1, "entry_odds": 881, "result": "loss"},
            {"id": 2, "ticket": "T", "player": "A", "market": "Anytime TD", "side": "Over", "line": 0.5,
             "entry_odds": None, "notes": "x,leg_price=150", "result": "win"},
            {"id": 3, "ticket": "T", "player": "B", "market": "Anytime TD", "side": "Over", "line": 0.5,
             "entry_odds": float("nan"), "result": "loss"}]
    orig = B.is_parlay_header
    B.is_parlay_header = lambda b: b.get("market") == "Parlay"
    try:
        cmp = B.compare_parlay_vs_singles(legs, 1.0)
        assert cmp["legs"][0]["pnl"] == 0.75 and cmp["legs"][1]["pnl"] == -0.5
        assert cmp["singles_pnl"] == 0.25
    finally:
        B.is_parlay_header = orig
