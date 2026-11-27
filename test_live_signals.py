"""Nov 27: live edges kept at first sighting and graded at the final (live_signals.py), the Live page's edges panel
and record, and Today's Live-now strip (live_now.py)."""
import json
from datetime import date

import pytest

import live_now as LN
import live_signals as LS
import model_store as MS


def _g(state="in", hs=50, as_=40, gid="g1"):
    return {"league": "NBA", "id": gid, "event_id": "e1", "home": "Home", "away": "Away", "home_score": hs,
            "away_score": as_, "state": state, "period": 3, "clock_left": 6.0, "halftime": False,
            "kickoff": "2026-11-27T00:00:00Z", "detail": ""}


def test_only_green_bets_are_kept_and_only_once():
    saved = {}

    def save(items):
        new = {k: v for k, v in items.items() if k not in saved}
        saved.update(new)
        return len(items)
    bets = [{"bet": "Home -4.5", "market": "Spread", "side": "home", "line": -4.5, "price": -110, "chance": 0.6,
             "edge": 0.146},
            {"bet": "Over 220.5", "market": "Total", "side": "over", "line": 220.5, "price": -110, "chance": 0.52,
             "edge": -0.007}]
    seen = set()
    assert LS.record_new("2026-11-27", _g(), bets, "Q3 6:00", "t1", seen=seen, save=save) == 1
    assert list(saved) == ["2026-11-27|NBA|g1|Home -4.5"]
    assert LS.record_new("2026-11-27", _g(), bets, "Q3 5:00", "t2", seen=seen, save=save) == 0   # seen this session
    first = json.loads(saved["2026-11-27|NBA|g1|Home -4.5"])
    assert first["clock"] == "Q3 6:00" and first["score"] == "40–50" and first["result"] is None


@pytest.mark.parametrize("sig,hs,as_,want", [
    ({"type": "Spread", "side": "home", "line": -4.5}, 100, 95, "win"),
    ({"type": "Spread", "side": "home", "line": -5.5}, 100, 95, "loss"),
    ({"type": "Spread", "side": "away", "line": 5.0}, 100, 95, "push"),
    ({"type": "Total", "side": "over", "line": 190.5}, 100, 95, "win"),
    ({"type": "Total", "side": "under", "line": 190.5}, 100, 95, "loss"),
    ({"type": "Moneyline", "side": "away", "line": None}, 100, 95, "loss"),
])
def test_grading_game_lines(sig, hs, as_, want):
    assert LS.grade(sig, _g("post", hs, as_)) == want


def test_props_grade_from_his_final_number_and_live_games_dont_grade():
    sig = {"type": "Prop", "side": "over", "line": 24.5}
    assert LS.grade(sig, _g("post"), 26) == "win"
    assert LS.grade(sig, _g("post"), 24) == "loss"
    assert LS.grade(sig, _g("in"), 30) is None


def test_grade_pending_and_record():
    rows = [dict(LS.row("2026-11-27", _g(), {"bet": "Home -4.5", "market": "Spread", "side": "home", "line": -4.5,
                                              "price": -110, "chance": 0.6, "edge": 0.15}, "Q3", "t"),
                 key="2026-11-27|NBA|g1|Home -4.5"),
            dict(LS.row("2026-11-27", _g(), {"bet": "Over 200.5", "market": "Total", "side": "over", "line": 200.5,
                                              "price": +120, "chance": 0.5, "edge": 0.1}, "Q3", "t"),
                 key="2026-11-27|NBA|g1|Over 200.5")]
    out = {}
    n = LS.grade_pending(["2026-11-27"], lambda lg, d: [_g("post", 110, 100)], lambda lg, e: {}, save=out.update,
                         rows=rows)
    assert n == 2
    graded = [json.loads(v) for v in out.values()]
    assert {r["bet"]: r["result"] for r in graded} == {"Home -4.5": "win", "Over 200.5": "win"}
    rec = LS.record(graded)
    assert rec["w"] == 2 and rec["n"] == 2 and rec["units"] == pytest.approx(100 / 110 + 1.2)
    assert LS.record_text(rec).startswith("2–0 · +2.1 units")


