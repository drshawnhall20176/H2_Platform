"""Nov 20: the game-line Money Score (money_score.py)."""
import math
import random

import money_score as MSC


def _rec(**kw):
    p = {"home": "Duke", "away": "Army", "best_home": -150, "best_away": 130, "fair_home": 0.58, "model_p": 0.66,
         "model_margin": 4.0, "home_spread": -3.5, "spread_price": -110, "spread_away_price": -110,
         "line_total": 140.5, "model_total": 143.0, "over_price": -110, "under_price": -110}
    p.update(kw)
    return p


def test_features_orient_home_and_over_and_grade_when_final():
    f = {x["mkt"]: x for x in MSC.features(_rec(final_home=70, final_away=60), "NCAAMB")}
    assert set(f) == {"ML", "SP", "TOT"}
    assert f["ML"]["y"] == 1.0 and f["SP"]["y"] == 1.0 and f["TOT"]["y"] == 0.0        # 70-60: Duke -3.5 covers, 130 under
    assert abs(f["SP"]["pm"] - 0.5) < 1e-9 and f["SP"]["pmod"] > 0.5
    assert all(x["y"] is None for x in MSC.features(_rec(), "NCAAMB"))


def test_fit_starts_at_the_books_and_learns_a_real_tilt():
    rng = random.Random(1)
    rows = []
    for _ in range(3000):                    # truth: home 6 points of chance better than the books say, model is noise
        pm = rng.uniform(0.3, 0.7)
        true = 1 / (1 + math.exp(-(math.log(pm / (1 - pm)) + 0.25)))
        rows.append({"pm": pm, "pmod": rng.uniform(0.2, 0.8), "y": float(rng.random() < true)})
    a, b, c = MSC.fit(rows)
    assert 0.12 < a < 0.38 and 0.75 < b < 1.25 and abs(c) < 0.15
    assert MSC.fit([]) is None


def test_score_label_result_and_money_band(monkeypatch):
    import props_engine as PE
    w = {"NCAAMB|ML": [0.25, 1.0, 0.0, 600], "NCAAMB|SP": [0.0, 1.0, 0.0, 600]}
    s = MSC.score_record(_rec(final_home=70, final_away=60), "NCAAMB", w_by=w)
    best = s["best"]
    assert best["mkt"] == "ML" and best["side"] == "home" and best["score"] > 0.04
    assert MSC.label(_rec(), best) == "Duke moneyline" and MSC.result(best) == "win"
    sp = dict(s["SP"], side="away")
    assert MSC.label(_rec(), sp) == "Army +3.5"
    monkeypatch.setattr(PE, "money_sports", lambda now=None, day=None: ("NCAAMB",))
    assert MSC.is_money("NCAAMB", best) == (MSC.BAND[0] <= best["score"] < MSC.BAND[1])
    assert not MSC.is_money("NBA", best) and not MSC.is_money("NCAAMB", dict(best, score=0.20))
    assert not MSC.is_money("NCAAMB", dict(best, mkt="TOT"))
    assert not MSC.is_money("NCAAMB", dict(best, score=0.08, chance=0.04))           # a long shot
    assert MSC.score_record(_rec(), "NCAAMB", w_by={})["best"] is None                # no fit: no score


def test_a_past_day_without_its_own_fit_is_not_scored_with_a_later_one(monkeypatch):
    import props_engine as PE
    monkeypatch.setattr(PE, "_et_today", lambda: "2026-11-22")
    store = {MSC.KEY: {"coefs": {"NCAAMB|ML": [0, 1, 0, 99]}},
             f"{MSC.KEY}:2026-11-21": {"coefs": {"NCAAMB|ML": [0.1, 1, 0, 90]}}}
    MSC._CACHE.clear()
    assert MSC.coefs("2026-11-21", get=lambda k, d=None: store.get(k, d))["NCAAMB|ML"][0] == 0.1
    assert MSC.coefs("2026-11-19", get=lambda k, d=None: store.get(k, d)) == {}
    assert MSC.coefs("2026-11-22", get=lambda k, d=None: store.get(k, d))["NCAAMB|ML"][3] == 99
    MSC._CACHE.clear()


def test_scoreboard_counts_game_line_money(monkeypatch):
    import money_scoreboard as MSB
    games = {"2026-11-20": [{"sport": "NCAAMB", "money": True, "money_result": "win", "money_price": 120},
                            {"sport": "NCAAMB", "money": True, "money_result": "loss", "money_price": -110},
                            {"sport": "NCAAMB", "money": False, "money_result": "win", "money_price": 300}]}
    b = MSB.scoreboard(load=lambda sp, m: None, today="2026-11-21",
                       test={"from": "2026-11-20", "to": "2026-11-23", "sports": ("NCAAMB",)},
                       games=lambda d: games.get(d, []))
    g = [r for r in b["sports"] if r["sport"] == "games:NCAAMB"][0]
    assert (g["hits"], g["misses"]) == (1, 1) and abs(g["units"] - 0.2) < 1e-9
    assert MSB.table(b)[-1]["Sport"].endswith("game lines")


def test_pick_clv_follows_the_picks_own_side():
    import clv
    row = {"side": "Under", "line": 20.5, "ts": "2026-11-20T23:00", "first_ts": "2026-11-20T15:00", "first_line": 21.5,
           "first_side": "Over", "first_over_price": -110, "first_under_price": -110, "over_price": -110,
           "under_price": -110}
    assert clv.pick_clv(row) == "beat"           # Under 21.5 taken, closed 20.5: the market moved toward the pick
    assert clv.pick_clv(dict(row, line=22.5)) == "lost"
    assert clv.pick_clv(dict(row, side=None)) is None
