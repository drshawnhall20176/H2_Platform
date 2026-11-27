"""Nov 18: the Pick'em Board renders for every app, including Dabble (no payout table -> no entry built)."""
import pytest
from streamlit.testing.v1 import AppTest

import pickem as PK

READS = {(1, "player_points"): {"player": "A B", "market_key": "player_points", "market": "Points",
                                "projection": 20.0, "values": [18, 22, 25, 15, 20, 21, 19, 24], "dist": "normal",
                                "game": "X @ Y"}}


def _offers():
    return [{"market": "player_points", "player": "A B", "point": 17.5, "over": {}, "under": {},
             "commence_time": "2099-11-18T23:00:00Z",
             "pickem": {a: {"over": {"price": -118}, "under": {"price": 119}} for a in PK.APPS}},
            {"market": "player_points", "player": "A B", "point": 19.5, "over": {"draftkings": -110, "novig": -104},
             "under": {"draftkings": -110, "novig": -102}, "commence_time": "2099-11-18T23:00:00Z"}]


@pytest.mark.parametrize("app", list(PK.APPS))
def test_page_renders_for_every_app(app, monkeypatch):
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "K")
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers())
    monkeypatch.setattr(BBD, "fetch_pickem_extra_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "load_slate_reads", lambda *a, **k: READS)
    at = AppTest.from_file("views/61_Pickem_Board.py", default_timeout=60)
    at.session_state["sport"] = "NBA"
    at.session_state["pk_app"] = app
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert ("No entry built" in text) == (PK.APPS[app].get("power") is None)


def test_empty_board_says_the_feed_lacks_the_app(monkeypatch):
    """Nov 18: Pick6 had college lines on its site but none in the odds feed -- the page must say it's the feed."""
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "K")
    off = [{"market": "player_points", "player": "A B", "point": 17.5, "over": {}, "under": {},
            "pickem": {"prizepicks": {"over": {"price": None}}}}]
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: off)
    monkeypatch.setattr(BBD, "fetch_pickem_extra_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "load_slate_reads", lambda *a, **k: {})
    at = AppTest.from_file("views/61_Pickem_Board.py", default_timeout=60)
    at.session_state["sport"] = "NCAAMB"
    at.session_state["cc_all"] = False                          # Nov 27: one sport (the board spans all by default)
    at.session_state["pk_app"] = "pick6"
    at.run()
    assert not at.exception
    msg = " ".join(i.value for i in at.info)
    assert "isn't carrying any DK Pick6" in msg and "PrizePicks (1)" in msg



def test_started_games_hidden_and_flags_block_the_entry(monkeypatch):
    """Nov 27 (owner): a game that has started, a player listed questionable, or a prop his sportsbook pulled never
    goes in the entry; started games are hidden by default."""
    from datetime import datetime, timezone
    past = {"kickoff": "2020-01-01T00:00:00Z", "posting": ["draftkings"], "basis": "books"}
    assert PK.flag(dict(past), "draftkings") == "🔒 Started — locked"
    fut = {"kickoff": "2099-01-01T00:00:00Z", "posting": ["fanduel", "betmgm", "novig"], "basis": "books"}
    x = dict(fut)
    assert PK.flag(x, "draftkings").startswith("⚠️ Not at DraftKings") and x["blocked"]
    y = dict(fut, posting=["draftkings", "fanduel"])
    assert PK.flag(y, "draftkings") is None and not y["blocked"]
    assert PK.flag(dict(y), "draftkings", injury="questionable").startswith("⚠️ Questionable")
    legs = [dict(y, player="A", game="g1", chance=0.6, side="More", app_line=1, market="Points", needed=None),
            dict(x, player="B", game="g2", chance=0.7, side="More", app_line=1, market="Points", needed=None)]
    assert [l["player"] for l in PK.best_entry(legs, 2, 0.55)] == ["A"]


def test_board_spans_sports_and_slates_by_start(monkeypatch):
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "K")
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers())
    monkeypatch.setattr(BBD, "fetch_pickem_extra_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "load_slate_reads", lambda *a, **k: READS)
    at = AppTest.from_file("views/61_Pickem_Board.py", default_timeout=60)
    at.session_state["pk_app"] = "prizepicks"
    at.run()
    assert not at.exception, at.exception
    assert at.button_group(key="pk_sport").value == "__all__"
    starts = at.selectbox(key="pk_starts")
    assert starts.options[0] == "All upcoming" and len(starts.options) == 2


def test_flex_switch_changes_the_payout(monkeypatch):
    """Nov 27 (owner): the Flex switch must change what the board prices."""
    import best_bets_data as BBD
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: "K")
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda *a, **k: _offers())
    monkeypatch.setattr(BBD, "fetch_pickem_extra_offers", lambda *a, **k: [])
    monkeypatch.setattr(BBD, "load_slate_reads", lambda *a, **k: READS)
    at = AppTest.from_file("views/61_Pickem_Board.py", default_timeout=60)
    at.session_state["pk_app"] = "prizepicks"
    at.session_state["pk_n"] = 6
    at.run()
    assert any("6-pick Power" in c.value for c in at.caption)
    at.toggle(key="pk_flex").set_value(True).run()
    assert not at.exception
    assert any("6-pick Flex" in c.value and "6 of 6: 25x" in c.value for c in at.caption)
