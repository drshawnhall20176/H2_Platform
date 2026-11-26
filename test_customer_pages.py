"""Nov 16: the customer's Today page and the single Players page."""
from pathlib import Path

import customer_today as CT
import players_hub as PH
import props_engine as PE

VIEWS = Path(__file__).with_name("views")



import pytest as _pytest_today


@_pytest_today.fixture(autouse=True)
def _no_schedule_calls(monkeypatch):
    """Nov 25: Today asks each sport's schedule which sports have games -- never the network in tests."""
    import customer_today as _CT
    monkeypatch.setattr(_CT, "has_games", lambda key, day: False)

def _p(sport, pick, chance, use=PE.USE_SINGLE, time="7:00 PM", lock=False, price=-110, kind="Prop"):
    return {"sport": sport, "kind": kind, "time": time, "pick": pick, "game": "A @ B", "price": price,
            "book": "DraftKings", "chance": chance, "use": use, "lock": lock}


RECS = {"NBA": {"🎯 Single only": (30, 50), "🎟️ Parlay leg": (4, 10)}, "NHL": {"🎯 Single only": (8, 25)}}


def test_standing_words():
    assert CT.standing("ok") == CT.WINNING and CT.standing("new") == CT.NEW and CT.standing(None) == CT.NEW
    assert CT.standing("losing") is None and CT.standing("fade") is None


def test_prop_picks_show_winning_types_hide_losing_and_new_until_asked():
    rows = [_p("NBA", "A Assists Over 5.5", 0.61), _p("NBA", "B Points Over 20.5", 0.70, use=PE.USE_PARLAY),
            _p("NHL", "C Shots Over 2.5", 0.66), _p("NBA", "D game line", 0.9, kind="Game line")]
    got = CT.prop_picks(rows, records_for=RECS.get)
    assert [r["Pick"] for r in got] == ["A Assists Over 5.5"]                      # NHL losing, parlay tag too new
    assert got[0]["Standing"] == CT.WINNING and got[0]["Record (30 days)"].startswith("30–20 (60%")
    assert got[0]["Best price"] == "-110 · DraftKings"
    more = CT.prop_picks(rows, include_new=True, records_for=RECS.get)
    assert [(r["Pick"], r["Standing"]) for r in more] == [("A Assists Over 5.5", CT.WINNING),
                                                          ("B Points Over 20.5", CT.NEW)]
    assert CT.prop_picks(rows, sports=["NHL"], include_new=True, records_for=RECS.get) == []
    assert CT.prop_picks([_p("NBA", "X", 0.6, price=None)], records_for=RECS.get)[0]["Best price"] == "—"


def test_prop_picks_keep_the_strongest_then_list_earliest_games_first():
    import components as C
    rows = [_p("NBA", "late strong", 0.80, time="10:00 PM"), _p("NBA", "early weak", 0.55, time="7:00 PM"),
            _p("NBA", "early strong", 0.75, time="7:00 PM"), _p("NBA", "weakest", 0.51, time="8:00 PM")]
    got = CT.prop_picks(rows, records_for=RECS.get, parse_time=C._kick_dt, top_n=3)
    assert [r["Pick"] for r in got] == ["early strong", "early weak", "late strong"]


def _w(sport, game, best, tested=False, backtest=None, status=None, time="7:00 PM"):
    return {"sport": sport, "game": game, "time": time, "best": best, "best_tested": tested, "best_chance": 0.58,
            "best_price": -105, "bet_market": "Spread", "backtest": backtest, "use": PE.USE_SINGLE, "status": status,
            "_rec": {"sport": sport}}


def test_line_picks_list_only_playable_game_lines():
    rows = [_w("NBA", "A @ B", "B -3.5", tested=True), _w("NBA", "C @ D", "D +2", backtest=0.57),
            _w("NHL", "E @ F", "F -1.5", backtest=0.50), _w("SOCCER", "G v H", "H", backtest=0.60, status="tracking"),
            _w("NBA", "I @ J", None)]
    got = CT.line_picks(rows, records_for=lambda lg: {})
    assert [(r["Game"], r["Basis"]) for r in got] == [("A @ B", "Tested rule"), ("C @ D", "Lean, 55%+ record")]
    assert got[0]["Chance"] == 0.58 and got[0]["Best price"] == "-105"
    assert got[1]["Chance"] is None and got[1]["Best price"] == "—"           # an untested lean claims no chance
    assert CT.line_picks(rows, sports=["NHL"], records_for=lambda lg: {}) == []


def test_summary_counts():
    props = CT.prop_picks([_p("NBA", "A", 0.6), _p("NBA", "B", 0.7, use=PE.USE_PARLAY)], include_new=True,
                          records_for=RECS.get)
    s = CT.summary(props, [{"Sport": "NHL"}])
    assert s == {"picks": 2, "winning": 1, "lines": 1, "sports": ["NBA", "NHL"]}


