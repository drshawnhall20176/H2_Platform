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
