"""Nov 20: the H2 Discord bot (community_post.py)."""
from datetime import datetime

import community_post as CP

ET = CP.ET


def _rows():
    base = {"kind": "Prop", "price": -110, "book": "draftkings"}
    return [dict(base, sport="NBA", player="A", pick="A Points Over 20.5", time="7:30 PM", chance=0.47, money=True,
                 edge=0.06, lock=False, price=110),
            dict(base, sport="NBA", player="B", pick="B Rebounds Under 9.5", time="7:00 PM", chance=0.66, lock=True),
            dict(base, sport="NHL", player="C", pick="C Shots Over 2.5", time="1:00 PM", chance=0.7, lock=True),  # started
            dict(base, sport="NBA", player="D", pick="D Assists Over 4.5", time="8:00 PM", chance=0.7, lock=True,
                 pickem_only=True),
            dict(base, sport="NBA", player="A", pick="A Rebounds Over 6.5", time="7:30 PM", chance=0.68, lock=True)]


def test_choose_money_first_then_locks_one_per_player_not_started_earliest_first():
    now = ET.localize(datetime(2026, 11, 20, 16, 0))
    got = CP.choose(_rows(), "2026-11-20", now)
    assert [g["pick"] for g in got] == ["B Rebounds Under 9.5", "A Points Over 20.5"]
    assert got[1]["money"] and not got[0]["money"]


def test_picks_wait_for_the_afternoon_on_weekdays_and_late_morning_on_weekends():
    assert not CP.picks_due(ET.localize(datetime(2026, 11, 20, 15, 0)))           # Friday 3 PM
    assert CP.picks_due(ET.localize(datetime(2026, 11, 20, 15, 31)))
    assert CP.picks_due(ET.localize(datetime(2026, 11, 22, 11, 45)))              # Sunday


def test_run_posts_once_and_never_marks_without_a_webhook():
    store, sent = {}, []
    now = ET.localize(datetime(2026, 11, 20, 16, 0))
    collect = lambda d, s, past=False: {"rows": _rows()}
    CP.run("picks", now, get=store.get, save=store.__setitem__, collect=collect, webhook="")
    assert not store                                                              # no webhook: nothing marked
    CP.run("picks", now, get=store.get, save=store.__setitem__, collect=collect, webhook="https://x",
           post=sent.append)
    assert "community:2026-11-20:picks" in store and sent and "Money picks" in sent[0]["content"]
    assert "draftkings" in sent[0]["content"] and "not financial advice" in sent[-1]["content"]
    CP.run("picks", now, get=store.get, save=store.__setitem__, collect=collect, webhook="https://x",
           post=sent.append)
    assert len(sent) == 1                                                         # once a day
    # next morning: results once graded
    res_rows = [dict(r, result="hit") if r["pick"].startswith("A Points") else dict(r, result="miss") for r in _rows()]
    nxt = ET.localize(datetime(2026, 11, 21, 10, 45))
    CP.run("results", nxt, get=store.get, save=store.__setitem__,
           collect=lambda d, s, past=False: {"rows": res_rows}, webhook="https://x", post=sent.append)
    body = sent[-1]["content"]
    assert "✅" in body and "❌" in body and "Money picks: **1–0** · +1.10 units" in body
    assert "community:2026-11-20:results" in store


def test_results_wait_until_most_picks_are_graded():
    posted = [{"sport": "NBA", "pick": f"P{i}", "time": "7:00 PM", "price": -110, "book": "", "chance": 0.6,
               "money": False, "lock": True} for i in range(5)]
    assert CP.results_text("2026-11-20", posted, {("NBA", "P0"): "hit"}) is None
    assert CP.results_text("2026-11-20", posted, {("NBA", f"P{i}"): "hit" for i in range(4)})
