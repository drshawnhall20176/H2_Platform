"""Nov 17: Today's best flags picks whose market has moved toward the model's side."""
import todays_best as TB


def _cap(t, side, line, price):
    return {"captured_at": t, "side": side, "line": line, "price": price}


def test_move_of_toward_and_against():
    ser = [_cap("2026-11-17T14:00", "Under", 9.5, -110), _cap("2026-11-17T21:00", "Under", 9.5, -135)]
    m = TB.move_of(ser, "Under")
    assert m["toward"] > TB.MOVE_MIN                       # our side got pricier: market agrees
    ser2 = [_cap("2026-11-17T14:00", "Over", 20.5, -110), _cap("2026-11-17T21:00", "Over", 19.5, -110)]
    assert TB.move_of(ser2, "Over")["toward"] < -TB.MOVE_MIN   # line dropped under an Over: against us
    assert TB.move_of(ser[:1], "Under") is None


def test_market_moves_marks_rows():
    idx = {("Jalen Johnson", "player_rebounds"): [_cap("2026-11-17T14:00", "Under", 9.5, -103),
                                                  _cap("2026-11-17T20:00", "Under", 9.5, -130)]}
    rows = [{"sport": "NBA", "kind": "Prop", "player": "Jalen Johnson", "market": "Rebounds", "side": "Under",
             "line": 9.5},
            {"sport": "NHL", "kind": "Prop", "player": "X", "market": "Saves", "side": "Over", "line": 24.5}]
    TB.market_moves("NBA", "2026-11-17", rows, index=idx)
    assert rows[0]["move"] == "📈 our way" and "Under" in rows[0]["move_why"]
    assert "move" not in rows[1]


def test_spread_move_ncaamb():
    p = {"home": "Duke", "away": "UNC", "open_line": 5.0, "line": 7.0, "model_margin": 9.0}
    m = TB.spread_move(p, "NCAAMB")
    assert m["spread_move"] == "📈 our way" and m["spread_move_why"] == "Duke -5 → -7"
    m2 = TB.spread_move(dict(p, model_margin=4.0), "NCAAMB")       # model likes UNC +7; the line moved away from UNC
    assert m2["spread_move"] == "📉 against" and m2["spread_move_why"] == "UNC +5 → +7"
    assert TB.spread_move(p, "NBA")["spread_move"] == ""
    assert TB.spread_move(dict(p, line=5.5), "NCAAMB")["spread_move"] == ""
