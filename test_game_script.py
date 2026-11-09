"""Game Script (Nov 7): props under each kind of game, every props sport, and tickets that count the script."""
from pathlib import Path

import pytest

import script_effects as SE

PE_PASS = "⛔ Pass"


def test_every_sport_has_sane_data():
    for sp in ("NBA", "NCAAMB", "WNBA", "NFL", "NCAAF", "NHL"):
        d = SE.DATA[sp]
        assert d["close"] < d["blow"] and d["shares"] and d["effects"]
        for g, t in d["trust"].items():
            assert 0 <= t <= 1 and g in d["effects"]
        sh = SE.shares(None, sp)
        assert abs(sum(sh.values()) - 1) < 1e-9


def test_shares_by_spread_and_by_moneyline():
    nba = SE.shares(-13.5, "NBA")
    assert nba["fav_blowout"] > 0.5 and nba["dog_blowout"] < 0.05
    assert SE.shares(13.5, "NBA") == nba                              # either sign
    nhl_even, nhl_big = SE.shares(0.52, "NHL"), SE.shares(0.72, "NHL")
    assert nhl_big["fav_blowout"] > nhl_even["fav_blowout"]
    assert SE.shares(0.28, "NHL") == nhl_big                           # the favorite's chance, either side


def test_groups_follow_the_sport():
    assert SE.group("NBA", "PRA", 30) == "starter:points" and SE.group("NBA", "Rebounds", 18) == "bench:rebounds"
    assert SE.group("NBA", "Points", 8) == "deep:points"                # deep reserves: measured nightly (Nov 7)
    assert SE.group("NBA", "Points", 2) is None                        # under 3 minutes: not measured
    assert SE.group("NFL", "Rush Yards") == "rush_yds" and SE.group("NCAAF", "Receptions") == "receptions"
    assert SE.group("NHL", "Goals") == "points" and SE.group("NHL", "Saves") == "saves"
    assert SE.group("NFL", "Anytime TD") == "anytime_td" and SE.group("NFL", "Sacks") == "sacks"   # Nov 9: every market grouped


def test_shifts_centered_point_the_right_way_and_respect_trust():
    sh = SE.shares(-14.0, "NCAAMB")
    bench = SE.over_by_script(0.50, "bench:points", True, sh, "NCAAMB")     # favorite's bench
    assert bench["fav_blowout"] > bench["close"]
    assert abs(sum(sh[s] * bench[s] for s in SE.SCRIPTS) - 0.50) < 1e-9
    sh = SE.shares(-12.0, "NFL")
    rb = SE.over_by_script(0.50, "rush_yds", True, sh, "NFL")               # the favorite's back runs out the clock
    assert rb["fav_blowout"] > rb["close"]
    dog_rb = SE.over_by_script(0.50, "rush_yds", False, sh, "NFL")
    assert dog_rb["fav_blowout"] < dog_rb["close"]
    # a group whose effect didn't hold up gets no shift
    assert SE.trust("NFL", "rec_yds") == 0                                   # didn't repeat on held-out games
    assert set(SE.over_by_script(0.5, "rec_yds", True, sh, "NFL").values()) == {0.5}
    assert set(SE.over_by_script(0.5, None, True, sh, "NFL").values()) == {0.5}


def test_ticket_counts_shared_script():
    sh = SE.shares(-14.0, "NCAAMB")
    a = SE.side_chance(SE.over_by_script(0.5, "starter:points", False, sh, "NCAAMB"), "Under")
    b = SE.side_chance(SE.over_by_script(0.5, "bench:points", True, sh, "NCAAMB"), "Over")
    scripted, plain, per = SE.ticket([a, b], sh)
    assert scripted > plain
    assert per["fav_blowout"] > per["close"]


