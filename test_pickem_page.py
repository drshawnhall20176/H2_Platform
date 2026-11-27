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
    assert PK.flag(x, "draftkings") is None and not x["blocked"]     # Nov 27: one book's absence says nothing
    y = dict(fut, posting=["draftkings", "fanduel"])
    assert PK.flag(y, "draftkings") is None and not y["blocked"]
    assert PK.flag(dict(y), "draftkings", injury="questionable").startswith("⚠️ Questionable")
    legs = [dict(y, player="A", game="g1", chance=0.6, side="More", app_line=1, market="Points", needed=None),
            dict(x, player="B", game="g2", chance=0.7, side="More", app_line=1, market="Points", needed=None)]
    assert [l["player"] for l in PK.best_entry(legs, 2, 0.55)] == ["B", "A"]      # a hint never blocks
    q = dict(fut, posting=["draftkings"])
    PK.flag(q, "draftkings", injury="questionable")
    assert q["blocked"]


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


def test_a_prop_pulled_since_the_last_snapshot_is_flagged():
    idx = {("Isaiah Joe", "player_rebounds_assists"): [
        {"book": "draftkings", "captured_at": "2026-11-27T15:08:00Z"},
        {"book": "fanduel", "captured_at": "2026-11-27T15:08:00Z"},
        {"book": "fanduel", "captured_at": "2026-11-27T20:08:00Z"}]}
    assert PK.pulled_by(idx, "Isaiah Joe", "player_rebounds_assists", "draftkings")
    assert not PK.pulled_by(idx, "Isaiah Joe", "player_rebounds_assists", "fanduel")
    x = {"kickoff": "2099-01-01T00:00:00Z", "posting": ["draftkings"], "basis": "books"}
    assert PK.flag(x, "draftkings", pulled=True) is None             # superseded by the all-books check



def test_books_dropped_reads_the_whole_market():
    snap = lambda b, t: {"book": b, "captured_at": t}                       # noqa: E731
    early, late = "2026-11-27T20:08:00Z", "2026-11-27T22:08:00Z"
    idx = {("Isaiah Joe", "player_rebounds_assists"): [snap(b, early) for b in ("draftkings", "fanduel", "betmgm",
                                                                              "caesars", "prizepicks")]
           + [snap("caesars", late)],
           ("Someone Else", "player_points"): [snap("fanduel", late)]}
    assert PK.books_dropped(idx, "Isaiah Joe", "player_rebounds_assists") == (3, 4)   # pick'em apps don't count
    x = {"kickoff": "2099-01-01T00:00:00Z", "basis": "books"}
    assert PK.flag(x, "draftkings", dropped=(3, 4)).startswith("⚠️ 3 of 4 books dropped") and x["blocked"]
    y = {"kickoff": "2099-01-01T00:00:00Z", "basis": "books"}
    assert PK.flag(y, None, dropped=(2, 4)).startswith("ℹ️ 2 of 4") and not y["blocked"]
    z = {"kickoff": "2099-01-01T00:00:00Z", "basis": "books"}
    assert PK.flag(z, "draftkings", dropped=(1, 2)) is None                           # too few books to read
    assert PK.flag(dict(z, posting=["fanduel"]), "draftkings") is None                # your book alone says nothing