def test_every_player_view_points_at_a_real_page_and_names_are_unique_per_sport():
    for sport, tools in PH.TOOLS.items():
        names = [n for n, _ in tools]
        assert names and len(names) == len(set(names)), sport
        for name, num in tools:
            assert PH.script_for(num, VIEWS) is not None, (sport, name, num)
            assert name in PH.ABOUT
    assert PH.tools_for("UFC") == [] and PH.script_for("999", VIEWS) is None
    assert PH.script_for("38", VIEWS).name == "38_Position_Matchups.py"


def test_today_page_renders_with_no_data_and_with_picks(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import pick_records as PR
    import todays_best as TB
    import streamlit as st
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception and len(at.info) == 2 and not at.dataframe
    assert any(CT.DISCLAIMER in c.value for c in at.caption)

    st.cache_data.clear()                                       # the page caches the day's rows for 10 minutes
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [_p("NBA", "A Assists Over 5.5", 0.61)], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [_w("NBA", "A @ B", "B -3.5", tested=True)])
    monkeypatch.setattr(PR, "tag_records", lambda sp: RECS.get(sp, {}))
    monkeypatch.setattr(PR, "lean_records", lambda lg, days=30, recs=None: {})
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception and len(at.dataframe) == 2
    assert list(at.dataframe[0].value["Pick"]) == ["A Assists Over 5.5"]
    assert list(at.dataframe[1].value["Pick"]) == ["B -3.5"]


