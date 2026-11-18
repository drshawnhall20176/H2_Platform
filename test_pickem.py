"""Nov 18: the Pick'em board -- break-evens, the books' chance moved to the app's line, model-only shrink, entries."""
import pickem as PK
import props_engine as PE


def _read(player="A B", mk="player_points", proj=20.0, game="X @ Y"):
    return {"player": player, "market_key": mk, "market": "Points", "projection": proj,
            "values": [18, 22, 25, 15, 20, 21, 19, 24], "dist": "normal", "game": game}


def test_breakeven():
    assert abs(PK.breakeven(3, 2) - 0.5774) < 1e-3 and abs(PK.breakeven(10, 4) - 0.5623) < 1e-3
    assert PK.APPS["prizepicks"]["power"][6] == 37.5


def test_books_chance_moves_with_the_line():
    r = _read()
    same = PK.books_chance_at(r, 19.5, 0.5, 19.5)
    lower = PK.books_chance_at(r, 19.5, 0.5, 17.5)
    higher = PK.books_chance_at(r, 19.5, 0.5, 21.5)
    assert same == 0.5 and lower > 0.6 and higher < 0.4


def test_legs_books_checked_vs_model_only(monkeypatch):
    monkeypatch.setattr(PE, "trust_for", lambda s, m=None: 0.5)
    reads = {(1, "player_points"): _read(), (2, "player_points"): _read("C D", proj=25.0, game="P @ Q")}
    offers = [
        # A B: the app hangs 17.5 while the books sit at 19.5 even money -> More is a real edge
        {"market": "player_points", "player": "A B", "point": 17.5, "over": {}, "under": {},
         "pickem": {"prizepicks": {"over": {"price": None}, "under": {"price": None}}}},
        {"market": "player_points", "player": "A B", "point": 19.5, "over": {"draftkings": -110},
         "under": {"draftkings": -110}},
        # C D: only the app posts him -- model only, shrunk toward a coin flip
        {"market": "player_points", "player": "C D", "point": 20.5, "over": {}, "under": {},
         "pickem": {"prizepicks": {"over": {"price": None}, "under": {"price": None}}}},
    ]
    lg = {x["player"]: x for x in PK.legs(reads, offers, "prizepicks", "NBA")}
    a, c = lg["A B"], lg["C D"]
    assert a["basis"] == "books" and a["side"] == "More" and a["chance"] > 0.6
    assert c["basis"] == "model only" and c["chance"] < 0.56 and c["model_over"] > 0.75
    e = PK.best_entry(list(lg.values()), 2, PK.breakeven(3, 2))
    assert [x["player"] for x in e] == ["A B"]                    # model-only legs never fill an entry


def test_entry_odds():
    entry = [{"player": f"P{i}", "game": f"g{i}", "market": "Points", "side": "More", "chance": 0.6} for i in range(3)]
    r = PK.entry_odds(entry, "prizepicks", sport="NBA")
    assert abs(r["all"] - 0.216) < 0.01 and abs(r["ev"] - (0.216 * 6 - 1)) < 0.06
    f = PK.entry_odds(entry, "prizepicks", flex=True, sport="NBA")
    assert f["table"][3] == 3.0 and abs(sum(f["dist"].values()) - 1) < 1e-9
    assert PK.entry_odds(entry[:1], "prizepicks") is None


def test_whole_number_lines_can_tie():
    vals = [2, 3, 2, 4, 1, 2, 3, 2]
    p_whole = PK.p_more(2.4, vals, "count", 2.0)          # more than 2, a 2 voids the pick
    p_half = PE.prob_over(2.4, vals, 2.5, "count")        # 3 or more
    assert p_whole > p_half                               # the tie is taken out of the losing side
    assert abs(PK.p_more(2.4, vals, "count", 2.5) - p_half) < 1e-12


def test_sides_at_different_lines():
    reads = {(1, "player_points"): _read(proj=20.0)}
    offers = [{"market": "player_points", "player": "A B", "point": 21.5, "over": {}, "under": {},
               "pickem": {"pick6": {"over": {"price": -137, "multiplier": 1.0}}}},
              {"market": "player_points", "player": "A B", "point": 18.5, "over": {}, "under": {},
               "pickem": {"pick6": {"under": {"price": -137, "multiplier": 1.0}}}}]
    lg = PK.legs(reads, offers, "pick6", "NBA")
    assert len(lg) == 1 and lg[0]["side"] in ("More", "Less")
