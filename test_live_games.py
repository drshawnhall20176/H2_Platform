"""Nov 12: live in-game reads."""
import math
from datetime import date, datetime, timezone

import live_games as LG
import live_model as LM


def test_clock_math():
    assert LM.elapsed("NBA", 1, 12) == 0 and LM.elapsed("NBA", 3, 6) == 30 and LM.minutes_left("NBA", 3, 6) == 18
    assert LM.minutes_left("NCAAMB", 2, 4) == 4 and LM.elapsed("NCAAMB", 2, 4) == 36
    assert LM.minutes_left("NBA", 5, 2.5) == 2.5 and LM.elapsed("NBA", 5, 2.5) == 50.5


def test_tip_off_matches_the_pregame_projection_and_time_shrinks_doubt():
    start = LM.project("NBA", 6.0, 230.0, 0, 0, 1, 12)
    assert abs(start["margin"] - 6.0) < 1e-9 and abs(start["total"] - 230.0) < 1e-9
    late = LM.project("NBA", 6.0, 230.0, 100, 90, 4, 2)          # home +10 with 2 minutes left
    assert late["win_home"] > 0.97 and late["margin_sd"] < 5
    tied_late = LM.project("NBA", 0.0, 230.0, 100, 100, 4, 0.5)
    assert 0.45 < tied_late["win_home"] < 0.55
    final = LM.project("NBA", 6.0, 230.0, 101, 99, 4, 0, final=True)
    assert final["win_home"] == 1.0 and final["total"] == 200


def test_cover_and_over_chances_are_consistent():
    rd = LM.project("NCAAMB", 4.0, 140.0, 40, 35, 2, 20)         # halftime, home +5
    assert abs(LM.cover_chance(rd, -LM.fair_spread(rd) * -1) - 0.5) < 0.06
    assert LM.cover_chance(rd, -2.5) > LM.cover_chance(rd, -10.5)
    assert abs(LM.cover_chance(rd, -3.5, "home") + LM.cover_chance(rd, -3.5, "away") - 1) < 1e-9
    assert LM.over_chance(rd, rd["total"] - 10) > 0.5 > LM.over_chance(rd, rd["total"] + 10)


def test_hockey_counts_goals_and_overtime():
    rd = LM.project("NHL", 0.3, 6.0, 2, 1, 3, 5)                 # home up 1, 5 minutes left
    assert 0.75 < rd["win_home"] < 0.97 and rd["tie_regulation"] > 0
    assert abs(LM.over_chance(rd, 2.5) - 1.0) < 1e-9             # 3 goals already scored
    assert 0 < LM.over_chance(rd, 3.5) < 1


def test_espn_feed_and_read():
    sb = {"events": [{"id": "1", "date": "2026-11-13T00:00Z", "competitions": [{
        "id": "1", "date": "2026-11-13T00:00Z",
        "status": {"clock": 245.0, "period": 3, "type": {"state": "in", "name": "STATUS_IN_PROGRESS",
                                                          "shortDetail": "4:05 - 3rd"}},
        "competitors": [{"homeAway": "home", "score": "80", "team": {"displayName": "Boston Celtics"}},
                        {"homeAway": "away", "score": "70", "team": {"displayName": "Toronto Raptors"}}]}]}]}
    gs = LG.espn_games("NBA", date(2026, 11, 12), fetch=lambda u, p=None: sb)
    g = gs[0]
    assert g["state"] == "in" and g["period"] == 3 and abs(g["clock_left"] - 245 / 60) < 1e-9
    assert LG.clock_text(g) == "Q3 4:05"
    pre = {"home": "Boston Celtics", "away": "Toronto Raptors", "kickoff": "2026-11-13T00:00:00+00:00",
           "model_margin": 5.0, "model_total": 225.0}
    assert LG.pregame_for(g, [pre]) is pre
    market = {"home_spread": -12.5, "spread_price": -110, "total": 212.5, "over_price": -110, "under_price": -110,
              "best_home": -900, "best_away": 600}
    r = LG.read_game(g, pre, market)
    assert r["read"]["win_home"] > 0.8 and {b["market"] for b in r["bets"]} == {"Spread", "Total", "Moneyline"}
    assert all(b["signal"][0] in "🟢🟡🔴" for b in r["bets"])
    assert LG.read_game(g, None, market) is None


def test_euroleague_live_header():
    now = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
    games = {"data": [{"gameCode": 50, "identifier": "E2026_50", "played": False, "utcDate": "2026-11-12T17:00:00Z",
                       "local": {"club": {"name": "Real Madrid"}, "score": 0},
                       "road": {"club": {"name": "Olympiacos Piraeus"}, "score": 0}}]}
    header = {"Live": True, "Quarter": "3", "RemainingPartialTime": "05:30", "ScoreA": "61", "ScoreB": "55"}
    fetch = lambda u, p=None: header if "Header" in u else games            # noqa: E731
    g = LG.euroleague_games("EUROLEAGUE", date(2026, 11, 12), fetch, now)[0]
    assert g["state"] == "in" and g["period"] == 3 and abs(g["clock_left"] - 5.5) < 1e-9 and g["home_score"] == 61