def test_line_parsing_and_team_matching():
    ev = {"competitions": [{"competitors": [
        {"homeAway": "home", "team": {"displayName": "Sacramento Kings", "location": "Sacramento", "name": "Kings", "abbreviation": "SAC"}},
        {"homeAway": "away", "team": {"displayName": "San Antonio Spurs", "location": "San Antonio", "name": "Spurs", "abbreviation": "SA"}}],
        "odds": [{"spread": 13.5, "homeTeamOdds": {"favorite": False}, "awayTeamOdds": {"favorite": True}}]}]}
    g = SE.parse_event(ev, "NBA")
    assert g["strength"] == 13.5 and g["teams"][g["fav"]]["display"] == "San Antonio Spurs"
    s, fav, dog = SE.line_for(["San Antonio Spurs", "Sacramento Kings"], [g])
    assert (s, fav, dog) == (13.5, "San Antonio Spurs", "Sacramento Kings")
    hk = {"competitions": [{"competitors": [
        {"homeAway": "home", "team": {"displayName": "Boston Bruins", "location": "Boston", "name": "Bruins"}},
        {"homeAway": "away", "team": {"displayName": "Utah Mammoth", "location": "Utah", "name": "Mammoth"}}],
        "odds": [{"homeTeamOdds": {"moneyLine": -180}, "awayTeamOdds": {"moneyLine": 150}}]}]}
    h = SE.parse_event(hk, "NHL")
    assert h["teams"][h["fav"]]["display"] == "Boston Bruins" and 0.6 < h["strength"] < 0.65


@pytest.mark.parametrize("sport,game,teams,market,lines", [
    ("NBA", "San Antonio Spurs @ Sacramento Kings", ("San Antonio Spurs", "Sacramento Kings"), "Rebounds", 13.5),
    ("NFL", "Kansas City Chiefs @ Denver Broncos", ("Kansas City Chiefs", "Denver Broncos"), "Rush Yards", 10.5),
    ("NHL", "Utah Mammoth @ Boston Bruins", ("Utah Mammoth", "Boston Bruins"), "Points", 0.70),
])
def test_page_renders_each_sport_live(monkeypatch, sport, game, teams, market, lines):
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    import model_store as MS
    log = [{"min": 30.0}] * 10
    plays = [{"Model": "player-props", "Player": "A One", "Team": teams[0], "Game": game, "Market": market,
              "Side": "Over", "Line": 5.5, "ModelProb": 0.56, "RealPrice": -112, "Use": "", "_game_log": log,
              "Projection": 6.4, "GameDate": "2026-11-08T00:00:00Z"},
             {"Model": "player-props", "Player": "B Two", "Team": teams[1], "Game": game, "Market": market,
              "Side": "Under", "Line": 4.5, "ModelProb": 0.57, "RealPrice": -104, "Use": "", "_game_log": log,
              "Projection": 3.9, "GameDate": "2026-11-08T00:00:00Z"}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], []))
    monkeypatch.setattr(MS, "load_snapshots", lambda *a, **k: [])
    monkeypatch.setattr(SE, "fetch_lines", lambda sp, days: [{"teams": [
        {"names": {SE.norm(teams[0])}, "home": False, "display": teams[0], "score": None},
        {"names": {SE.norm(teams[1])}, "home": True, "display": teams[1], "score": None}], "fav": 0, "strength": lines,
        "final": False}])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = sport
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.metric[1].value == f"{SE.shares(lines, sport)['fav_blowout']:.0%}"
    at.session_state["gs_cond"] = "fav_blowout"
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_page_looks_back_with_snapshots_and_results(monkeypatch):
    """An earlier date: the kickoff snapshots, the final score, the script that happened, each prop graded."""
    import datetime as dt
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    import postgame as PG
    game = "SA @ SAC"
    snaps = [{"sport": "NBA", "slate_date": "2026-11-06", "game": game, "team": "San Antonio Spurs", "opp": "Sacramento Kings",
              "player": "Bench Guy", "player_id": "1", "market": "Rebounds", "line": 4.5, "side": "Under", "chance": 0.52,
              "projection": 4.4, "use_tag": PE_PASS, "price": -110, "over_price": -110, "under_price": -110,
              "lean": None, "gap": None, "flags": "[]", "kickoff": "2026-11-07T03:00:00Z"},
             {"sport": "NBA", "slate_date": "2026-11-06", "game": game, "team": "Sacramento Kings", "opp": "San Antonio Spurs",
              "player": "Kings Starter", "player_id": "2", "market": "Assists", "line": 5.5, "side": "Over", "chance": 0.53,
              "projection": 5.7, "use_tag": PE_PASS, "price": -115, "over_price": -115, "under_price": -105,
              "lean": None, "gap": None, "flags": "[\"blowout risk\"]", "kickoff": "2026-11-07T03:00:00Z"}]
    monkeypatch.setattr(MS, "load_snapshots", lambda sport, dates=None, db_path=None: snaps)
    monkeypatch.setattr(PG, "fetch_results", lambda *a, **k: {})
    monkeypatch.setattr(PG, "grade", lambda s, r: [dict(x, actual=v) for x, v in zip(s, (8.0, 3.0))])
    import sports
    monkeypatch.setattr(sports.get("NBA").engine, "build_slate", lambda d: ([
        {"Player": "Bench Guy", "AvgMin": 20.0}, {"Player": "Kings Starter", "AvgMin": 32.0}], []))
    monkeypatch.setattr(SE, "fetch_lines", lambda sp, days: [{"teams": [
        {"names": {SE.norm("San Antonio Spurs")}, "home": False, "display": "San Antonio Spurs", "score": 128.0},
        {"names": {SE.norm("Sacramento Kings")}, "home": True, "display": "Sacramento Kings", "score": 101.0}],
        "fav": 0, "strength": 13.5, "final": True}])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = "NBA"
    at.session_state["gs_date"] = dt.date(2026, 11, 6)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Favorite blows it open" in at.success[0].value
    at.session_state["gs_cond"] = "fav_blowout"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    df = at.dataframe[0].value
    assert "Result" in df.columns and set(df["Result"]) <= {"✅", "❌", "➖", ""}


