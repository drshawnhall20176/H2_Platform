"""
Oct 29: every play says what it's fit for -- 🎟️ Parlay + Single / 🎟️ Parlay leg / 🎯 Single only / ⛔ Pass --
prices follow your books in order (DraftKings, then FanDuel), and DK Pick6 can be the pricing book.
"""

import odds_api as O
import props_engine as PE
import slate_props as SP


def row(**kw):
    base = {"pid": 1, "player": "P", "projection": 22.0, "values": [20, 23, 21, 24, 22], "dist": "normal",
            "line": 17.5, "side": "Over", "lean": "Over", "p_final": 0.68, "p_model": 0.75, "p_market": 0.55,
            "ev": 0.06, "over_price": -110, "under_price": -110, "flags": [], "out": False, "book": {}}
    base.update(kw)
    return base


def test_the_four_tags():
    assert PE.use_tag(row())[0] == PE.USE_BOTH                                             # +23% cushion, 68%, +6%
    assert PE.use_tag(row(ev=0.01, lean="No lean"))[0] == PE.USE_PARLAY                    # safe, small edge
    single = PE.use_tag(row(projection=19.0, p_final=0.6, ev=0.05))                        # +8.6% cushion, real edge
    assert single[0] == PE.USE_SINGLE and "too close" in single[1]
    assert PE.use_tag(row(returning=True))[0] == PE.USE_PASS                               # a warning
    assert PE.use_tag(row(projection=16.0))[0] == PE.USE_PASS                              # other side
    assert PE.use_tag(row(projection=19.0, ev=-0.02, lean="No lean"))[0] == PE.USE_PASS    # thin and no edge
    assert PE.use_tag(row(line=None))[0] == "—"


def test_milestones_need_70_percent_and_pickem_needs_the_break_even():
    r = row(line=None, lean="No lean")
    assert PE.use_tag(r, "Over", 15.0, p=0.88, milestone=True)[0] == PE.USE_PARLAY
    assert PE.use_tag(r, "Over", 20.0, p=0.62, milestone=True)[0] == PE.USE_PASS              # under 70%, thin
    pk = row(book={"pickem": True, "book": "pick6"}, over_price=None, under_price=None, ev=None)
    assert PE.use_tag(pk)[0] == PE.USE_PARLAY                                              # 68% > 57.7% break-even
    assert PE.use_tag(dict(pk, p_final=0.55))[0] == PE.USE_PASS


def test_book_order_and_pick6_lines():
    assert PE.PICKEM_BOOKS == tuple(O.PICKEM_BOOKS)
    assert PE.book_order("priority") == ["draftkings", "fanduel"] and PE.book_order("fanduel") == ["fanduel", "draftkings"]
    assert PE.book_order("pick6") == ["pick6"] and PE.book_order("best") is None
    offers = [{"market": "player_points", "player": "A", "point": 18.5, "over": {"fanduel": -115, "betmgm": -110},
               "under": {"fanduel": -105, "betmgm": -110}},
              {"market": "player_points", "player": "A", "point": 17.5, "over": {}, "under": {},
               "pickem": {"pick6": {"over": {"price": None}, "under": {"price": None}}}}]
    fd = PE.shop(offers, book="priority")
    assert fd["book"] == "fanduel" and fd["missing_book"] and fd["wanted"] == "draftkings" and fd["best_over"] == ("fanduel", -115)
    p6 = PE.shop(offers, book="pick6")
    assert p6["pickem"] and p6["line"] == 17.5 and p6["best_over"] is None and p6["book"] == "pick6"


def test_slate_plays_carry_the_tag_and_skip_players_pick6_does_not_post():
    r = row(market="Points", line_src="book", book={"book": "draftkings", "best_over": ("draftkings", -110)})
    p = SP.play_from_row(r, None)
    assert p["Use"] == PE.USE_BOTH and PE.has_tag(p["Notes"], "use:both") and p["Conviction"] > 1.0
    missing = dict(r, book={"missing_book": True, "wanted": "pick6", "book": None})
    assert SP.play_from_row(missing, None) is None
    pk = dict(r, over_price=None, under_price=None, ev=None,
              book={"pickem": True, "book": "pick6", "best_over": None, "best_under": None})
    pp = SP.play_from_row(pk, None)
    assert pp["Pickem"] and pp["Use"] == PE.USE_PARLAY and pp["Conviction"] > 1.0


def test_logged_props_carry_the_tag_for_the_scorecard():
    plays = PE.plays_for_log([row()], "Points", "A @ B")
    assert PE.note_tags(plays[0]["Notes"]) == ["use:both"]
