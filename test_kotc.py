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