def test_script_use_reruns_the_rules():
    import props_engine as PE
    row = {"line": 4.5, "side": "Under", "p_over": 0.48, "projection": 4.4, "over_price": 120, "under_price": -150,
           "lean": None, "gap": None, "flags": ["blowout risk"]}
    flat = SE.script_use(row, 0.48, "NBA")
    assert flat["use"] == PE.USE_PASS
    hot = SE.script_use(row, 0.66, "NBA")                       # the script moves the chance to 66% Over at +120
    assert hot["side"] == "Over" and hot["ev"] > 0.4
    assert hot["use"] in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)       # blowout-risk warning dropped
    news = dict(row, lean="Check news")
    assert SE.script_use(news, 0.66, "NBA")["use"] == PE.USE_PASS          # news warnings stay
    assert SE.script_projection(4.4, 4.5, 0.48, 0.66) > 4.5


def test_page_explains_uncovered_sport():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = "MLB"
    at.run()
    assert not at.exception and "Game Script covers" in at.info[0].value


def test_snapshot_team_ids_match_espn():
    ev = {"competitions": [{"competitors": [
        {"homeAway": "home", "score": "101", "team": {"id": "23", "displayName": "Sacramento Kings", "location": "Sacramento", "name": "Kings"}},
        {"homeAway": "away", "score": "128", "team": {"id": "24", "displayName": "San Antonio Spurs", "location": "San Antonio", "name": "Spurs"}}],
        "status": {"type": {"completed": True}},
        "odds": [{"spread": 13.5, "awayTeamOdds": {"favorite": True}, "homeTeamOdds": {"favorite": False}}]}]}
    g = SE.parse_event(ev, "NBA")
    rows = [{"team": "24", "opp": "23"}, {"team": "23", "opp": "24"}]
    teams = SE.game_teams(rows, "San Antonio Spurs @ Sacramento Kings")
    assert SE.game_for(teams, [g]) is g
    assert SE.team_matches("24", SE.fav_names(g)) and not SE.team_matches("23", SE.fav_names(g))
    assert not SE.team_matches("2", {"24"})
    assert SE.actual_script(g, "NBA") == "fav_blowout"


