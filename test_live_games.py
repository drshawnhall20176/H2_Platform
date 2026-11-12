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


def test_tennis_live_read():
    assert abs(LM.tennis(0.65, "atp", 3, [], [])["win_a"] - 0.65) < 0.001       # before a ball: the pre-match chance
    up = LM.tennis(0.5, "atp", 3, [6, 3], [2, 1])                                 # a set and a break up
    assert up["win_a"] > 0.85 and up["games_played"] == 12 and up["total_games"] > 12
    down = LM.tennis(0.65, "atp", 3, [3], [5])
    assert down["win_a"] < 0.65
    done = LM.tennis(0.3, "wta", 3, [6, 6], [2, 4], final=True)
    assert done["win_a"] == 1.0 and done["total_games"] == 18
    assert abs(LM.hold(0.64) - 0.8126) < 0.001


def test_tennis_feed_orientation_and_lines():
    sb = {"events": [{"name": "Nitto ATP Finals", "groupings": [{"grouping": {"displayName": "Men's Singles"},
          "competitions": [{"id": "9", "date": "2026-11-12T13:00Z",
                            "status": {"type": {"state": "in", "shortDetail": "2nd Set"}},
                            "competitors": [
                                {"order": 1, "athlete": {"displayName": "Jannik Sinner"}, "possession": True,
                                 "linescores": [{"value": 6}, {"value": 2}]},
                                {"order": 2, "athlete": {"displayName": "Taylor Fritz"},
                                 "linescores": [{"value": 4}, {"value": 1}]}]}]}]}]}
    m = [x for x in LG.tennis_matches(date(2026, 11, 12), fetch=lambda u, p=None: sb if "atp" in u else {})][0]
    assert m["sets1"] == [6, 2] and m["state"] == "in" and m["best_of"] == 3 and m["server"] == 1
    picks = [{"home": "Taylor Fritz", "away": "Jannik Sinner", "model_p": 0.3}]
    assert abs(LG.tennis_pregame(m, picks) - 0.7) < 1e-9
    ev = {"home_team": "Taylor Fritz", "away_team": "Jannik Sinner", "bookmakers": [{"key": "draftkings", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Taylor Fritz", "price": 700}, {"name": "Jannik Sinner", "price": -1200}]}]}]}
    mk = LG.tennis_market(m, [ev])
    assert mk["p1_price"] == -1200 and mk["p2_price"] == 700
    r = LG.read_tennis(m, 0.7, mk)
    assert r["read"]["win_a"] > 0.9 and {b["market"] for b in r["bets"]} == {"Moneyline"}


def test_football_possession_and_books_pregame():
    sit = {"possession": "12", "possessionText": "KC 35", "downDistanceText": "2nd & 7"}
    ids = {"home": ("12", "KC"), "away": ("7", "DEN")}
    assert LG._possession(sit, ids) == ("home", 65.0)
    assert LG._possession({"possession": "7", "possessionText": "KC 20"}, ids) == ("away", 20.0)
    summ = {"pickcenter": [{"provider": {"name": "Draft Kings"}, "spread": 3.5, "overUnder": 46.5}]}
    pre = LG.espn_pregame("NFL", "1", fetch=lambda u, p=None: summ)
    assert pre["model_margin"] == -3.5 and pre["model_total"] == 46.5 and pre["source"] == "books"
    near = LM.project("NFL", -3.5, 46.5, 17, 20, 4, 1.5, possession="home", yards_to_go=8)
    far = LM.project("NFL", -3.5, 46.5, 17, 20, 4, 1.5, possession="away", yards_to_go=80)
    assert near["win_home"] > far["win_home"]


def test_live_props_read_and_lines():
    import live_props as LP
    summ = {"boxscore": {"players": [{"team": {"displayName": "Boston Celtics"}, "statistics": [{
        "labels": ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"],
        "athletes": [{"athlete": {"displayName": "Jaylen Brown"},
                      "stats": ["24", "18", "7-14", "2-5", "2-2", "5", "3", "1", "1", "0", "1", "4", "2", "+6"]}]}]}]}}
    bx = LP.box(summ)
    assert LP.current(bx["jaylen brown"], "Threes Made", "NBA") == 2 and LP.current(bx["jaylen brown"], "PRA", "NBA") == 26
    g = {"league": "NBA", "home_score": 80, "away_score": 70}
    rd = LM.project("NBA", 3, 225, 80, 70, 3, 0)                 # end of the 3rd: a quarter left
    snaps = [{"player": "Jaylen Brown", "market": "Points", "projection": 26.0, "line": 24.5, "proj_opp": 34},
             {"player": "Somebody Else", "market": "Points", "projection": 10.0, "line": 9.5}]
    rows = LP.read_props(g, rd, snaps, summ)
    assert len(rows) == 1 and rows[0]["now"] == 18 and 18 < rows[0]["projected"] < 26
    assert 0 < rows[0]["p_over_pre"] < 1
    data = {"bookmakers": [{"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "description": "Jaylen Brown", "point": 21.5, "price": -150},
        {"name": "Under", "description": "Jaylen Brown", "point": 21.5, "price": 120}]}]}]}
    lines = LP.live_prop_lines("NBA", "ev1", ["Points"], "key", fetch=lambda eid, ks: data)
    assert lines and lines[0]["line"] == 21.5 and lines[0]["over"] == -150
    checked = LP.check_lines(rows, lines, "NBA", rd["share_left"])
    assert {c["bet"].split()[-2] for c in checked} == {"Over", "Under"}