def test_store_keeps_the_first_sighting(tmp_path):
    db = str(tmp_path / "m.db")
    MS.add_blobs_once(LS.KIND, {"2026-11-27|NBA|g1|x": "first"}, db_path=db)
    MS.add_blobs_once(LS.KIND, {"2026-11-27|NBA|g1|x": "second"}, db_path=db)
    MS.save_blobs(LS.KIND, {"2026-11-20|NBA|g0|y": "old"}, db_path=db)
    got = MS.blobs_since(LS.KIND, "2026-11-25", db_path=db)
    assert got == {"2026-11-27|NBA|g1|x": "first"}


def test_live_now_strip_items():
    games = {"NBA": [_g("in"), _g("pre", gid="g2")], "NHL": [dict(_g("in", 2, 1, "h1"), league="NHL")]}
    got = LN.in_progress(["NBA", "NHL", "MLB"], lambda lg: games.get(lg, []))
    assert sorted(g["id"] for g in got) == ["g1", "h1"]
    items = LN.order([LN.item(got[0], {"model_margin": 3.0, "model_total": 220.0}, 0),
                      LN.item(got[1], None, 2)])
    assert items[0]["league"] == "NHL" and "🔥 2 live edges flagged" in LN.line(items[0])
    assert "live read: Home" in LN.line(items[1])


def test_live_page_shows_edges_panel_and_keeps_the_signal(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import live_games as LG
    st.cache_data.clear()
    g = _g("in", 60, 40)
    monkeypatch.setattr(LG, "games", lambda lg, day: [g])
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [])
    monkeypatch.setattr(LG, "pregame_for", lambda g, picks: {"model_margin": 2.0, "model_total": 200.0, "source": "lab"})
    monkeypatch.setattr(LG, "live_odds", lambda lg, key: [{"id": "o1", "home_team": "Home", "away_team": "Away"}])
    import intl_picks as IP
    monkeypatch.setattr(IP, "market", lambda ev, h, a: {"best_home": -110, "best_away": -110})
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "k")
    kept = {}
    monkeypatch.setattr(MS, "add_blobs_once", lambda kind, items, db_path=None: kept.update(items) or len(items))
    at = AppTest.from_file("views/54_Live_Games.py", default_timeout=120)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert any(m.value.startswith("**🔥 Live edges right now — 1**") for m in at.markdown)
    assert list(kept) == ["%s|NBA|g1|Home to win" % next(iter(kept)).split("|")[0]]
    assert any("How live edges have done" in e.label for e in at.expander)


