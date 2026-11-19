import components as C


def test_outcome_reads_every_spelling():
    for v in ("✅", "hit", "win", "✅ won", True, "Hit"):
        assert C.outcome(v) == "hit", v
    for v in ("❌", "miss", "loss", "❌ lost", False, "Miss"):
        assert C.outcome(v) == "miss", v
    for v in (None, "", "push", "void", "—", "⏳", "Open"):
        assert C.outcome(v) is None, v


def test_bands_by_chance_with_expected():
    rows = [{"r": "✅", "c": 0.038}, {"r": "❌", "c": 0.039}, {"r": "❌", "c": 0.12}, {"r": "✅", "c": 0.62},
            {"r": "❌", "c": 0.64}, {"r": "push", "c": 0.6}, {"r": "✅", "c": None}]
    b = C.chance_bands(rows, "r", "c")
    assert [x["Chance"] for x in b] == ["0%–5%", "10%–15%", "60%–65%"]
    assert b[0]["Hits"] == 1 and b[0]["Misses"] == 1 and abs(b[0]["Expected"] - 0.0385) < 1e-9
    assert b[2]["Picks"] == 2 and b[2]["Hit rate"] == 0.5


def test_long_shots_page_has_the_split_and_a_misses_filter():
    src = open("views/53_Long_Shots.py").read()
    assert "C.hit_miss_breakdown(rows" in src and "C.show_filter(rows" in src
    for f in ("Home.py", "views/41_Postgame_Review.py", "views/50_Game_Script.py", "views/54_Live_Games.py",
              "views/40_Analyst_Record.py", "views/19_Track_Record.py"):
        assert "hit_miss_breakdown(" in open(f).read(), f


def test_saved_long_shots_graded_from_box_scores():
    import long_shots_scan as LSS
    rows = [{"Player": "RJ Barrett", "Bet": "45+ Pts+Reb+Ast", "Market": "Pts+Reb+Ast"},
            {"Player": "Dean Wade", "Bet": "3+ Threes Made", "Market": "Threes Made"},
            {"Player": "Nobody", "Bet": "8+ Assists", "Market": "Assists"}]
    snaps = [{"player": "RJ Barrett", "team": "28", "opp": "27"}, {"player": "Dean Wade", "team": "5", "opp": "19"}]
    box = lambda tid, name, st: {"final": True, "teams": {tid: {name: st}}}
    res = {("28", "27"): box("28", "rj barrett", {"pts": 30, "reb": 10, "ast": 6}),
           ("5", "19"): box("5", "dean wade", {"pts": 8, "fg3m": 2, "3pm": 2})}
    got = LSS.grade_saved(rows, "NBA", "2026-11-18", snaps=snaps, results=res)
    assert [g["Hit"] for g in got] == ["✅", "❌", None] and got[0]["Actual"] == 46.0


def test_blowout_result_from_archived_finals_when_ungraded():
    import todays_best as TB
    k = {"fav": "Houston Rockets", "dog": "Indiana Pacers", "kick": "2026-11-19T00:00:00Z", "gid": "1"}
    finals = [{"date": "2026-11-19", "home_team": "Indiana Pacers", "away_team": "Houston Rockets",
               "home_points": 98, "away_points": 121}]
    assert TB._script_from_finals("NBA", k, {}, load=lambda sp, since=None: finals) == "fav_blowout"
    close = [dict(finals[0], away_points=100)]
    assert TB._script_from_finals("NBA", k, {}, load=lambda sp, since=None: close) == "close"
    assert TB._script_from_finals("NBA", k, {}, load=lambda sp, since=None: []) is None


def test_a_late_rebuild_keeps_the_started_games_picks():
    import todays_best as TB
    old = [{"game": "A @ B", "pick": "x"}, {"game": "C @ D", "pick": "y"}]
    new = [{"game": "C @ D", "pick": "y2"}]
    assert TB.keep_started(new, old) == [{"game": "C @ D", "pick": "y2"}, {"game": "A @ B", "pick": "x"}]
    assert TB.keep_started([], old) == old and TB.keep_started(new, None) == new


def test_lost_day_rebuilt_from_snapshots():
    import todays_best as TB, props_engine as PE
    snaps = [{"player": "A", "market": "Points", "side": "Over", "line": 20.5, "chance": 0.66, "cushion": 0.2,
              "use_tag": PE.USE_PASS, "bet_use_tag": PE.USE_SINGLE, "bet_side": "Over", "bet_line": 19.5,
              "bet_chance": 0.6, "price": -110, "book": "draftkings", "game": "X @ Y", "kickoff": "2026-11-19T00:10:00Z"},
             {"player": "B", "market": "Points", "side": "Under", "line": 10.5, "chance": 0.5, "cushion": 0.01,
              "use_tag": PE.USE_PASS, "price": -110, "book": "draftkings", "game": "X @ Y", "ev": 0.0}]
    rows = TB.props_from_snapshots("NBA", "2026-11-18", snaps=snaps)
    assert len(rows) == 1 and rows[0]["pick"] == "A Points Over 19.5" and rows[0]["use"] == PE.USE_SINGLE
    assert rows[0]["time"] == "7:10 PM"


def test_combo_markets_find_their_result(monkeypatch):
    """Nov 19: saved picks say 'Pts+Reb', snapshots 'PR' -- 14 of 19 NCAAMB picks showed no result."""
    import todays_best as TB
    monkeypatch.setattr(TB, "load_props", lambda sp, d: {"at": "x", "rows": [
        {"kind": "Prop", "player": "Braylon Mullins", "market": "Pts+Reb", "side": "Under", "line": 23.5, "pick": "p"}]})
    monkeypatch.setattr(TB, "prop_results", lambda sp, d: {("braylon mullins", "PR", "Under", 23.5): "win"})
    monkeypatch.setattr(TB, "game_rows", lambda d, past=False: [])
    got = TB.collect("2026-11-18", ["NCAAMB"], past=True)["rows"]
    assert got[0]["result"] == "win"


def test_game_lines_two_charts_and_filter_by_either_column():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string('''
import components as C
rows = [{"pick": "✅ won", "pc": 0.508, "winner": "❌ lost", "wc": 0.62},
        {"pick": "❌ lost", "pc": 0.508, "winner": "✅ won", "wc": 0.91},
        {"pick": "❌ lost", "pc": 0.508, "winner": "✅ won", "wc": 0.85}]
C.hit_miss_pair([("Pick result", rows, "pick", "pc"), ("Winner result", rows, "winner", "wc")], key="t")
shown = C.show_filter(rows, "pick", key="f", by={"Pick result": "pick", "Winner result": "winner"})
import streamlit as st
st.write(len(shown))
''').run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    assert "**Pick result**: 1 hit, 2 missed" in md and "**Winner result**: 2 hit, 1 missed" in md
    assert any("same chance" in c.value for c in at.caption)          # one band: no table, a note
    at.radio(key="f").set_value(C.SHOW_HITS).run()
    at.radio(key="f_by").set_value("Winner result").run()
    assert at.markdown[-1].value.strip("`") == "2"