def test_football_box_stats():
    import live_props as LP
    summ = {"boxscore": {"players": [{"team": {"displayName": "Buffalo Bills"}, "statistics": [
        {"name": "passing", "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
         "athletes": [{"athlete": {"displayName": "Josh Allen"}, "stats": ["21/31", "234", "7.5", "1", "1"]}]},
        {"name": "rushing", "labels": ["CAR", "YDS", "AVG", "TD", "LONG"],
         "athletes": [{"athlete": {"displayName": "Josh Allen"}, "stats": ["6", "40", "6.7", "1", "12"]}]}]}]}}
    rec = LP.box(summ)["josh allen"]
    assert LP.current(rec, "Pass Yards", "NFL") == 234 and LP.current(rec, "Pass Completions", "NFL") == 21
    assert LP.current(rec, "Pass Attempts", "NFL") == 31 and LP.current(rec, "Rush + Rec Yards", "NFL") == 40


def test_final_results_show_how_the_model_did():
    m = {"p1": "Jannik Sinner", "p2": "Taylor Fritz", "winner": 2}
    r = LG.tennis_result(m, 0.7)
    assert r["pick"] == "Jannik Sinner" and r["result"] == "❌ Loss" and abs(r["chance"] - 0.7) < 1e-9
    assert LG.tennis_result(m, None)["result"] == "—"
    g = {"league": "NBA", "home": "Boston Celtics", "away": "Toronto Raptors", "home_score": 110.0, "away_score": 100.0}
    gr = LG.game_result(g, {"model_margin": 4.0, "model_total": 225.0})
    assert gr["pick"] == "Boston Celtics" and gr["result"] == "✅ Win" and gr["chance"] > 0.5
    assert LG.record([r, gr, {"result": "—"}]) == "1–1"


def test_live_box_tables():
    import live_props as LP
    summ = {"boxscore": {"players": [{"team": {"displayName": "Boston Celtics"}, "statistics": [{
        "labels": ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"],
        "athletes": [{"athlete": {"displayName": "Jaylen Brown"},
                      "stats": ["24", "18", "7-14", "2-5", "2-2", "5", "3", "1", "1", "0", "1", "4", "2", "+6"]},
                     {"athlete": {"displayName": "Bench Guy"}, "didNotPlay": True, "stats": []}]}]}]}}
    t = LP.box_tables(summ, "NBA")
    assert len(t) == 1 and t[0]["team"] == "Boston Celtics" and t[0]["rows"][0]["PTS"] == "18"
    assert [r["Player"] for r in t[0]["rows"]] == ["Jaylen Brown"]


def test_retired_match_is_void_and_trend_arrows():
    m = {"p1": "Taylor Fritz", "p2": "Ben Shelton", "winner": 1, "void": "retired"}
    r = LG.tennis_result(m, 0.6)
    assert r["result"] == "⚪ Void (retired)" and LG.record([r]) == ""
    assert LG._void_reason({"name": "STATUS_FINAL", "detail": "Retired"}) == "retired"
    assert LG._void_reason({"name": "STATUS_FINAL", "detail": "Final"}) is None
    up, down, flat = LG.trend(0.8, 0.6), LG.trend(0.4, 0.6), LG.trend(0.61, 0.6)
    assert up["arrow"] == "▲" and down["arrow"] == "▼" and flat["arrow"] == "▬" and abs(up["delta"] - 0.2) < 1e-9
