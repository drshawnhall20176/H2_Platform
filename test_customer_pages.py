"""Nov 16: the customer's Today page and the single Players page."""
from pathlib import Path

import customer_today as CT
import players_hub as PH
import props_engine as PE

VIEWS = Path(__file__).with_name("views")


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
    at.run()
    assert not at.exception and ran == ["38_Position_Matchups.py"]
    ran.clear()
    at.session_state["players_view_NFL"] = PH.QBS
    at.run()
    assert not at.exception and ran == ["14_QB_Lab.py"]
    ran.clear()
    at = AppTest.from_file("views/58_Players.py", default_timeout=60)
    at.session_state["sport"] = "UFC"
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
    at = AppTest.from_file("Home.py", default_timeout=120).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Today at a glance" in text and "**A Assists Over 5.5**" in text
    assert text.index("Today at a glance") < text.index("Select Sport")
    assert any(m.value == "61%" for m in at.metric)