def test_usage_formula():
    import roster_usage as RU
    log = [{"min": 36.0, "fga": 20.0, "fta": 8.0, "tov": 3.0}] * 5
    team = {"fga": 88.0, "fta": 22.0, "tov": 14.0}
    u = RU.usage(log, team, 240.0)
    assert 30 < u < 33                                          # (20+3.52+3) x 48 / (36 x 111.68) = 31.7%
    assert RU.usage([{"min": 20.0}], team, 240.0) is None       # no attempts in the box: no usage, not a zero
    assert RU.usage(log, {}, 240.0) is None


def test_roster_table_and_filters(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    import model_store as MS
    import roster_usage as RU
    teams = ("San Antonio Spurs", "Sacramento Kings")
    game = f"{teams[0]} @ {teams[1]}"
    plays = [{"Player": "Star One", "Team": teams[0], "Game": game, "Market": "Points", "Side": "Over", "Line": 24.5,
              "ModelProb": 0.55, "RealPrice": -110, "Projection": 26.0, "GameDate": "2026-11-08T00:00:00Z"},
             {"Player": "Big Two", "Team": teams[1], "Game": game, "Market": "Rebounds", "Side": "Under", "Line": 9.5,
              "ModelProb": 0.56, "RealPrice": -110, "Projection": 8.9, "GameDate": "2026-11-08T00:00:00Z"}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], []))
    monkeypatch.setattr(MS, "load_snapshots", lambda *a, **k: [])
    monkeypatch.setattr(SE, "calls", lambda sport: {})
    monkeypatch.setattr(SE, "fetch_lines", lambda sp, days: [{"teams": [
        {"names": {SE.norm(teams[0])}, "home": False, "display": teams[0], "score": None, "id": "24"},
        {"names": {SE.norm(teams[1])}, "home": True, "display": teams[1], "score": None, "id": "23"}],
        "fav": 0, "strength": 13.5, "final": False}])
    monkeypatch.setattr(RU, "game_rows", lambda sport, ts, d, engine=None: [
        {"player": "Star One", "pid": 1, "team": teams[0], "games": 8, "min": 34.0, "usg": 31.0, "pts": 25.0, "reb": 5.0, "ast": 6.0},
        {"player": "Deep Guy", "pid": 2, "team": teams[0], "games": 4, "min": 6.0, "usg": 18.0, "pts": 2.0, "reb": 1.0, "ast": 0.5},
        {"player": "Big Two", "pid": 3, "team": teams[1], "games": 8, "min": 18.0, "usg": 19.0, "pts": 9.0, "reb": 9.0, "ast": 1.0},
        {"player": "Two Way", "pid": 4, "team": teams[1], "games": 0, "min": None, "usg": None, "pts": None, "reb": None, "ast": None}])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    props, roster = at.dataframe[0].value, at.dataframe[1].value
    assert {"Min", "Usage %"} <= set(props.columns) and len(roster) == 4
    assert set(roster["Role"]) == {"starter", "deep", "bench", "did not play"}
    at.session_state["gs_cond"] = "fav_blowout"
    at.run()
    roster = at.dataframe[1].value
    assert "Pts vs avg" in roster.columns
    star = roster[roster["Player"] == "Star One"].iloc[0]
    assert star["Pts vs avg"] > 0                                # the favorite's starter in his team's blowout
    at.multiselect(key="gs_f_market").set_value(["Rebounds"]).run()
    assert list(at.dataframe[0].value["Player"]) == ["Big Two"]
    at.multiselect(key="gs_f_market").set_value([]).run()
    at.multiselect(key="gs_f_group").set_value(["starter"]).run()
    assert list(at.dataframe[0].value["Player"]) == ["Star One"]


