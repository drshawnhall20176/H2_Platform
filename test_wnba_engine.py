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


# ----------------------------------------------------------------- ESPN fetch layer
def test_get_json_returns_none_on_http_error(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            raise E.requests.exceptions.HTTPError("500")

    monkeypatch.setattr(E.requests, "get", lambda *a, **k: FakeResp())
    assert E._get_json("https://example.com") is None


def test_get_json_returns_none_on_timeout(monkeypatch):
    def raise_timeout(*a, **k):
        raise E.requests.exceptions.ReadTimeout("timed out")

    monkeypatch.setattr(E.requests, "get", raise_timeout)
    assert E._get_json("https://example.com") is None


def test_get_json_returns_parsed_body_on_success(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(E.requests, "get", lambda *a, **k: FakeResp())
    assert E._get_json("https://example.com") == {"ok": True}


# ----------------------------------------------------------------- gamelog value parsing
def test_parse_gamelog_value_plain_number():
    assert E._parse_gamelog_value("32") == 32.0


def test_parse_gamelog_value_made_attempted_combo():
    assert E._parse_gamelog_value("12-24") == 12.0   # makes, not attempts


def test_parse_gamelog_value_handles_junk():
    assert E._parse_gamelog_value(None) == 0.0
    assert E._parse_gamelog_value("DNP") == 0.0
    assert E._parse_gamelog_value("") == 0.0


# ----------------------------------------------------------------- get_schedule (ESPN scoreboard)
def test_get_schedule_parses_espn_scoreboard_shape(monkeypatch):
    fake_response = {
        "events": [
            {
                "id": "401810001",
                "date": "2026-07-14T00:00Z",
                "competitions": [{
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "20", "displayName": "Atlanta Dream"}},
                        {"homeAway": "away", "team": {"id": "19", "displayName": "Chicago Sky"}},
                    ]
                }],
            },
            {"id": "bad_event", "competitions": []},   # malformed -> must be skipped, not crash
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)

    games = E.get_schedule("2026-07-14")
    assert len(games) == 1
    g = games[0]
    assert g["home_id"] == 20 and g["home_name"] == "Atlanta Dream"
    assert g["away_id"] == 19 and g["away_name"] == "Chicago Sky"
    assert g["game_date"] == "2026-07-14T00:00Z"
    print("✓ get_schedule parses ESPN's scoreboard shape and skips malformed events")


def test_get_schedule_uses_yyyymmdd_date_param(monkeypatch):
    captured = {}

    def fake_get_json(url, params=None):
        captured["params"] = params
        return {"events": []}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    E.get_schedule("2026-07-14")
    assert captured["params"] == {"dates": "20260714"}


def test_get_schedule_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_schedule("2026-07-14") == []


# ----------------------------------------------------------------- get_team_roster (ESPN roster)
def test_get_team_roster_flattens_position_groups(monkeypatch):
    fake_response = {
        "athletes": [
            {"position": "G", "items": [{"id": "1", "displayName": "Guard One"},
                                        {"id": "2", "displayName": "Guard Two"}]},
            {"position": "F", "items": [{"id": "3", "displayName": "Forward One"}]},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)
    roster = E.get_team_roster(20)
    assert {p["name"] for p in roster} == {"Guard One", "Guard Two", "Forward One"}
    assert all(isinstance(p["id"], int) for p in roster)


def test_get_team_roster_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_roster(20) == []


# ----------------------------------------------------------------- get_player_recent_games (ESPN gamelog)
def test_get_player_recent_games_aligns_names_from_the_right(monkeypatch):
    # Mirrors the documented ESPN shape: `names` includes meta fields (date/opponent/gameResult)
    # BEFORE the stat columns, but `stats` only holds the stat-column values.
    fake_response = {
        "names": ["date", "opponent", "gameResult", "minutes", "fieldGoalsMade",
                 "threePointsMade", "freeThrowsMade", "rebounds", "assists", "steals",
                 "blocks", "points"],
        "events": [
            {"id": "1", "date": "2026-07-13T00:00Z", "gameResult": "W",
             "stats": ["32", "8-15", "3-6", "4-4", "6", "5", "2", "1", "23"]},
        ],
    }

    def fake_get_json(url, params=None):
        assert "/athletes/555/gamelog" in url
        return fake_response

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    games = E.get_player_recent_games(555)

    assert len(games) == 1
    g = games[0]
    assert g["min"] == 32.0
    assert g["fg3m"] == 3.0     # from "3-6" -> makes
    assert g["reb"] == 6.0
    assert g["ast"] == 5.0
    assert g["pts"] == 23.0
    print("✓ get_player_recent_games correctly aligns names/stats and parses made-attempted combos")


def test_get_player_recent_games_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_player_recent_games(555) == []


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