def test_players_page_runs_only_the_chosen_view(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import runpy
    ran = []
    monkeypatch.setattr(runpy, "run_path", lambda path, run_name=None: ran.append(Path(path).name) or {})
    at = AppTest.from_file("views/58_Players.py", default_timeout=60)
    at.session_state["sport"] = "NFL"
    at.session_state["h2_view_pref"] = "Table"                  # Nov 25: Cards is the default; the tools are Table
    at.run()
    assert not at.exception and ran == ["38_Position_Matchups.py"]
    ran.clear()
    at.session_state["players_view_NFL"] = PH.QBS
    at.run()
    assert not at.exception and ran == ["14_QB_Lab.py"]
    ran.clear()
    at = AppTest.from_file("views/58_Players.py", default_timeout=60)
    at.session_state["sport"] = "UFC"
    at.session_state["h2_view_pref"] = "Table"
    at.run()
    assert not at.exception and ran == [] and at.info


def test_top_cards_are_the_strongest_winning_picks_one_per_player():
    # Nov 16: the cards at the top of the owner's Home
    rows = [dict(_p("NBA", "A Assists Over 5.5", 0.61), player="A"), dict(_p("NBA", "A Points Over 20.5", 0.70), player="A"),
            dict(_p("NBA", "B Rebounds Over 8.5", 0.58, lock=True), player="B"),
            dict(_p("NBA", "C Points Over 11.5", 0.90, use=PE.USE_PARLAY), player="C"),      # too new: not a card
            dict(_p("NHL", "D Shots Over 2.5", 0.80), player="D"),                             # losing type: not a card
            dict(_p("NBA", "E line", 0.9, kind="Game line"), player="E")]
    got = CT.top_cards(rows, records_for=RECS.get)
    assert [c["pick"] for c in got] == ["B Rebounds Over 8.5", "A Points Over 20.5"]          # the lock first
    assert got[0]["lock"] and got[1]["chance"] == 0.70 and got[1]["price"] == "-110 · DraftKings"
    assert got[1]["record"].startswith("30–20 (60%") and got[1]["sport"] == "NBA"
    assert len(CT.top_cards([dict(_p("NBA", f"P{i} x", 0.6 + i / 100), player=f"P{i}") for i in range(9)], records_for=RECS.get)) == 4
    assert CT.top_cards([], records_for=RECS.get) == [] and CT.top_cards(None) == []


def test_home_opens_with_today_at_a_glance(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import pick_records as PR
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {
        "rows": [dict(_p("NBA", "A Assists Over 5.5", 0.61), player="A")], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    monkeypatch.setattr(PR, "tag_records", lambda sp: RECS.get(sp, {}))
    at = AppTest.from_file("Today.py", default_timeout=120).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "**A Assists Over 5.5**" in text                     # Nov 17: the glance is the entry page, Today.py
    assert any(m.value == "61%" for m in at.metric)
    assert any(b.label == "Open desk →" for b in at.button)        # Nov 17: one row per sport, each with its desk
    assert any("NBA" in m.value and "playable pick" in m.value for m in at.markdown)


def test_today_sport_row_carries_its_best_money_pick(monkeypatch):
    """Nov 19 (owner, the middle ground): no separate 💰 box -- each sport's row carries its strongest 💰 pick."""
    from streamlit.testing.v1 import AppTest
    import pick_records as PR
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [
        dict(_p("NBA", "A Assists Over 5.5", 0.61), player="A"),
        dict(_p("NBA", "M Points Over 20.5", 0.55, use=PE.USE_PASS, time="11:59 PM"), player="M", money=True, edge=0.09)],
        "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    monkeypatch.setattr(PR, "tag_records", lambda sp: RECS.get(sp, {}))
    at = AppTest.from_file("Today.py", default_timeout=120).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Best money picks" not in text
    assert "**💰 M Points Over 20.5**" in text and "**A Assists Over 5.5**" in text
    assert any("+9% edge" in c.value for c in at.caption)


def test_owner_brief_sits_at_the_top_of_today(monkeypatch):
    """Nov 19 (owner): the morning brief and the afternoon picks note at the top, not the bottom."""
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    import pick_records as PR
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {
        "rows": [dict(_p("NBA", "A Assists Over 5.5", 0.61), player="A")], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    monkeypatch.setattr(PR, "tag_records", lambda sp: RECS.get(sp, {}))
    real = MS.get_setting
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None, **kw: {"text": "title\nOvernight jobs: all ran"}
                        if k.startswith("brief:") and k.endswith(":morning") else real(k, d, **kw))
    at = AppTest.from_file("Today.py", default_timeout=120).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert at.expander[0].label.startswith("☀️ Morning brief")
    src = open("Today.py").read()
    assert src.index("the owner's brief (Nov 19") < src.index("C.kpi_row(") < src.index("for s in _order:")


def test_today_has_one_sport_bar_all_sports_by_default_that_also_sets_the_sidebar(monkeypatch):
    """Nov 25 (owner): the top bar and the bottom 'Explore a sport' were redundant -- one bar, All sports by default,
    one sport at a time (sidebar follows), several at once only when switched on."""
    from streamlit.testing.v1 import AppTest
    import pick_records as PR
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda day, keys, past=False: {"rows": [_p("NBA", "A Assists Over 5.5", 0.61),
                                                                               _p("NHL", "B Shots Over 2.5", 0.6)],
                                                                      "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    monkeypatch.setattr(PR, "tag_records", lambda sp: {"🎯 Single only": (30, 50)})
    monkeypatch.setattr(PR, "lean_records", lambda lg, days=30, recs=None: {})
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception and not at.warning
    assert not [b for b in at.button if (b.key or "").startswith("today_sport_")]   # no bottom sport buttons
    bar = at.button_group(key="today_one")
    assert bar.value == "ALL"
    assert len(at.dataframe[0].value) == 2                                           # all sports' picks
    bar.set_value("NBA").run()
    assert not at.exception and at.session_state["sport"] == "NBA"                   # the sidebar follows
    assert len(at.dataframe[0].value) == 1
    at.toggle(key="today_multi").set_value(True).run()
    assert not at.exception and at.button_group(key="today_sports").value == ["NBA"]   # carried over
    at.button_group(key="today_sports").set_value(["NBA", "NHL"]).run()
    assert not at.exception and at.session_state["sport"] == "NHL" and len(at.dataframe[0].value) == 2
    at.toggle(key="today_multi").set_value(False).run()
    assert not at.exception and at.button_group(key="today_one").value == "ALL"


def test_today_date_selector_and_sports_with_games_only(monkeypatch):
    """Nov 25 (owner): a date selector (back and forward) and sport buttons only for sports with games that day."""
    from streamlit.testing.v1 import AppTest
    import customer_today as CTm
    import pick_records as PR
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    seen = []

    def collect(day, keys, past=False):
        seen.append((day, past))
        return {"rows": [_p("NBA", "A Assists Over 5.5", 0.61)], "props": {}}
    monkeypatch.setattr(TB, "collect", collect)
    monkeypatch.setattr(TB, "winner_rows", lambda day, leagues=None, past=False: [])
    monkeypatch.setattr(PR, "tag_records", lambda sp: {"🎯 Single only": (30, 50)})
    monkeypatch.setattr(PR, "lean_records", lambda lg, days=30, recs=None: {})
    monkeypatch.setattr(CTm, "has_games", lambda key, day: key == "NHL")       # NHL has games; NBA has a pick
    at = AppTest.from_file("views/57_Today.py", default_timeout=60).run()
    assert not at.exception
    opts = at.button_group(key="today_one").options
    keys = [o.content if hasattr(o, "content") else str(o) for o in opts]
    joined = " ".join(keys)
    assert "NBA" in joined and "NHL" in joined and "NFL" not in joined and "MLB" not in joined
    assert seen[-1][1] is False
    at.button(key="today_prev").click().run()                                  # yesterday: graded, past=True
    assert not at.exception and seen[-1][1] is True
    assert any("Yesterday" in m.value for m in at.markdown)
    at.button(key="today_back").click().run()                                  # back to today (cached: no reload)
    import datetime as _d
    assert not at.exception and at.session_state["today_day"] > _d.date.today() - _d.timedelta(days=1)
