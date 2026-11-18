import kotc as K


def _board(player, team, pts, reb, ast, game="A @ B"):
    return [{"Player": player, "Team": team, "Opp": "X", "Market": m, "Recent Avg": v, "Matchup Score": v, "Game": game}
            for m, v in (("Points", pts), ("Rebounds", reb), ("Assists", ast))]


def test_king_chance_ranks_the_big_line_first_and_blowouts_cost_starters():
    board = _board("Jokic", "Nuggets", 28, 12, 10) + _board("Role", "Nuggets", 10, 4, 2) + \
        _board("Star", "Knicks", 30, 6, 8, game="Bucks @ Knicks")
    info = {("Jokic", "Nuggets"): {"min": 35, "pra": [48, 52, 45, 50, 55, 47]},
            ("Role", "Nuggets"): {"min": 22, "pra": [15, 16, 14, 18]},
            ("Star", "Knicks"): {"min": 34, "pra": [44, 40, 46, 42, 45]}}
    blow = K.blowout_by_team([{"game": "Bucks @ Knicks", "team": "Knicks", "who": "favorite", "fav_big": 0.54,
                               "dog_big": 0.02, "line": "Knicks −15.5"},
                              {"game": "A @ Nuggets", "team": "Nuggets", "who": "favorite", "fav_big": 0.10,
                               "dog_big": 0.05, "line": "Nuggets −2.5"}])
    rows = K.build(board, info, blow, sims=4000)
    assert rows[0]["Player"] == "Jokic" and rows[0]["King chance"] > 0.5
    star = next(r for r in rows if r["Player"] == "Star")
    assert star["Min at risk"] > 0 and star["Adj PRA"] < star["Proj PRA"]
    assert sum(r["King chance"] for r in rows) > 0.99
    assert all(r["Player"] != "Jokic" for r in K.build(board, info, blow, {"Jokic"}, sims=500))


def test_model_projection_leads():
    """Nov 17: King of the Court uses the model's PRA projection, not the Hot Hand's own score."""
    import kotc as K
    reads = {("nikola jokic", "PRA"): {"projection": 52.0}, ("a b", "Points"): {"projection": 20.0},
             ("a b", "Rebounds"): {"projection": 5.0}, ("a b", "Assists"): {"projection": 4.0}}
    mp = K.model_pra(reads)
    assert mp == {"nikola jokic": 52.0, "a b": 29.0}
    board = [{"Player": "Nikola Jokic", "Team": "DEN", "Opp": "PHX", "Market": m, "Recent Avg": 10, "Matchup Score": 10,
              "Game": "g"} for m in K.PRA_MARKETS]
    rows = K.build(board, {}, {}, model_proj=mp, sims=200)
    assert rows[0]["Proj PRA"] == 52.0 and rows[0]["Source"] == "model"


def test_whole_field_has_a_real_chance():
    """Nov 18: Sensabaugh / Grimes (~15 PRA projected) tied for the crown at 56 while the old sim had them at exactly 0%.
    Every rotation player is simulated now, from how players at his level actually finish against the model."""
    board = _board("Star", "LAL", 36, 7, 8) + _board("Two", "SA", 25, 12, 4, game="g2")
    for i in range(30):
        board += _board(f"Bench{i}", f"T{i % 8}", 9, 3, 2, game=f"g{i % 4}")
    rows = K.build(board, {}, {}, sims=20000)
    assert rows[0]["Player"] == "Star" and 0.15 < rows[0]["King chance"] < 0.8
    bench = [r for r in rows if r["Player"].startswith("Bench")]
    assert all(r["King chance"] > 0 for r in bench[:5]) and sum(r["King chance"] for r in bench) > 0.03
    assert abs(sum(r["King chance"] for r in rows) - 1.0) < 1e-9
    f = K.field_chance(rows)
    assert f is not None and 0.0 < f < 1.0