def test_minutes_effects_and_projection(monkeypatch):
    import script_data as D
    c = D.CFG["NBA"]
    games = []
    for k in range(30):
        blow = k >= 20                                          # the last 10 games: team A wins by 25
        sa, sb = (130, 105) if blow else (110, 108)
        games.append((f"2025-11-{k + 1:02d}", {"teams": {"A": {"home": True, "score": sa}, "B": {"home": False, "score": sb}},
                      "players": {"s": {"team": "B", "minutes": 26.0 if blow else 34.0},
                                  "b": {"team": "A", "minutes": 24.0 if blow else 16.0}}}))
    m = D.minutes_effects(c, games)
    assert m["starter"]["blow_lose"] < -5 and m["bench"]["blow_win"] > 5
    monkeypatch.setitem(SE.DATA["NBA"], "minutes", {"starter": {"close": 1.0, "mid": 0.5, "blow_win": -3.0, "blow_lose": -7.0},
                                                    "bench": {"close": -1.0, "mid": 0.0, "blow_win": 5.0, "blow_lose": 2.0}})
    sh = SE.shares(-13.5, "NBA")
    dog_star = SE.minutes_by_script("NBA", 34.0, False, sh)
    assert dog_star["fav_blowout"] < 31 < 34 < dog_star["close"]
    assert abs(sum(sh[s] * dog_star[s] for s in SE.SCRIPTS) - 34.0) < 1e-9
    assert SE.minutes_by_script("NBA", 1.0, True, sh) == {}


def test_upper_table_carries_the_whole_roster(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    import model_store as MS
    import roster_usage as RU
    teams = ("Denver Nuggets", "Indiana Pacers")
    game = f"{teams[0]} @ {teams[1]}"
    snaps = [{"sport": "NBA", "slate_date": "x", "game": game, "team": "7", "opp": "11", "player": "Big Man",
              "player_id": "1", "market": "Points", "line": 25.5, "side": "Under", "chance": 0.52, "projection": 25.0,
              "use_tag": "⛔ Pass", "price": -110, "over_price": -110, "under_price": -110, "lean": None, "gap": None,
              "flags": "[]", "kickoff": "2026-11-08T00:00:00Z"}]
    monkeypatch.setattr(MS, "load_snapshots", lambda *a, **k: snaps)
    monkeypatch.setattr(SE, "calls", lambda sport: {})
    monkeypatch.setitem(SE.DATA["NBA"], "minutes", {"starter": {"close": 1.0, "mid": 0.5, "blow_win": -3.0, "blow_lose": -7.0},
                                                    "bench": {"close": -1.0, "mid": 0.0, "blow_win": 5.0, "blow_lose": 2.0},
                                                    "deep": {"close": -1.5, "mid": 0.0, "blow_win": 6.0, "blow_lose": 4.0}})
    monkeypatch.setattr(SE, "fetch_lines", lambda sp, days: [{"teams": [
        {"names": {SE.norm(teams[0]), "7"}, "home": False, "display": teams[0], "score": None, "id": "7"},
        {"names": {SE.norm(teams[1]), "11"}, "home": True, "display": teams[1], "score": None, "id": "11"}],
        "fav": 0, "strength": 7.5, "final": False}])
    monkeypatch.setattr(RU, "game_rows", lambda sport, ts, d, engine=None: [
        {"player": "Big Man", "pid": 1, "team": teams[0], "games": 8, "min": 34.0, "usg": 28.0, "pts": 26.0, "reb": 12.0, "ast": 9.0},
        {"player": "Pacers Sub", "pid": 2, "team": teams[1], "games": 8, "min": 16.0, "usg": 20.0, "pts": 8.0, "reb": 3.0, "ast": 2.0}])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    top = at.dataframe[0].value
    assert set(top["Player"]) == {"Big Man", "Pacers Sub"}
    assert top[top["Player"] == "Big Man"].iloc[0]["Team"] == "Nuggets (fav)"            # not "7"
    at.session_state["gs_cond"] = "dog_blowout"
    at.run()
    top = at.dataframe[0].value
    col = [c for c in top.columns if c.startswith("Min if")][0]
    big, sub = top[top["Player"] == "Big Man"].iloc[0], top[top["Player"] == "Pacers Sub"].iloc[0]
    assert big[col] < 34.0 and sub[col] > 16.0                  # the favorite's starter sits, the winners' bench plays
    assert sub["Market"] == "— no line" and "minutes 16 →" in sub["Why"]
