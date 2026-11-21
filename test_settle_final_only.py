"""Nov 21: Bet Log settlement grades only finished games (owner: "your 14-1 record is overstated" -- an Under graded at
halftime counted as a win). NBA, WNBA and college basketball skip any game that isn't final; NHL already did."""
import pytest

import nba_engine
import ncaamb_engine
import wnba_engine


@pytest.mark.parametrize("E", [nba_engine, ncaamb_engine, wnba_engine])
def test_player_results_skip_games_still_in_progress(monkeypatch, E):
    monkeypatch.setattr(E, "get_schedule", lambda d: [{"gameId": "1", "status_state": "post"},
                                                       {"gameId": "2", "status_state": "in"},
                                                       {"gameId": "3", "status_state": "pre"}])
    boxes = {"1": {10: {"pts": 20.0}}, "2": {20: {"pts": 4.0}}, "3": {30: {"pts": 0.0}}}
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: boxes[gid])
    res = E.get_player_results("2026-11-20")
    assert 10 in res and 20 not in res and 30 not in res


@pytest.mark.parametrize("E", [nba_engine, ncaamb_engine, wnba_engine])
def test_games_without_a_status_still_count(monkeypatch, E):
    monkeypatch.setattr(E, "get_schedule", lambda d: [{"gameId": "1"}])
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: {10: {"pts": 20.0}})
    assert 10 in E.get_player_results("2026-11-20")


def test_ncaamb_schedule_carries_the_status(monkeypatch):
    ev = {"id": "9", "date": "2026-11-21T00:00Z", "competitions": [{
        "status": {"type": {"state": "in"}},
        "competitors": [{"homeAway": "home", "team": {"id": "1", "displayName": "A", "abbreviation": "A"}},
                        {"homeAway": "away", "team": {"id": "2", "displayName": "B", "abbreviation": "B"}}]}]}
    monkeypatch.setattr(ncaamb_engine, "_get_json_cached", lambda *a, **k: {"events": [ev]})
    monkeypatch.setattr(ncaamb_engine, "_get_json", lambda *a, **k: {"events": [ev]})
    g = ncaamb_engine.get_schedule("2026-11-20")
    assert g and g[0]["status_state"] == "in"
