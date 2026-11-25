import alt_hits as AH

ALT = {"player_rebounds_alternate": "player_rebounds", "player_points_alternate": "player_points"}
ROWS = [{"player": "Joel Embiid", "market_key": "player_rebounds", "market": "Rebounds", "game": "MIA @ PHI",
         "time": "7:00 PM", "values": [8, 9, 10, 4, 11, 12, 9, 8, 7, 10], "projection": 9.4, "line": 9.5},
        {"player": "Thin Sample", "market_key": "player_points", "market": "Points", "game": "MIA @ PHI",
         "values": [10, 12]}]
QUOTES = [{"market": "player_rebounds_alternate", "name": "Over", "description": "Joel Embiid", "point": 3.5,
           "price": -900},
          {"market": "player_rebounds_alternate", "name": "Over", "description": "Joel Embiid", "point": 7.5,
           "price": -250},
          {"market": "player_rebounds_alternate", "name": "Under", "description": "Joel Embiid", "point": 7.5,
           "price": 180},
          {"market": "player_points_alternate", "name": "Over", "description": "Thin Sample", "point": 9.5, "price": -200}]


def test_rungs_put_the_hit_rate_beside_the_break_even():
    got = {r["rung"]: r for r in AH.rungs(QUOTES, ROWS, ALT)}
    assert set(got) == {"4+ Rebounds", "8+ Rebounds"}                 # Unders and thin samples are left out
    four, eight = got["4+ Rebounds"], got["8+ Rebounds"]
    assert four["hits"] == 10 and round(four["break_even"], 2) == 0.9 and verdict(four) == "Priced about right"
    assert eight["hits"] == 8 and round(eight["break_even"], 3) == 0.714 and verdict(eight) == "Priced about right"


def verdict(r):
    return AH.verdict(r["margin"])


def test_verdicts_and_table():
    assert AH.verdict(0.15) == "History above break-even" and AH.verdict(-0.2) == "History below break-even"
    t = AH.table(AH.rungs(QUOTES, ROWS, ALT))
    assert t[0]["Last 10"] in ("10/10", "8/10") and t[0]["Price"] in ("-900", "-250") and t[0]["Projection"] == "9.4"


def test_for_day_reads_each_games_archive():
    calls = []
    got = AH.for_day("NBA", "2026-11-25", ROWS, load_odds=lambda h, a: calls.append((h, a)) or {"offers": QUOTES})
    assert calls == [("PHI", "MIA")] and len(got) == 2
    assert AH.for_day("NBA", "2026-11-25", ROWS, load_odds=lambda h, a: None) == []


def test_card_rows_are_his_rungs_with_the_scans_honest_chance():
    p = {"Player": "Joel Embiid", "MarketKey": "player_rebounds", "Market": "Rebounds", "Game": "MIA @ PHI",
         "_values": [8, 9, 10, 4, 11, 12, 9, 8, 7, 10]}
    got = AH.card_rows(p, "NBA", "2026-11-25", load_odds=lambda h, a: {"offers": QUOTES},
                       long_shots=[{"Player": "Joel Embiid", "Market": "Rebounds", "Bet": "8+ Rebounds",
                                    "Honest chance": 0.71}])
    assert [r["rung"] for r in got] == ["4+ Rebounds", "8+ Rebounds"] and got[1]["honest"] == 0.71
    assert got[0]["honest"] is None
    assert AH.card_rows({"Player": "X"}, "NBA", "2026-11-25") == []
