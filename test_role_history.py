"""Nov 26: the player card's 'what tonight's defense allowed to his role lately'."""
import role_history as RH


def _data():
    allowed = {
        "NYJ": [{"offense": "LAC", "order": 11, "who": {"RB1": ["Omarion Hampton"]}, "slots": {"RB1": {"rush_yds": 89}}},
                {"offense": "BUF", "order": 10, "who": {"RB1": ["James Cook"]}, "slots": {"RB1": {"rush_yds": 157}}},
                {"offense": "NE", "order": 9, "who": {"RB1": ["R. Stevenson"]}, "slots": {"RB1": {"rush_yds": 40}}},
                {"offense": "KC", "order": 8, "who": {"RB1": ["Old Game"]}, "slots": {"RB1": {"rush_yds": 1}}}],
        "X": [{"offense": "MIA", "order": 11, "who": {"RB1": ["Ollie Gordon II"]}, "slots": {"RB1": {"rush_yds": 70}}},
              {"offense": "MIA", "order": 10, "who": {"RB1": ["Ollie Gordon II"]}, "slots": {"RB1": {"rush_yds": 60}}}]}
    return {"games": [{"home": "MIA", "away": "NYJ", "home_id": "MIA", "away_id": "NYJ"}], "allowed": allowed,
            "names": {"LAC": "Chargers", "BUF": "Bills", "NE": "Patriots"}, "pgames": []}


def test_football_role_history_last_three_games():
    h = RH.for_player("NFL", _data(), "Ollie Gordon II", "MIA", "New York Jets @ Miami Dolphins", "Rush Yards")
    assert h["slot"] == "RB1" and h["defense"] == "New York Jets"
    assert [(r["name"], r["value"]) for r in h["rows"]] == [("Omarion Hampton", 89), ("James Cook", 157),
                                                            ("R. Stevenson", 40)]
    t = RH.text(h, "NFL")
    assert t.startswith("**vs New York Jets, recent lead RBs — rush yds:** Wk11 Omarion Hampton 89 (Chargers)")


def test_unknown_market_or_role_is_quiet():
    assert RH.for_player("NFL", _data(), "Ollie Gordon II", "MIA", "New York Jets @ Miami Dolphins", "Anytime TD") is None
    assert RH.for_player("NFL", _data(), "Nobody", "MIA", "New York Jets @ Miami Dolphins", "Rush Yards") is None


def test_nba_rows_take_the_groups_top_player():
    pg = [{"opp": 9, "team": 1, "pos": "PG", "order": "2026-11-24", "game": "a", "name": "Brunson", "stats": {"pts": 31}},
          {"opp": 9, "team": 1, "pos": "SG", "order": "2026-11-24", "game": "a", "name": "Bridges", "stats": {"pts": 18}},
          {"opp": 9, "team": 2, "pos": "G", "order": "2026-11-22", "game": "b", "name": "Young", "stats": {"pts": 25}},
          {"opp": 9, "team": 2, "pos": "C", "order": "2026-11-22", "game": "b", "name": "Big", "stats": {"pts": 40}}]
    rows = RH.nba_rows(pg, 9, "G", "pts")
    assert [(r["name"], r["value"]) for r in rows] == [("Brunson", 31), ("Young", 25)]
    assert RH.when("2026-11-24", "NBA") == "Nov 24" and RH.when(11, "NFL") == "Wk11"
