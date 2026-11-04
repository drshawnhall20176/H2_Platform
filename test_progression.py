from datetime import date
from pathlib import Path

import betlog as B
import model_store as MS
import progression as P


def _bet(i, day, result, stake=10.0, odds=-110, close=None, ticket=None, market="Points", real=True):
    return {"id": i, "slate_date": day, "ts_placed": day, "result": result, "stake": stake, "entry_odds": odds,
            "close_odds": close, "ticket": ticket, "market": market, "is_real_bet": real, "player": "X"}


def test_plan_bankroll_gates_and_months():
    bets = [_bet(1, "2026-11-01", "win", close=-120), _bet(2, "2026-11-01", "loss", close=-105),
            _bet(3, "2026-11-02", "win"), _bet(4, "2026-12-01", "loss"),
            _bet(5, "2026-10-01", "win"),                                   # before the plan start: ignored
            _bet(6, "2026-11-02", "win", real=False)]                       # tracking: ignored
    r = P.plan({"start_bankroll": 1000, "start_date": "2026-11-01", "unit_pct": 0.01}, bets, date(2027, 1, 5))
    win = round(10 * 100 / 110, 2)
    assert r["settled"] == 4 and r["singles"] == 4
    assert abs(r["bankroll"] - (1000 + 2 * win - 20)) < 0.02
    assert abs(r["unit"] - r["bankroll"] * 0.01) < 0.01
    assert [m["month"] for m in r["months"]] == ["2026-11", "2026-12"]
    assert r["stage"] == 1 and not r["prove"][0]["ok"]                     # 4 singles, not 1,000
    assert r["prove"][2]["value"] == 2 and r["prove"][3]["value"] == 0.5    # 2 bets with a close, 1 beat it
    assert r["max_dd"] > 0


def test_parlays_counted_once_and_capped():
    bets = [_bet(1, "2026-11-02", "loss", stake=10, ticket="T1", market=B.PARLAY_MARKET),
            _bet(2, "2026-11-02", "loss", stake=0, ticket="T1"), _bet(3, "2026-11-02", "win", stake=0, ticket="T1"),
            _bet(4, "2026-11-02", "win", stake=40)]
    r = P.plan({"start_date": "2026-11-01"}, bets, date(2026, 11, 3))
    assert r["parlays"] == 1 and r["singles"] == 1
    assert abs(r["discipline"]["parlay_share"] - 0.2) < 1e-9 and not r["discipline"]["parlay_ok"]


def test_goal_math_and_stage_two():
    r = P.plan({"monthly_goal": 4000, "target_roi": 0.03, "bets_per_month": 400, "unit_pct": 0.01}, [], date(2026, 11, 3))
    g = r["goal"]
    assert abs(g["turnover"] - 133333.33) < 1 and abs(g["per_bet"] - 333.33) < 1 and abs(g["bankroll_needed"] - 33333.3) < 5
    many = [_bet(i, "2026-11-%02d" % (1 + i % 28), "win" if i % 100 < 56 else "loss", close=-125 if i < 300 else None)
            for i in range(1000)]
    r2 = P.plan({"start_date": "2026-11-01", "start_bankroll": 5000}, many, date(2026, 12, 3))
    assert all(x["ok"] for x in r2["prove"]) and r2["stage"] == 2


def test_settings_round_trip(tmp_path):
    db = str(tmp_path / "m.db")
    assert MS.save_setting(P.SETTINGS_KEY, {"start_bankroll": 2500}, db_path=db)
    assert MS.get_setting(P.SETTINGS_KEY, db_path=db) == {"start_bankroll": 2500}
    assert MS.get_setting("nope", {"a": 1}, db_path=db) == {"a": 1}


def test_page_renders_and_saves(monkeypatch):
    from streamlit.testing.v1 import AppTest
    got = {}
    monkeypatch.setattr(MS, "get_setting", lambda key, default=None, db_path=None: {})
    monkeypatch.setattr(MS, "save_setting", lambda key, value, db_path=None: got.update({key: value}) or True)
    monkeypatch.setattr(B, "list_bets", lambda *a, **k: [_bet(1, "2026-11-01", "win"), _bet(2, "2026-11-02", "loss")])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "42_Progression_Plan.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Prove" in m.value for m in at.markdown)
    at.number_input[0].set_value(5000.0)
    at.button[0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert got[P.SETTINGS_KEY]["start_bankroll"] == 5000.0


def test_zero_stake_rows_are_not_bets():
    bets = [_bet(1, "2026-11-01", "win", stake=0.0), _bet(2, "2026-11-01", "loss", stake=2.0)]
    r = P.plan({"start_date": "2026-11-01", "start_bankroll": 100}, bets, date(2026, 11, 4))
    assert r["singles"] == 1 and r["settled"] == 1 and r["bankroll"] == 98.0
