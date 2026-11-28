"""Oct 31: auto-settling NBA / NFL / NCAAF Bet Log props from ESPN box scores (prop_settlement.py)."""
import json
from pathlib import Path

import prop_settlement as PS

SUMMARY = json.loads((Path(__file__).parent / "test_fixtures" / "espn_ncaaf_summary_401856844_trimmed.json")
                     .read_text())
BOARD = {"events": [{"id": "401856844", "competitions": [{"competitors": [
    {"team": {"abbreviation": "UCF", "displayName": "UCF Knights", "location": "UCF", "id": "2116"}},
    {"team": {"abbreviation": "BAY", "displayName": "Baylor Bears", "location": "Baylor", "id": "239"}}]}]}]}


def fetch(url, params=None):
    return BOARD if url.endswith("scoreboard") else SUMMARY


def bet(i, player, market, side, line, game="Baylor @ UCF", **kw):
    return dict({"id": i, "player": player, "market": market, "side": side, "line": line, "game": game,
                 "slate_date": "2026-10-30", "result": None}, **kw)


def test_props_settle_from_the_box_score_and_nothing_is_guessed():
    open_bets = [bet(1, "D.J. Lagway", "Pass Yards", "Over", 256.5),          # 319 -> win ("D.J." == "DJ")
                 bet(2, "Duke Watson", "Rush Attempts", "Under", 14.5),       # 7 -> win
                 bet(3, "Caden Knighten", "Rush Attempts", "Under", 6.5),     # 7 -> loss
                 bet(4, "Gavin Freeman", "Receiving Yards", "Over", 114),     # exactly 114 -> push
                 bet(5, "Nobody Here", "Receptions", "Over", 2.5),            # not in the box -> a person
                 bet(6, "Duke Watson", "Made Up Market", "Over", 1.5),        # can't grade -> a person
                 bet(7, "Duke Watson", "Rush Attempts", "Over", 5.5, game="no teams here"),
                 bet(8, None, "Parlay", "2-leg parlay", None, ticket="T"),    # headers settle from legs
                 bet(9, "Duke Watson", "Rush Attempts", "Over", 5.5, result="win")]   # already settled
    plan = PS.build_plan(open_bets, "NCAAF", fetch=fetch)
    got = {p["bet_id"]: (p["new_result"], p["actual"]) for p in plan["proposed"]}
    assert got == {1: ("win", 319), 2: ("win", 7), 3: ("loss", 7), 4: ("push", 114)}
    assert {u["bet_id"] for u in plan["unresolved"]} == {5, 6, 7}
    assert PS.build_plan(open_bets, "MLB", fetch=fetch) == {"proposed": [], "still_pending": [], "unresolved": []}


def test_an_unfinished_game_stays_pending():
    live = json.loads(json.dumps(SUMMARY))
    live["header"]["competitions"][0]["status"]["type"]["completed"] = False
    plan = PS.build_plan([bet(1, "Duke Watson", "Rush Attempts", "Under", 14.5)], "NCAAF",
                         fetch=lambda url, params=None: BOARD if url.endswith("scoreboard") else live)
    assert plan["proposed"] == [] and plan["still_pending"][0]["why"] == "game not final yet"


def test_football_legs_typed_with_common_names_still_grade():
    """Nov 28: a PrizePicks leg logged as "Passing Yards" (the grader's name is Pass Yards) would never settle."""
    import postgame as PG
    st = {"rush_yds": 72, "rec": 8, "rec_yds": 101, "pass_yds": 230}
    assert PG.stat_value("NCAAF", "Passing Yards", st) == 230
    assert PG.stat_value("NCAAF", "Rushing Yards", st) == 72
    assert PG.stat_value("NFL", "Rec Yards", st) == 101
    assert PG.stat_value("NCAAF", "Receptions", st) == 8
    assert PG.stat_value("NCAAF", "Bogus", st) is None
