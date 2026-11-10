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


def test_fit_reproduces_the_saved_main_line_chance():
    import props_engine as PE
    snap = {"market": "Assists", "projection": 5.98, "line": 4.5, "p_model": 0.70}
    f = LS.fit(snap)
    assert abs(PE.count_sf(5.98, f["spread"], 5) - 0.70) < 0.01
    pts = LS.fit({"market": "Points", "projection": 22.0, "line": 19.5, "p_model": 0.65})
    assert abs(LS.rung_raw(pts, 20) - 0.65) < 0.01


def test_lookback_rungs_above_the_line_with_result_and_saved_price():
    s = {"player": "Jeremiah Fears", "market": "Assists", "projection": 5.98, "line": 4.5, "p_model": 0.70,
         "game": "NO @ GS", "actual": 8, "ts": "1"}
    old = dict(s, projection=3.0, ts="0")                       # an earlier snapshot of the same prop is ignored
    q = [{"market": "player_assists_alternate", "name": "Over", "description": "Jeremiah Fears", "point": 7.5,
          "price": 1500}]
    rows = LS.lookback([old, s], q)
    bets = [r["Bet"] for r in rows]
    assert "6+ Assists" in bets and "8+ Assists" in bets and "5+ Assists" not in bets
    eight = next(r for r in rows if r["Bet"] == "8+ Assists")
    assert eight["Hit"] == "✅" and eight["Price"] == 1500 and eight["EV per $1"] > 1 and eight["Fair price"] < 1500
    assert rows[0]["Hit"] == "✅"                               # hits first, longest shots first
    summ = LS.night_summary(rows)
    assert summ["rungs"] == len(rows) and summ["hits"] == 2


def test_lookback_without_a_result_is_pending():
    rows = LS.lookback([{"player": "A", "market": "Points", "projection": 20.0, "line": 18.5, "p_model": 0.6,
                         "game": "X @ Y", "actual": None}])
    assert rows and all(r["Hit"] is None for r in rows) and LS.night_summary(rows)["rungs"] == 0
