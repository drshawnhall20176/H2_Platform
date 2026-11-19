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
