import intl_hoops as I
import tennis_model as T


def _espn_tennis():
    def comp(cid, a, b, wa, sa, sb, status="STATUS_FINAL"):
        return {"id": cid, "date": "2025-10-12T10:00Z", "round": {"displayName": "Round 1"},
                "status": {"type": {"completed": True, "name": status}},
                "competitors": [{"athlete": {"displayName": a}, "winner": wa, "linescores": [{"value": v} for v in sa]},
                                {"athlete": {"displayName": b}, "winner": not wa, "linescores": [{"value": v} for v in sb]}]}
    return {"events": [{"name": "Mutua Madrid Open", "groupings": [
        {"grouping": {"displayName": "Men's Singles"}, "competitions": [
            comp(1, "Carlos Alcaraz", "Jannik Sinner", True, [6, 3, 7], [4, 6, 5]),
            comp(2, "A B", "C D", False, [1, 0], [6, 3], status="STATUS_RETIRED")]},
        {"grouping": {"displayName": "Men's Doubles"}, "competitions": [comp(3, "X", "Y", True, [6], [0])]}]}]}


def test_parse_day_singles_scores_and_surface():
    ms = T.parse_day(_espn_tennis(), "atp")
    assert len(ms) == 2
    m = ms[0]
    assert m["surface"] == "clay" and m["best_of"] == 3 and m["winner"] == 1
    assert (m["sets1"], m["sets2"], m["games1"], m["games2"]) == (2, 1, 16, 15)
    assert ms[1]["status"] == "retired" and ms[1]["winner"] == 2
    assert T.surface("Wimbledon") == "grass" and T.surface("Rolex Paris Masters") == "hard"
    assert T.best_of("Wimbledon", "atp") == 5 and T.best_of("Wimbledon", "wta") == 3


def test_elo_learns_the_better_player():
    ms = [{"id": f"m{i}", "date": f"2025-01-{1 + i % 28:02d}", "p1": "Strong Guy", "p2": f"Weak {i}", "winner": 1,
           "surface": "hard", "status": "final"} for i in range(30)]
    elo, rows = T.run(ms)
    assert rows[0]["p"] == 0.5 and elo.prob("Strong Guy", "Newcomer", "hard") > 0.8
    assert elo.prob("Strong Guy", "Newcomer", "clay") < elo.prob("Strong Guy", "Newcomer", "hard")
    assert elo.matches("strong guy") == 30


def test_games_fit_and_over_chance():
    rows = [{"p": 0.5 + d, "best_of": 3, "status": "final", "games1": 12 + int(20 * d), "games2": 10 - int(20 * d)}
            for d in [x / 100 for x in range(-30, 31)] * 2]
    fit = T.fit_games(rows)
    g = T.games(fit, 0.8, 3)
    assert g["margin"] > 4 and abs(T.p_over(10, 3, 10) - 0.5) < 1e-9


def test_hoops_team_matching_and_projection():
    ev = [{"home_team": "Real Madrid", "away_team": "Panathinaikos"}, {"home_team": "Fenerbahce", "away_team": "Monaco"}]
    assert I.match_event(ev, "Panathinaikos AKTOR Athens", "Real Madrid")["home_team"] == "Real Madrid"
    assert I.match_event(ev, "Olympiacos Piraeus", "Monaco") is None
    games = [{"home_team": h, "away_team": a, "home_points": hp, "away_points": ap, "neutral_site": False}
             for h, a, hp, ap in [("Real Madrid", "Monaco", 90, 80), ("Monaco", "Fenerbahce", 85, 82),
                                  ("Fenerbahce", "Real Madrid", 78, 88)] * 5]
    p = I.project(I.ratings(games, 3.0), "Real Madrid Baloncesto", "AS Monaco")
    assert p and p["margin"] > 0 and 150 < p["total"] < 190
    assert I.win_prob(0) == 0.5 and I.win_prob(10) > 0.75
    assert I.season_of("NBL", "2026-01-10") == "2025" and I.season_of("NBL", "2025-10-10") == "2025"


def test_euroleague_parser():
    data = {"data": [{"identifier": "E2025_1", "played": True, "date": "2025-10-01T18:00:00",
                      "local": {"club": {"name": "Real Madrid"}, "score": 90},
                      "road": {"club": {"name": "Monaco"}, "score": 80}},
                     {"identifier": "E2025_2", "played": False, "local": {}, "road": {}}]}
    g = I.euroleague_season("E2025", fetch=lambda url, params=None: data)
    assert len(g) == 1 and g[0]["home_points"] == 90 and g[0]["date"] == "2025-10-01"
