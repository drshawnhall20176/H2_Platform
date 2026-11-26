"""Nov 26: the owner's test list -- 💰 / 🃏 / 🧪 close-gap picks across every sport, earliest first."""
import focus_list as FL
import game_previews as GP


def _bet_of(r):
    return r.get("_v", GP.BET_INFO)


PROPS = [
    {"kind": "Prop", "sport": "NBA", "pick": "A Points Over 20.5", "time": "7:00 PM", "price": -110, "chance": 0.56,
     "money": True, "game": "X @ Y"},
    {"kind": "Prop", "sport": "NFL", "pick": "B Rec Yds Under 40.5", "time": "1:00 PM", "price": -115, "chance": 0.57,
     "_v": GP.BET_YES, "game": "P @ Q"},
    {"kind": "Prop", "sport": "NHL", "pick": "C SOG Over 2.5", "time": "8:00 PM", "price": -120, "chance": 0.5,
     "_v": GP.BET_TRACK, "game": "M @ N"},
    {"kind": "Prop", "sport": "NHL", "pick": "D SOG Over 1.5", "time": "8:00 PM", "price": -200, "chance": 0.6,
     "game": "M @ N"},
]
WINNERS = [
    {"sport": "NCAAMB", "time": "12:00 PM", "game": "Duke @ UNC", "best": "UNC -3", "use": "",
     "_full": {"home": "UNC", "away": "Duke", "home_spread": -3.0, "model_margin": 4.0}},
    {"sport": "NCAAMB", "time": "2:00 PM", "game": "A @ B", "best": "B -10", "use": "",
     "_full": {"home": "B", "away": "A", "home_spread": -10.0, "model_margin": 3.0}},
    {"sport": "NBA", "time": "7:30 PM", "game": "Heat @ Knicks", "money": True, "money_pick": "Knicks -4.5",
     "money_price": -108, "money_chance": 0.55, "money_score": 0.05},
]


def test_default_kinds_and_time_order():
    rows = FL.build(PROPS, WINNERS, bet_of=_bet_of, parse_time=lambda t: __import__("components")._kick_dt(t))
    assert [r["kind"] for r in rows] == [FL.GAP, FL.BET, FL.MONEY, FL.MONEY]
    assert rows[0]["pick"] == "UNC -3"                         # model -4 vs line -3: 1 point apart, model's side
    assert all(r["sport"] != "NHL" for r in rows)              # other tracking off, info-only never listed


def test_other_tracking_on_request_and_sport_filter():
    rows = FL.build(PROPS, WINNERS, kinds=FL.KINDS, sports=["NHL"], bet_of=_bet_of)
    assert [r["pick"] for r in rows] == ["C SOG Over 2.5"]


def test_close_gap_needs_two_points_or_less():
    assert FL.close_gap({"home": "B", "away": "A", "home_spread": -10.0, "model_margin": 3.0}) is None
    cg = FL.close_gap({"home": "B", "away": "A", "home_spread": 5.0, "model_margin": -6.5})
    assert cg["pick"] == "A -5" and cg["gap"] == 1.5


def test_edge_is_chance_minus_breakeven():
    r = FL.build(PROPS, [], kinds=[FL.BET], bet_of=_bet_of)[0]
    assert abs(r["need"] - 115 / 215) < 1e-9 and abs(r["edge"] - (0.57 - 115 / 215)) < 1e-9
    assert FL.table([r])[0]["Price"] == "-115"


def test_the_page_is_an_office_page():
    import office as OF
    assert OF.is_office_page("64")


def test_page_renders_the_list(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda d, keys, past=False: {"rows": []})
    monkeypatch.setattr(TB, "winner_rows", lambda d, leagues=None, past=False: [
        {"sport": "NBA", "time": "11:59 PM", "game": "Heat @ Knicks", "money": True, "money_pick": "Knicks -4.5",
         "money_price": -108, "money_chance": 0.55, "money_score": 0.05}])
    at = AppTest.from_file("views/64_Test_List.py", default_timeout=60).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert any("Knicks -4.5" in str(df.value.to_dict()) for df in at.dataframe)


def test_blanks_are_blank_and_assumed_prices_are_marked():
    import math
    rows = FL.build([], WINNERS[:1])
    t = FL.table(rows)[0]
    assert math.isnan(t["Chance"]) and math.isnan(t["Edge"])
    assert t["Price"] == "-110*"
