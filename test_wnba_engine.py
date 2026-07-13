"""
test_wnba_engine.py — offline unit tests for wnba_engine's pure logic.

No network required — get_schedule/get_team_roster/get_player_recent_games (the actual live
nba_api calls) are monkeypatched out. This mirrors test_engine.py's approach for MLB: the pure
assembly/filtering logic is fully covered offline; the live HTTP layer is verified separately by
whoever deploys, since stats.wnba.com is unreachable from the build sandbox.

    python test_wnba_engine.py     # or: pytest test_wnba_engine.py
"""

import wnba_engine as E


def _log(pts, reb, ast, fg3m, minutes):
    return {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3m, "min": minutes}


# ----------------------------------------------------------------- avg_minutes
def test_avg_minutes_empty_log():
    assert E.avg_minutes([]) == 0.0


def test_avg_minutes_computes_mean():
    log = [_log(10, 5, 3, 1, 20), _log(14, 6, 2, 2, 30)]
    assert E.avg_minutes(log) == 25.0


# ----------------------------------------------------------------- player_row
def test_player_row_filters_low_minutes():
    log = [_log(2, 1, 0, 0, 5), _log(0, 0, 1, 0, 4)]   # avg 4.5 min -> deep bench
    row = E.player_row({"id": 1, "name": "Bench Player"}, "ATL", "CHI", "CHI @ ATL",
                       "2026-07-13T23:00:00Z", log, min_avg_minutes=12.0)
    assert row is None


def test_player_row_filters_empty_log():
    row = E.player_row({"id": 1, "name": "No Games"}, "ATL", "CHI", "CHI @ ATL", None, [],
                       min_avg_minutes=12.0)
    assert row is None


def test_player_row_computes_averages_for_rotation_player():
    log = [_log(18, 6, 4, 2, 32), _log(22, 4, 6, 3, 34), _log(14, 8, 3, 1, 30)]
    row = E.player_row({"id": 42, "name": "Star Player"}, "Atlanta Dream", "Chicago Sky",
                       "Chicago Sky @ Atlanta Dream", "2026-07-13T23:00:00Z", log,
                       min_avg_minutes=12.0)
    assert row is not None
    assert row["Player"] == "Star Player"
    assert row["Team"] == "Atlanta Dream"
    assert row["Opp"] == "Chicago Sky"
    assert row["AvgMin"] == round((32 + 34 + 30) / 3, 1)
    assert row["PTS"] == round((18 + 22 + 14) / 3, 1)
    assert row["REB"] == round((6 + 4 + 8) / 3, 1)
    assert row["AST"] == round((4 + 6 + 3) / 3, 1)
    assert row["FG3M"] == round((2 + 3 + 1) / 3, 1)
    # private fields for the projections module
    assert row["_pid"] == 42
    assert row["_game_log"] == log
    assert row["_game_date"] == "2026-07-13T23:00:00Z"
    print("✓ player_row computes correct averages and carries the raw log for projections")


# ----------------------------------------------------------------- build_slate orchestration
def test_build_slate_returns_empty_when_no_games(monkeypatch):
    monkeypatch.setattr(E, "get_schedule", lambda date_str: [])
    rows, meta = E.build_slate("2026-07-13")
    assert rows == [] and meta == []


def test_build_slate_assembles_rows_from_mocked_fetches(monkeypatch):
    game = {"gameId": "1", "game_date": "2026-07-13T23:00:00Z",
            "home_id": 1611661330, "home_name": "Atlanta Dream",
            "away_id": 1611661329, "away_name": "Chicago Sky"}
    monkeypatch.setattr(E, "get_schedule", lambda date_str: [game])

    rosters = {
        1611661330: [{"id": 1, "name": "Home Starter"}, {"id": 2, "name": "Home Bench"}],
        1611661329: [{"id": 3, "name": "Away Starter"}],
    }
    monkeypatch.setattr(E, "get_team_roster", lambda team_id: rosters.get(team_id, []))

    logs = {
        1: [_log(20, 5, 4, 2, 30)] * 5,     # rotation player
        2: [_log(2, 1, 0, 0, 6)] * 5,       # deep bench -> filtered out
        3: [_log(15, 7, 3, 1, 28)] * 5,     # rotation player
    }
    monkeypatch.setattr(E, "get_player_recent_games", lambda player_id, last_n: logs.get(player_id, []))

    rows, meta = E.build_slate("2026-07-13", min_avg_minutes=12.0, last_n_games=5)

    assert len(meta) == 1
    assert meta[0]["label"] == "Chicago Sky @ Atlanta Dream"
    names = {r["Player"] for r in rows}
    assert names == {"Home Starter", "Away Starter"}   # bench player filtered by minutes
    home_row = next(r for r in rows if r["Player"] == "Home Starter")
    assert home_row["Team"] == "Atlanta Dream" and home_row["Opp"] == "Chicago Sky"
    print("✓ build_slate wires schedule -> rosters -> game logs -> filtered rows correctly")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            import inspect
            if "monkeypatch" in inspect.signature(t).parameters:
                print(f"SKIP  {t.__name__} (needs pytest's monkeypatch fixture — run via pytest)")
                continue
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed (run via pytest for full monkeypatch coverage)")
