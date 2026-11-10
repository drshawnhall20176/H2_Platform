"""AppTest for the Long Shots look-back (a past date): saved model reads + box scores -> rungs with results."""
import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

HERE = Path(__file__).parent


def test_past_date_shows_rungs_and_results(monkeypatch):
    import best_bets_data as BBD
    import model_store as MS
    import nba_engine
    import postgame as PG
    snap = {"sport": "NBA", "slate_date": "2026-11-09", "game": "New Orleans Pelicans @ Golden State Warriors",
            "team": "NO", "opp": "GS", "player": "Jeremiah Fears", "market": "Assists", "projection": 5.98,
            "line": 4.5, "p_model": 0.70, "ts": "1"}
    monkeypatch.setattr(MS, "load_snapshots", lambda sport, dates: [dict(snap)])
    monkeypatch.setattr(MS, "load_odds", lambda *a, **k: None)
    monkeypatch.setattr(PG, "fetch_results", lambda *a, **k: {})
    monkeypatch.setattr(PG, "grade", lambda snaps, res: [dict(s, actual=8) for s in snaps])
    monkeypatch.setattr(nba_engine, "build_slate", lambda d, *a, **k: ([], []))
    monkeypatch.setattr(BBD, "get_odds_api_key", lambda: None)
    at = AppTest.from_file(str(HERE / "views" / "53_Long_Shots.py"), default_timeout=60)
    at.session_state["sport"] = "NBA"
    at.session_state["longshots_date"] = datetime.date(2026, 11, 9)
    at.run()
    assert not at.exception, at.exception
    txt = " ".join(m.value for m in at.markdown)
    assert "rungs hit" in txt
    df = at.dataframe[0].value
    assert "8+ Assists" in set(df["Bet"]) and "✅" in set(df["Hit"])