def test_today_shows_the_live_now_strip(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import todays_best as TB
    import customer_today as CT
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    monkeypatch.setattr(CT, "has_games_many", lambda keys, day, workers=8, saved=None: {k: True for k in keys},
                        raising=False)
    monkeypatch.setattr(LN, "board", lambda lg, day_s: [_g("in")] if lg == "NBA" else [])
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert any(m.value.startswith("**🔴 Live now — 1 game in progress**") for m in at.markdown)
    assert any(b.label == "Live →" for b in at.button)


def test_test_list_stage_labels_and_retired_rules():
    import focus_list as FL
    import rule_scoreboard as RS
    assert RS.row_rule_key({"kind": FL.GAP, "sport": "NCAAMB"}) == "close_gap|NCAAMB"
    assert RS.row_rule_key({"kind": FL.MONEY, "sport": "NBA", "open_as": "game"}) == "money_games|NBA"
    assert RS.row_rule_key({"kind": FL.PAUSED, "sport": "NHL", "what": "🔒 Most probable — off"}) == "lock|NHL"
    assert RS.row_rule_key({"kind": FL.TRACK, "sport": "NFL", "what": "NFL / college football Under rule"}) == \
        "nfl_under_vs_fav|NFL"
    assert RS.row_rule_key({"kind": FL.BET, "sport": "NBA"}) is None
    r = {"rule": "money_props", "stage": "Paper", "next": "Gate 1", "health": "", "m": {"n": 34}, "picks": []}
    assert RS.stage_text(r, "2026-11-27").startswith("📝 Paper · 34 of 100 to Gate 1")
    gone = dict(r, health="⛔ Pause line: losing even at the top of its range")
    assert RS.retired(gone) and RS.stage_text(gone, "2026-11-27") == "⛔ Retired by its record"
    assert not RS.retired(dict(gone, stage="Live test"))          # live rules switch off by market (shutoff.py)
    assert RS.stage_text(None, "2026-11-27") == "—"


def test_matchup_grade_text():
    import role_history as RH
    assert RH.grade_text({"grade": "A", "rank": 2, "of": 32, "label": "WR1s", "stat": "rec_yds"}) == \
        "A · 2nd most of 32 to WR1s"
    assert RH.grade_text(None) == "—"


def test_rules_move_by_their_own_record():
    import rule_scoreboard as RS
    base = {"rule": "close_gap", "key": "close_gap|NCAAMB", "health": "", "ready": False}
    assert RS.next_stage(dict(base, stage="Paper", ready=True)) == ("Live test", "cleared Gate 1")
    assert RS.next_stage(dict(base, stage="Paper", health="⛔ Pause line: x"))[0] == "Retired"
    assert RS.next_stage(dict(base, stage="Retired")) == ("Paper", "its record moved back off the pause line")
    assert RS.next_stage(dict(base, stage="Live test", ready=True)) == ("Proven", "cleared Gate 2")
    assert RS.next_stage(dict(base, stage="Proven", health="⛔ Pause line: y"))[0] == "Paused"
    assert RS.next_stage(dict(base, stage="Paused", ready=True)) == ("Live test", "cleared its return gate")
    assert RS.next_stage(dict(base, stage="Live test")) is None
    rec = {"rules": [dict(base, stage="Paper", ready=True),
                     {"rule": "money_props", "key": "money_props|NBA", "stage": "Paper", "ready": True, "health": ""}]}
    new, moves = RS.advance(rec, {}, "2026-11-27")
    assert [m["key"] for m in moves] == ["close_gap|NCAAMB"]          # 💰 props keep their own weekly switch
    assert new["close_gap|NCAAMB"]["stage"] == "Live test" and new["close_gap|NCAAMB"]["since"] == "2026-11-27"
    assert RS.stage("close_gap", "NCAAMB", "2026-11-28", new) == "Live test"


def test_the_money_pause_lifts_itself(monkeypatch):
    import model_store as MS
    import money_score as MSC
    monkeypatch.setattr(MSC, "PAUSED", {"NCAAMB": "2026-11-22"})
    MSC._STAGE_CACHE.clear()
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None, db_path=None: {})
    assert MSC.paused("NCAAMB", "2026-11-27") and not MSC.paused("NCAAMB", "2026-11-20")
    MSC._STAGE_CACHE.clear()
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None, db_path=None:
                        {"money_games|NCAAMB": {"stage": "Live test", "since": "2026-12-01"}})
    assert MSC.paused("NCAAMB", "2026-11-27") and not MSC.paused("NCAAMB", "2026-12-02")
    MSC._STAGE_CACHE.clear()
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None, db_path=None:
                        {"money_games|NBA": {"stage": "Paused", "since": "2026-12-01"}})
    assert MSC.paused("NBA", "2026-12-03")
    MSC._STAGE_CACHE.clear()


