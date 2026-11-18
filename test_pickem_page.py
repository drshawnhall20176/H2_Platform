"""Nov 18: the Pick'em Board renders for every app, including Dabble (no payout table -> no entry built)."""
import pytest
from streamlit.testing.v1 import AppTest

import pickem as PK

READS = {(1, "player_points"): {"player": "A B", "market_key": "player_points", "market": "Points",
                                "projection": 20.0, "values": [18, 22, 25, 15, 20, 21, 19, 24], "dist": "normal",
                                "game": "X @ Y"}}


def _offers():
    return [{"market": "player_points", "player": "A B", "point": 17.5, "over": {}, "under": {},
             "commence_time": "2026-11-18T23:00:00Z",
             "pickem": {a: {"over": {"price": -118}, "under": {"price": 119}} for a in PK.APPS}},
            {"market": "player_points", "player": "A B", "point": 19.5, "over": {"draftkings": -110, "novig": -104},
             "under": {"draftkings": -110, "novig": -102}, "commence_time": "2026-11-18T23:00:00Z"}]


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
