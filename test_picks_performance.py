import picks_performance as PP


def _p(res, price=-110):
    return {"day": "2026-11-23", "sport": "NCAAMB", "pick": "X +2", "result": res, "price": price,
            "units": (PP._dec(price) - 1) if res == "win" else -1.0 if res == "loss" else 0.0, "dec": PP._dec(price)}


def test_summary_and_curve_track_units_against_the_profitable_pace_and_break_even():
    picks = [_p("win"), _p("win"), _p("loss"), _p("push")]
    s = PP.summary(picks)
    assert (s["wins"], s["losses"], s["pushes"]) == (2, 1, 1) and abs(s["units"] - (2 * 100 / 110 - 1)) < 1e-9
    assert abs(s["needed"] - 110 / 210) < 1e-9 and s["pace_units"] == PP.PACE * 4
    c = PP.curve(picks)
    assert [round(x["Profitable pace"], 2) for x in c] == [0.05, 0.1, 0.15, 0.2]
    assert c[-1]["Hit rate"] == 2 / 3 and abs(c[-1]["Needed"] - 110 / 210) < 1e-9
    assert PP.verdict(s).startswith("Only 3 graded")


def test_ledger_picks_reads_graded_ledgers_in_order(monkeypatch):
    import pick_ledger as PL
    store = {"2026-11-23": {"graded_at": "x", "rows": {"a": {"pick": "A +2", "result": "win", "price": -105,
                                                             "first_seen": "1"},
                                                       "b": {"pick": "B -3", "result": None, "first_seen": "2"}}}}
    monkeypatch.setattr(PL, "load", lambda kind, sp, day, get=None: store.get(day, {"rows": {}, "graded_at": None}))
    got = PP.ledger_picks("cand", ("NCAAMB",), "2026-11-23", "2026-11-24")
    assert [g["pick"] for g in got] == ["A +2"] and got[0]["units"] > 0.9


def test_charts_build():
    pts = PP.curve([_p("win"), _p("loss"), _p("win")])
    assert PP.chart(pts, "t") is not None and PP.rate_chart(pts, "t") is not None
