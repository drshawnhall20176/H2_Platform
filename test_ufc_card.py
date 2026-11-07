"""Nov 7: the MMA card in one request -- on the UFC Fight Card page and in Today's best."""
import glob
import os
from pathlib import Path

import ufc_engine as E

FEED = [
    {"id": "late", "commence_time": "2026-11-08T03:00:00Z", "home_team": "Main B", "away_team": "Main A",
     "bookmakers": [{"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [{"name": "Main A", "price": -250}, {"name": "Main B", "price": 200}]}]},
                    {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [{"name": "Main A", "price": -230}, {"name": "Main B", "price": 190}]}]}]},
    {"id": "early", "commence_time": "2026-11-07T22:00:00Z", "home_team": "Prelim B", "away_team": "Prelim A",
     "bookmakers": [{"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [{"name": "Prelim A", "price": 120}, {"name": "Prelim B", "price": -140}]}]}]},
    {"id": "nobook", "commence_time": "2026-11-07T23:00:00Z", "home_team": "X", "away_team": "Y", "bookmakers": []},
    {"id": "next", "commence_time": "2026-11-14T23:00:00Z", "home_team": "N1", "away_team": "N2", "bookmakers": []},
]


def test_card_from_odds():
    card = E.card_from_odds(FEED, "2026-11-07")
    assert [b["id"] for b in card] == ["early", "nobook", "late"]              # earliest first; next week's left out
    late = card[-1]
    assert late["books"] == 2 and late["best_a"] == -230 and late["best_b"] == 200 and 0.66 < late["p_a"] < 0.70
    assert card[1]["p_a"] is None and card[1]["books"] == 0                    # on the card, no price yet
    assert card[0]["p_a"] < 0.5                                                # the second-named fighter is favored


def test_today_best_ufc_rows(monkeypatch):
    import todays_best as TB
    monkeypatch.setattr(E, "MAIN_CARD_MIN_BOOKS", 0)
    monkeypatch.setattr(E, "get_card", lambda key, d: E.card_from_odds(FEED, d))
    rows = TB.ufc_rows("2026-11-07", "k")
    assert [r["game"] for r in rows] == ["Prelim A vs Prelim B", "Y vs X", "Main A vs Main B"]
    assert rows[0]["fav"] == "Prelim B" and rows[0]["fav_price"] == -140 and rows[0]["dog_price"] == 120
    assert TB.ufc_rows("2026-11-07", None) == []


def _page():
    return os.path.abspath(glob.glob(str(Path(__file__).parent / "views" / "23_*UFC*.py"))[0])


def test_fight_card_page_shows_the_card(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import datetime as dt
    monkeypatch.setenv("ODDS_API_KEY", "k")
    monkeypatch.setattr(E, "get_ufc_events", lambda key, d=None: [e for e in FEED if E._eastern_date_str(e["commence_time"]) == d])
    monkeypatch.setattr(E, "get_card", lambda key, d=None: E.card_from_odds(FEED, d))
    monkeypatch.setattr(E, "get_event_odds", lambda *a, **k: {})
    monkeypatch.setattr(E, "MAIN_CARD_MIN_BOOKS", 0)
    at = AppTest.from_file(_page(), default_timeout=60)
    at.session_state["sport"] = "UFC"
    at.run()
    at.date_input[0].set_value(dt.date(2026, 11, 7)).run()
    overview = next(d.value for d in at.dataframe if "Bout" in d.value.columns)
    assert list(overview["Bout"]) == ["Prelim A vs Prelim B", "Y vs X", "Main A vs Main B"]


def test_empty_date_offers_upcoming_cards_not_an_old_demo(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import datetime as dt
    monkeypatch.setenv("ODDS_API_KEY", "k")
    monkeypatch.setattr(E, "get_ufc_events", lambda key, d=None: [])
    monkeypatch.setattr(E, "card_dates", lambda key: ["2099-11-14", "2099-11-21"])
    at = AppTest.from_file(_page(), default_timeout=60)
    at.session_state["sport"] = "UFC"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown) + " ".join(i.value for i in at.info)
    assert "Upcoming card dates" in text and "Ankalaev" not in text and "Nov 14" in text


def test_home_fight_card_section(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import todays_best as TB
    monkeypatch.setattr(TB, "collect", lambda d, sp, past=False: {"rows": [], "props": {}})
    monkeypatch.setattr(TB, "winner_rows", lambda d, leagues=None, past=False: [])
    monkeypatch.setattr(TB, "blowout_rows", lambda d: [])
    monkeypatch.setattr(TB, "ufc_rows", lambda d, key: [
        {"sport": "UFC", "time": "10:00 PM", "game": "Main A vs Main B", "fav": "Main A", "dog": "Main B", "chance": 0.68,
         "fav_price": -230, "dog_price": 200, "books": 2, "commence": "2026-11-08T03:00:00Z"},
        {"sport": "UFC", "time": "5:00 PM", "game": "Prelim A vs Prelim B", "fav": "Prelim B", "dog": "Prelim A",
         "chance": 0.55, "fav_price": -140, "dog_price": 120, "books": 1, "commence": "2026-11-07T22:00:00Z"}])
    at = AppTest.from_file(str(Path(__file__).parent / "Home.py"), default_timeout=60)
    at.session_state["sport"] = "UFC"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    df = next(d.value for d in at.dataframe if "Bout" in d.value.columns)
    assert list(df["Bout"]) == ["Prelim A vs Prelim B", "Main A vs Main B"]


def test_main_card_only():
    card = E.card_from_odds(FEED, "2026-11-07")
    assert [b["id"] for b in E.main_card_only(card)] == []                      # no bout here has 5+ books
    big = [dict(b, books=8) if b["id"] == "late" else b for b in card]
    assert [b["id"] for b in E.main_card_only(big)] == ["late"]
