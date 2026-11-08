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
