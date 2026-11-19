from datetime import date

import money_review as MR
import props_engine as PE


def _rows(n_days, per_day, hit_every, dec=2.0, start=1):
    out = []
    for d in range(n_days):
        for i in range(per_day):
            out.append({"date": f"2026-10-{start + d:02d}", "dec": dec, "hit": (d * per_day + i) % hit_every != 0})
    return out


def test_turns_on_only_with_enough_reads_days_and_both_halves():
    good = _rows(20, 20, 2)                       # 50% at +100: ROI 0 -- not enough
    assert not MR.evaluate("NBA", good, False)["on"]
    win = _rows(20, 20, 3)                        # 67% at +100: +33%
    v = MR.evaluate("NBA", win, False)
    assert v["on"] and v["changed"] and v["n"] == 400
    few_days = _rows(5, 80, 3)                    # 400 reads but 5 nights: not enough game days
    assert not MR.evaluate("NBA", few_days, False)["on"]
    assert MR.evaluate("NFL", _rows(6, 60, 3), False)["on"]     # weekly sport: 6 game days is enough


def test_a_cold_spell_does_not_flip_it_but_a_faded_edge_does():
    v = MR.evaluate("NBA", _rows(10, 20, 3) + _rows(10, 20, 2, start=11), True)   # later half breaks even
    assert v["on"] and not v["changed"]
    lose = _rows(20, 20, 1, dec=1.9)              # every 1st one loses... (hit_every=1 -> all lose)
    v = MR.evaluate("NBA", lose, True)
    assert not v["on"] and v["changed"]


def test_window_is_the_last_max_reads_not_the_last_n_days():
    old_bad = [dict(r, date="2025-12-01") for r in _rows(1, MR.MAX_READS, 1)]
    v = MR.evaluate("NFL", old_bad + _rows(20, 100, 3), False)
    assert v["n"] == MR.MAX_READS and v["first"] >= "2026-10-01"


def test_run_keeps_out_of_season_verdicts_and_writes_notes():
    store = {MR.KEY: {"at": "2026-11-09T10:00:00", "sports": {"NFL": {"on": True, "last": "2026-11-16", "why": "x"}}}}
    graded = {"NBA": [], "NHL": [], "NCAAF": [], "NCAAMB": [],
              "NFL": [{"slate_date": "2026-11-16", "result": "hit", "price": 110, "ev": 0.08, "book": "draftkings",
                       "market": "Receptions"}]}
    rec = MR.run(today=date(2026, 11, 23), grade=lambda sp: graded[sp], get=store.get,
                 save=lambda k, v: store.__setitem__(k, v), write=False)
    assert rec["sports"]["NFL"]["on"] and "out of season" in rec["sports"]["NFL"]["why"]
    assert MR.run(today=date(2026, 11, 24), grade=lambda sp: [], get=lambda k, d=None: rec, write=False) is None


def test_money_sports_follow_the_saved_verdict(monkeypatch):
    import model_store as MS
    PE._MONEY_CACHE.clear()
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: {"sports": {"NBA": {"on": False}, "NFL": {"on": True}}})
    assert PE.money_sports() == ("NFL",)
    assert PE.is_money("NFL", 0.08, market="Receptions") and not PE.is_money("NBA", 0.08, market="Points")
    PE._MONEY_CACHE.clear()
