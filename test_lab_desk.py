"""Nov 21: the Command Center shows UFC, Tennis and International Hoops (owner: "the command Center shows nothing")."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import lab_desk as LD
import sports

PAGE = str(Path(__file__).parent / "views" / "0_#L01f3c6_Command_Center.py")


def _game(**kw):
    r = {"sport": "INTL", "league": "EuroLeague", "time": "2:00 PM", "game": "Real Madrid @ Olympiacos",
         "winner": "Olympiacos", "chance": 0.62, "price": -150, "best": "Olympiacos -3.5", "best_tested": True,
         "best_chance": 0.55, "best_price": -110, "best_value": 0.05, "money": True, "money_pick": "Olympiacos -3.5",
         "money_price": -110, "money_score": 0.05, "_full": {}}
    r.update(kw)
    return r


@pytest.mark.parametrize("key", ["INTL", "TENNIS"])
def test_labs_show_their_games(monkeypatch, key):
    monkeypatch.setattr(LD, "_game_rows", lambda k, d: [_game(sport=key)])
    monkeypatch.setattr(LD, "_record", lambda k: {"settled": 3, "wins": 2, "losses": 1, "beat_close_rate": 60.0})
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = key
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Money · Pick · Winner" in m.value for m in at.markdown)


def test_ufc_shows_the_card(monkeypatch):
    monkeypatch.setattr(LD, "_ufc_card", lambda d: [{"id": "1", "commence": "2026-11-21T15:10:00Z", "a": "A", "b": "B",
                                                     "p_a": 0.57, "best_a": -142, "best_b": 125, "books": 6}])
    monkeypatch.setattr(LD, "_record", lambda k: {"settled": 0})
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["sport"] = "UFC"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.dataframe and "A vs B" in at.dataframe[0].value["Bout"].tolist()


def test_props_sports_are_not_labs():
    assert not LD.is_lab(sports.get("NBA")) and not LD.is_lab(sports.get("MLB"))
    assert LD.is_lab(sports.get("UFC")) and LD.is_lab(sports.get("TENNIS"))
