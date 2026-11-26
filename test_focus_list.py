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
    assert [r["kind"] for r in rows] == [FL.GAP, FL.BET, FL.MONEY, FL.MONEY, FL.TRACK]
    assert rows[0]["pick"] == "UNC -3"                         # model -4 vs line -3: 1 point apart, model's side
    assert "D SOG Over 1.5" not in [r["pick"] for r in rows]   # info only is never listed
    real = FL.build(PROPS, WINNERS, kinds=FL.REAL, bet_of=_bet_of)
    assert all(r["sport"] != "NHL" for r in real)


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
    assert t["Chance"] == "—" and t["Edge"] == "—"
    assert t["Price"] == "-110*"


def test_log_items_carry_the_kind_and_the_book_price():
    w = dict(WINNERS[0], _rec={"sport": "NCAAMB", "home": "UNC", "away": "Duke", "kickoff": "2026-11-26T17:00:00Z"})
    gap = FL.build([], [w])[0]
    gap.update(book_price=-105, book_line=gap["line"])
    it = FL.log_item(gap, "fanduel")
    assert it["tracking"] and it["price"] == -105 and it["book"] == "fanduel" and it["bet_market"] == "Spread"
    money = FL.build([], [dict(WINNERS[2], _rec={"sport": "NBA", "home": "Knicks", "away": "Heat"},
                               money_market="Spread", money_side="home", money_line=-4.5)])[0]
    it = FL.log_item(money, "draftkings")                      # no book quote: the board's price
    assert it["note"] == "💰" and it["price"] == -108 and not it["tracking"]
    prop = dict(PROPS[0], player="A", market="Points", side="Over", line=20.5, book="fanduel")
    r = FL.build([prop], [], kinds=[FL.MONEY], bet_of=_bet_of)[0]
    r.update(book_price=-102, book_line=19.5)                  # a different line: keep the board's price and book
    it = FL.log_item(r, "draftkings")
    assert it["price"] == -110 and it["book"] == "fanduel" and it["notes_extra"] == "money-pick"


def test_logged_tags_group_with_the_model():
    import betlog as B
    import todays_best as TB
    w = dict(WINNERS[0], _rec={"sport": "NCAAMB", "home": "UNC", "away": "Duke", "kickoff": "2026-11-26T17:00:00Z",
                               "game_id": "g1"})
    it = FL.log_item(FL.build([], [w])[0], "fanduel")
    row = TB.bet_rows([it], 2.7, True, "test-list", "2026-11-26")[0]
    assert "close-gap-test" in row["notes"] and B.model_group(row) == "with" and row["book"] == "draftkings"


def test_paper_kinds_props_and_paused_game_lines():
    reads = [
        {"sport": "NFL", "pick": "R Under 50.5", "side": "Under", "money_band": True, "chance": 0.5, "price": -110},
        {"sport": "NHL", "pick": "L Over 0.5", "lock_rule": True, "lock": False, "price": -200, "chance": 0.7},
        {"sport": "NBA", "pick": "H Over 9.5", "use": "🎯 Single only", "earned": 0.5, "price": -120,
         "_v": GP.BET_TRACK},
    ]
    win = [{"sport": "NCAAMB", "time": "1:00 PM", "game": "A @ B", "money": False, "money_pick": "B -3",
            "money_score": 0.06, "money_chance": 0.55, "money_market": "Spread", "money_price": -110,
            "_full": {"home": "B", "away": "A"}}]
    rows = FL.build(reads, win, kinds=FL.KINDS, bet_of=_bet_of)
    kinds = {r["pick"]: r["kind"] for r in rows}
    assert kinds == {"R Under 50.5": FL.PAUSED, "L Over 0.5": FL.PAUSED, "H Over 9.5": FL.HELD, "B -3": FL.PAUSED}
    assert {t["Bet or paper"] for t in FL.table(rows)} == {"Paper"}


def test_merge_prefers_rows_with_the_paper_flags():
    a = {"sport": "NBA", "pick": "X Over 1.5", "money": True}
    b = {"sport": "NBA", "pick": "X Over 1.5", "money": True, "money_band": True}
    assert FL.merge_props([a], [b]) == [b]


def test_page_shows_baseline_and_selected_book(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    import todays_best as TB
    st.cache_data.clear()
    monkeypatch.setattr(TB, "collect", lambda d, keys, past=False: {"rows": []})
    monkeypatch.setattr(TB, "load_reads", lambda sp, d: [])
    monkeypatch.setattr(TB, "winner_rows", lambda d, leagues=None, past=False: [
        {"sport": "NBA", "time": "11:59 PM", "game": "Heat @ Knicks", "money": True, "money_pick": "Knicks -4.5",
         "money_price": -108, "money_chance": 0.55, "money_score": 0.05}])
    at = AppTest.from_file("views/64_Test_List.py", default_timeout=60).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    cols = list(at.dataframe[0].value.columns)
    assert "DraftKings now" in cols and "DraftKings move" in cols and "Go?" in cols
    at.selectbox(key="tl_book").set_value("fanduel").run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    cols = list(at.dataframe[0].value.columns)
    assert "FanDuel now" in cols and "FanDuel vs DraftKings" in cols
    assert cols.index("Go?") > cols.index("FanDuel needs")
