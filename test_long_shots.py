import long_shots as LS


def test_honest_shrinks_the_overconfident_middle_and_lifts_the_far_tail():
    assert round(LS.honest(0.25, "Points"), 4) == round(0.25 * 0.65, 4)
    assert LS.honest(0.03, "Assists") > 0.03
    assert LS.honest(0.25, "Pts+Reb+Ast") == LS.honest(0.25, "PRA")


def test_finder_values_an_alt_rung_like_fears_8_plus():
    reads = {(1, "player_assists"): {"player": "Jeremiah Fears", "market": "Assists", "projection": 6.0,
                                    "values": [5, 7, 6, 8, 4, 6, 7], "dist": "count", "line": 4.5, "game": "NO @ GS"}}
    quotes = [{"market": "player_assists_alternate", "name": "Over", "description": "Jeremiah Fears", "point": 7.5,
               "price": 1500.0},
              {"market": "player_assists_alternate", "name": "Over", "description": "Jeremiah Fears", "point": 5.5,
               "price": 499.0}]
    rows = LS.finder(reads, quotes, lambda s: s.lower(), lambda proj, vals, line, dist, *f: {7.5: 0.22, 5.5: 0.55}[line])
    assert [r["Bet"] for r in rows][0] in ("8+ Assists", "6+ Assists")
    eight = next(r for r in rows if r["Bet"] == "8+ Assists")
    assert eight["Honest chance"] < 0.22 and eight["EV per $1"] > 1.0 and round(eight["Book says"], 4) == round(100 / 1600, 4)
