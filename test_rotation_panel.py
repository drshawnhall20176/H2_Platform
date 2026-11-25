import rotation_panel as RP


def _pg(team, game, order, name, pid, mins, starter):
    return {"team": team, "game": game, "order": order, "name": name, "pid": pid, "starter": starter,
            "stats": {"min": mins}}


def _league():
    pg = []
    for i in range(12):                                       # 12 games; the panel reads the last 10
        g, d = f"g{i}", f"2026-11-{i + 1:02d}"
        for k in range(5):
            pg.append(_pg("BOS", g, d, f"Starter {chr(65 + k)}", f"s{k}", 32 - k, True))
        pg.append(_pg("BOS", g, d, "Sixth Man", "b1", 24, False))
        pg.append(_pg("BOS", g, d, "Deep Guy", "d1", 6 if i % 2 else 0, False))
        pg.append(_pg("NYK", g, d, "Other Team", "o1", 40, True))
    pg.append(_pg("BOS", "g0", "2026-11-01", "Old Starter", "x", 30, True))      # only in a game outside the last 10
    return pg


def test_rotation_uses_the_last_ten_games_and_skips_dnps():
    rot = RP.rotation(_league(), "BOS")
    names = [r["name"] for r in rot]
    assert "Old Starter" not in names and "Other Team" not in names
    deep = next(r for r in rot if r["name"] == "Deep Guy")
    assert deep["games"] == 5 and deep["avg_min"] == 6 and deep["of"] == 10
    s0 = next(r for r in rot if r["name"] == "Starter A")
    assert s0["starts"] == 10 and s0["avg_min"] == 32


def test_groups_and_html():
    g = RP.groups(RP.rotation(_league(), "BOS"))
    assert [r["name"] for r in g["Starters"]] == [f"Starter {chr(65 + k)}" for k in range(5)]
    assert [r["name"] for r in g["Bench"]] == ["Sixth Man"] and [r["name"] for r in g["Deep bench"]] == ["Deep Guy"]
    html = RP.team_html("Boston Celtics", RP.rotation(_league(), "BOS"), proj={"sixth man": 27.0},
                        inj={"starter a": "out"})
    assert "STARTERS" in html and "DEEP BENCH" in html and "→ <b" in html and "🚑" in html
    assert "line-through" in html


def test_proj_minutes_reads_saved_rows():
    got = RP.proj_minutes([{"player": "Jaylen Brown", "proj_min": 35.2}, {"Player": "X", "_proj_min": None},
                           {"player": "Y", "proj_min": "n/a"}])
    assert got == {"jaylen brown": 35.2}


def test_game_card_finds_the_matchup_by_loose_names():
    import game_card as GC
    games = [{"home": "Boston Celtics", "away": "New York Knicks", "home_abbr": "BOS", "away_abbr": "NY"},
             {"home": "Miami Heat", "away": "Orlando Magic"}]
    assert GC._bundle_game("NBA", games, "Knicks", "Celtics") is games[0]
    assert GC._bundle_game("NBA", games, "NY", "BOS") is games[0]
    assert GC._bundle_game("NBA", games, "Magic", "Celtics") is None