def test_one_sport_choice_for_the_whole_site():
    import streamlit as st
    import sport_scope as SC
    ss = st.session_state
    for k in ("sport", "cc_all", "sport_many", "f"):
        ss.pop(k, None) if hasattr(ss, "pop") else None
    assert SC.current() == SC.ALL                                # a new visit: All sports
    SC.choose("NBA")
    assert SC.current() == "NBA" and ss["sport"] == "NBA"
    SC.seed_multi("f", ["NBA", "NHL"])
    assert ss["f"] == ["NBA"]
    ss["f"] = ["NBA", "NHL"]
    SC.from_multi("f")
    assert SC.current() == SC.MANY and SC.sidebar_value(["NBA", "NHL"], True) == SC.ALL
    assert SC.sidebar_options(["NBA", "NHL"], False) == SC.sidebar_options(["NBA", "NHL"], True)   # one widget everywhere
    assert SC.sidebar_value(["NBA", "NHL"], False) == "NHL"   # a single-sport page shows the last one picked
    ss["f"] = []
    SC.from_multi("f")
    assert SC.current() == SC.ALL
    SC.seed_single("g", ["All", "NBA"], "All")
    assert ss["g"] == "All"
    SC.pick_from_sidebar(SC.ALL, multi=False)                    # All sports on a one-sport page opens Today
    assert ss["_goto_page"] == "today" and SC.current() == SC.ALL


def test_player_card_header_shows_the_coach_grade():
    import player_card as PC
    p = {"Player": "Chance Mallory", "Market": "Pts+Reb+Ast", "Side": "Under", "Line": 24.5, "RealPrice": -110,
         "ModelProb": 0.55, "_earned": 0.50, "Game": "Virginia Cavaliers @ Xavier Musketeers", "Use": "No edge"}
    chk = PC.coach_grade(p, "NCAAMB", bets=[], tag_records_for=lambda sp: {})
    assert chk and chk["grade"] in "ABCDFT"
    html = PC.coach_html(chk)
    assert "MY COACH" in html and f">{chk['grade']}<" in html and "$" not in html
    assert PC.coach_html(None) == ""
    assert PC.coach_grade(dict(p, Side=None), "NCAAMB", bets=[], tag_records_for=lambda sp: {}) is None


def test_game_card_can_log_the_spread_and_the_total():
    import game_lines_table as GLT
    full = {"home": "Pittsburgh Steelers", "away": "Denver Broncos", "home_spread": 2.5, "line_total": 37.0,
            "pick": "away", "total_pick": "over", "model_margin": -2.1, "model_total": 43.3, "over_price": -110,
            "under_price": -110, "league": "NFL", "home_spread_price": -110, "away_spread_price": -110}
    w = {"_full": full, "bet_market": "Total", "best": "Over 37", "league": "NFL"}
    sp = GLT.market_item(w, "Spread")
    assert sp and sp["pick"].startswith("Denver Broncos -2.5")
    items = GLT.line_items([w], [(0, "✓ Spread"), (0, "✓ Total")])
    assert [i["pick"].split(" (")[0] for i in items] == [sp["pick"].split(" (")[0], "Over 37"]
    no_flag = GLT.market_item({"_full": dict(full, pick=None)}, "Spread")       # not flagged: still the model's side
    assert no_flag and no_flag["pick"].startswith("Pittsburgh Steelers +2.5")    # Denver by 2.1 < 2.5: home covers
    assert GLT.market_item({"_full": dict(full, pick=None, model_margin=None)}, "Spread") is None


def test_saved_lean_records_round_trip():
    from datetime import datetime, timedelta, timezone
    import pick_records as PR
    d = {"Spread": (10, 18), ("Spread", 2): (4, 6), "Total": (0, 0)}
    store = {}
    now = datetime(2026, 11, 27, 18, tzinfo=timezone.utc)
    orig = PR.lean_records
    try:
        PR.lean_records = lambda lg, *a, **k: d
        assert PR.save_lean_records(["NBA"], save=lambda k, v: store.__setitem__(k, v), now=now) == 1
        assert PR.lean_records_fast("NBA", get=lambda k, dflt=None: store.get(k), now=now + timedelta(hours=1)) == d
        PR.lean_records = lambda lg, *a, **k: {"fresh": (1, 1)}
        assert PR.lean_records_fast("NBA", get=lambda k, dflt=None: store.get(k),
                                    now=now + timedelta(hours=4)) == {"fresh": (1, 1)}   # too old: worked out again
    finally:
        PR.lean_records = orig
