"""Game Script (Nov 7): props under each kind of game, every props sport, and tickets that count the script."""
from pathlib import Path

import pytest

import script_effects as SE


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
    assert SE.group("NBA", "Points", 8) is None                        # deep bench: not measured
    assert SE.group("NFL", "Rush Yards") == "rush_yds" and SE.group("NCAAF", "Receptions") == "receptions"
    assert SE.group("NHL", "Goals") == "points" and SE.group("NHL", "Saves") == "saves"
    assert SE.group("NFL", "Anytime TD") is None


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
    untrusted = next(g for g, t in SE.DATA["NBA"]["trust"].items() if t == 0)
    assert set(SE.over_by_script(0.5, untrusted, True, SE.shares(-13.5, "NBA"), "NBA").values()) == {0.5}
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
def test_page_renders_each_sport(monkeypatch, sport, game, teams, market, lines):
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    log = [{"min": 30.0}] * 10
    plays = [{"Model": "player-props", "Player": "A One", "Team": teams[0], "Game": game, "Market": market,
              "Side": "Over", "Line": 5.5, "ModelProb": 0.56, "RealPrice": -112, "Use": "", "_game_log": log,
              "GameDate": "2026-11-08T00:00:00Z"},
             {"Model": "player-props", "Player": "B Two", "Team": teams[1], "Game": game, "Market": market,
              "Side": "Under", "Line": 4.5, "ModelProb": 0.57, "RealPrice": -104, "Use": "", "_game_log": log,
              "GameDate": "2026-11-08T00:00:00Z"}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], []))
    monkeypatch.setattr(SE, "fetch_lines", lambda sp, days: [{"teams": [
        {"names": {SE.norm(teams[0])}, "home": False, "display": teams[0]},
        {"names": {SE.norm(teams[1])}, "home": True, "display": teams[1]}], "fav": 0, "strength": lines}])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = sport
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.metric[1].value == f"{SE.shares(lines, sport)['fav_blowout']:.0%}"
    at.radio(key="gs_script").set_value("fav_blowout").run()
    assert not at.exception


def test_page_explains_uncovered_sport():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = "MLB"
    at.run()
    assert not at.exception and "Game Script covers" in at.info[0].value
