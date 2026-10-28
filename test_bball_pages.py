"""
test_bball_pages.py — AppTest coverage for Matchup Lab and Hot Hand Engine on NBA (the engine replaced with a
small fake slate), added after the Oct 28 Mitchell test: every window of Matchup Lab must render (the Season
window crashed on a NaN), and both pages must show the shared form / position matchup / rest numbers.
"""

import datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import nba_engine
import position_data as PD

HERE = Path(__file__).parent


def _log():
    cur = [dict(pts=p, reb=r, ast=a, fg3m=t, min=34, opp="X", date=f"2026-10-2{i}", src="current")
           for i, (p, r, a, t) in enumerate(((21, 0, 2, 2), (22, 1, 10, 3), (18, 2, 5, 3), (11, 0, 11, 1)))]
    prior = [dict(pts=p, reb=r, ast=a, fg3m=t, min=30, opp="Y", date=f"2026-04-0{i + 1}", src="prior")
             for i, (p, r, a, t) in enumerate(((12, 2, 1, 2), (15, 3, 11, 0), (9, 1, 6, 1), (12, 4, 6, 2)))]
    return cur + prior


def _row():
    return {"Player": "Davion Mitchell", "Team": "Miami Heat", "Opp": "Atlanta Hawks",
            "GameLabel": "Miami Heat @ Atlanta Hawks", "AvgMin": 32.0, "PTS": 15.0, "REB": 1.6, "AST": 6.5,
            "FG3M": 1.8, "_pid": 7, "_team_id": 14, "_opp_id": 1, "_game_log": _log(),
            "_game_date": "2026-10-28T23:00Z"}


def _league():
    """Ten guards against ten defenses; defense 1 (Atlanta) gives up little to guards."""
    out = []
    for t in range(10):
        for i in range(3):
            out.append(dict(game=f"{t}-{i}", order=f"2026-10-2{i}", team=100 + t, opp=t + 1, pid=1000 + t,
                            name=f"G{t}", pos="PG", stats=dict(min=30, pts=12 if t == 0 else 20, reb=4, ast=5,
                                                               fg3m=2)))
    out.append(dict(game="m", order="2026-10-25", team=14, opp=9, pid=7, name="Davion Mitchell", pos="PG",
                    stats=dict(min=34, pts=18, reb=1, ast=6, fg3m=2)))
    return out


@pytest.fixture
def fake_nba(monkeypatch):
    monkeypatch.setattr(nba_engine, "build_slate", lambda d, *a, **k: (
        [_row()], [{"label": "Miami Heat @ Atlanta Hawks", "home_id": 1, "away_id": 14, "home_abbr": "ATL",
                    "away_abbr": "MIA", "home_name": "Atlanta Hawks", "away_name": "Miami Heat",
                    "game_date": "2026-10-28T23:00Z"}]))
    monkeypatch.setattr(nba_engine, "get_team_injuries", lambda abbr: [])
    monkeypatch.setattr(nba_engine, "get_player_history_vs_opponent", lambda *a, **k: [])
    monkeypatch.setattr(nba_engine, "get_player_season_games",
                        lambda *a, **k: [dict(g) for g in _log() if g["src"] == "current"])
    monkeypatch.setattr(nba_engine, "get_team_recent_allowed_stats",
                        lambda tid, d, n=10, days_back=45: {"pts": 112.0, "reb": 44.0, "ast": 26.0, "fg3m": 12.0,
                                                           "poss": 100.0})
    monkeypatch.setattr(nba_engine, "get_team_rest_info",
                        lambda tid, d, days_back=10: {"rest_days": 2, "is_back_to_back": False})
    monkeypatch.setattr(PD, "nba_league_props_sample", lambda d: {"cur": _league(), "prior": [], "notes": []})


def _app(path):
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_file(str(HERE / "views" / path), default_timeout=60)
    at.session_state["sport"] = "NBA"
    return at


@pytest.mark.parametrize("window", ["Season", "Last 10 Games", "Last 6 Games", "Last 5 Games"])
def test_matchup_lab_renders_every_window_with_shared_numbers(fake_nba, window):
    at = _app("11_Matchup_Lab.py")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.radio(key="matchup_lab_window").set_value(window).run()
    assert not at.exception, [e.value for e in at.exception]
    table = [d.value for d in at.dataframe if "Form" in getattr(d.value, "columns", [])]
    assert table, "the player-signals table must render"
    t = table[0]
    assert "Position Matchup" in t.columns
    pts = t[t["Market"] == "Points"].iloc[0]
    assert 17.5 < float(pts["Form"]) < 19.0
    if window == "Last 6 Games":
        assert any("incl. 2 from last season" in c for c in t.columns)
    caps = " ".join(c.value for c in at.caption)
    assert "1 day off" in caps


def test_hot_hand_shows_form_position_matchup_and_both_teams_rest(fake_nba):
    at = _app("10_Hot_Hand_Engine.py")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    board = [d.value for d in at.dataframe if "Matchup Score" in getattr(d.value, "columns", [])][0]
    for col in ("Form", "Position Matchup", "Team D Factor", "Opp Rest", "Fatigue"):
        assert col in board.columns, col
    pts = board[board["Market"] == "Points"].iloc[0]
    assert 17.5 < float(pts["Form"]) < 19.0 and pts["Rest"] == "1 day off"
