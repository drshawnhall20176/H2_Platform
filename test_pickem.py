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


def test_priced_apps_judge_each_pick_against_its_own_price(monkeypatch):
    """Nov 18: Dabble / ParlayPlay price each pick -- a pick must beat its own price, and an entry pays the product."""
    monkeypatch.setattr(PE, "trust_for", lambda s, m=None: 0.5)
    assert PK.is_priced("dabble_us_dfs") and not PK.is_priced("prizepicks")
    assert abs(PK.needed(-118) - 118 / 218) < 1e-9 and abs(PK.needed(119) - 100 / 219) < 1e-9
    reads = {(1, "player_points"): _read(), (2, "player_points"): _read("C D", game="P @ Q")}
    offers = [
        {"market": "player_points", "player": "A B", "point": 17.5, "over": {}, "under": {},
         "pickem": {"dabble_us_dfs": {"over": {"price": -118}, "under": {"price": -110}}}},
        {"market": "player_points", "player": "A B", "point": 19.5, "over": {"novig": -105},
         "under": {"novig": -105}},                                  # an exchange is a price source like any book
        {"market": "player_points", "player": "C D", "point": 19.5, "over": {}, "under": {},
         "pickem": {"dabble_us_dfs": {"over": {"price": -400}, "under": {"price": 250}}}},
        {"market": "player_points", "player": "C D", "point": 19.5, "over": {"prophetx": -105},
         "under": {"prophetx": -105}},
    ]
    lg = {x["player"]: x for x in PK.legs(reads, offers, "dabble_us_dfs", "NBA")}
    a, c = lg["A B"], lg["C D"]
    assert a["basis"] == "books" and a["side"] == "More" and a["needed"] > 0.54 and a["chance"] > a["needed"]
    assert c["side"] == "Less" and c["needed"] < 0.3              # +250 Less beats its price; -400 More does not
    e = PK.best_entry(list(lg.values()), 2, 0.5)
    assert all(x["chance"] >= x["needed"] for x in e)
    if len(e) == 2:
        r = PK.entry_odds(e, "dabble_us_dfs", sport="NBA")
        assert r and r["mult"] > 2.0


def test_offers_merge_across_fetches():
    import best_bets_data as BBD
    a = [{"market": "m", "player": "P", "point": 1.5, "over": {"draftkings": -110}, "under": {"draftkings": -110},
          "pickem": {"prizepicks": {"over": {"price": None}}}, "commence_time": "t"}]
    b = [{"market": "m", "player": "P", "point": 1.5, "over": {"novig": -102}, "under": {"novig": -104},
          "pickem": {"dabble_us_dfs": {"over": {"price": -118}}}},
         {"market": "m", "player": "Q", "point": 2.5, "over": {}, "under": {},
          "pickem": {"underdog": {"under": {"price": None}}}}]
    got = {o["player"]: o for o in BBD.merge_offers(a, b)}
    p = got["P"]
    assert p["over"] == {"draftkings": -110, "novig": -102} and set(p["pickem"]) == {"prizepicks", "dabble_us_dfs"}
    assert "Q" in got and a[0]["over"] == {"draftkings": -110}        # inputs untouched
