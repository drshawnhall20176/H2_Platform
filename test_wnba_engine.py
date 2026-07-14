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
    monkeypatch.setattr(E, "get_player_recent_games",
                        lambda player_id, last_n, team_id=None, before_date=None: logs.get(player_id, []))

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


# ----------------------------------------------------------------- boxscore stat-value parsing
def test_parse_stat_value_plain_number():
    assert E._parse_stat_value("32") == 32.0


def test_parse_stat_value_made_attempted_combo():
    assert E._parse_stat_value("12-24") == 12.0   # makes, not attempts


def test_parse_stat_value_handles_junk():
    assert E._parse_stat_value(None) == 0.0
    assert E._parse_stat_value("DNP") == 0.0
    assert E._parse_stat_value("") == 0.0


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


def test_get_team_roster_handles_flat_player_list_shape(monkeypatch):
    # The shape that actually explains the live bug: 'athletes' present, but each entry IS a
    # player directly, no {"position", "items"} grouping wrapper like the docs show.
    fake_response = {
        "athletes": [
            {"id": "1", "displayName": "Player One"},
            {"id": "2", "displayName": "Player Two"},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)
    roster = E.get_team_roster(18)
    assert {p["name"] for p in roster} == {"Player One", "Player Two"}
    assert all(isinstance(p["id"], int) for p in roster)
    print("✓ get_team_roster handles the flat (ungrouped) athletes shape, not just the documented one")


def test_get_team_roster_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_roster(20) == []


# ----------------------------------------------------------------- request caching
def test_get_json_cached_dedupes_identical_requests(monkeypatch):
    E._response_cache.clear()
    calls = []

    def fake_get_json(url, params=None):
        calls.append((url, params))
        return {"n": len(calls)}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    r1 = E._get_json_cached("https://example.com/x", params={"a": 1})
    r2 = E._get_json_cached("https://example.com/x", params={"a": 1})
    r3 = E._get_json_cached("https://example.com/x", params={"a": 2})   # different params -> new call

    assert r1 == r2 == {"n": 1}
    assert r3 == {"n": 2}
    assert len(calls) == 2
    print("✓ _get_json_cached dedupes identical (url, params) requests within a process")


# ----------------------------------------------------------------- get_team_recent_game_ids
def test_get_team_recent_game_ids_filters_to_completed_games_for_that_team(monkeypatch):
    E._response_cache.clear()
    fake_scoreboard = {
        "events": [
            {"id": "g1", "date": "2026-07-10T00:00Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "20"}}, {"team": {"id": "19"}}]}]},
            {"id": "g2", "date": "2026-07-12T00:00Z",   # not this team -> excluded
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "5"}}, {"team": {"id": "19"}}]}]},
            {"id": "g3", "date": "2026-07-14T00:00Z",   # this team, but not completed -> excluded
             "status": {"type": {"completed": False}},
             "competitions": [{"competitors": [{"team": {"id": "20"}}, {"team": {"id": "16"}}]}]},
            {"id": "g4", "date": "2026-07-13T00:00Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "20"}}, {"team": {"id": "9"}}]}]},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_scoreboard)

    ids = E.get_team_recent_game_ids(20, "2026-07-14", n=10)
    assert ids == ["g4", "g1"]   # both g1/g4 involve team 20 and are completed, newest first
    print("✓ get_team_recent_game_ids keeps only this team's completed games, newest first")


def test_get_team_recent_game_ids_empty_on_fetch_failure(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_recent_game_ids(20, "2026-07-14") == []


# ----------------------------------------------------------------- get_game_boxscore
def test_get_game_boxscore_extracts_every_player_from_both_teams(monkeypatch):
    E._response_cache.clear()
    fake_summary = {
        "boxscore": {
            "teams": [
                {"team": {"id": "20"}, "players": [{
                    "statistics": [{
                        "names": ["MIN", "FG", "3PT", "FT", "REB", "AST", "STL", "BLK", "TO", "PTS"],
                        "athletes": [
                            {"athlete": {"id": "111"}, "didNotPlay": False,
                             "stats": ["32", "8-15", "3-6", "4-4", "6", "5", "1", "0", "2", "23"]},
                            {"athlete": {"id": "112"}, "didNotPlay": True, "stats": []},
                        ],
                    }],
                }]},
                {"team": {"id": "19"}, "players": [{
                    "statistics": [{
                        "names": ["MIN", "FG", "3PT", "FT", "REB", "AST", "STL", "BLK", "TO", "PTS"],
                        "athletes": [
                            {"athlete": {"id": "222"}, "didNotPlay": False,
                             "stats": ["28", "5-12", "1-4", "2-2", "9", "3", "0", "1", "3", "13"]},
                        ],
                    }],
                }]},
            ]
        }
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_summary)

    box = E.get_game_boxscore("g1")
    assert set(box.keys()) == {111, 222}   # 112 excluded (didNotPlay)
    assert box[111] == {"pts": 23.0, "reb": 6.0, "ast": 5.0, "fg3m": 3.0, "min": 32.0}
    assert box[222]["pts"] == 13.0 and box[222]["min"] == 28.0
    print("✓ get_game_boxscore extracts both teams' players in one call, skips DNPs")


def test_get_game_boxscore_empty_on_fetch_failure(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_game_boxscore("g1") == {}


# ----------------------------------------------------------------- get_player_recent_games
def test_get_player_recent_games_requires_team_id_and_before_date():
    # Without these there's no way to know which games to look at -> empty, not a guess.
    assert E.get_player_recent_games(111) == []
    assert E.get_player_recent_games(111, team_id=20) == []
    assert E.get_player_recent_games(111, before_date="2026-07-14") == []


def test_get_player_recent_games_pulls_from_team_games_via_boxscore(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=E.CFG.RECENT_GAMES_N: ["g1", "g2"])
    boxscores = {
        "g1": {111: {"pts": 20.0, "reb": 5.0, "ast": 4.0, "fg3m": 2.0, "min": 30.0}},
        "g2": {111: {"pts": 18.0, "reb": 6.0, "ast": 3.0, "fg3m": 1.0, "min": 28.0},
               999: {"pts": 10.0, "reb": 2.0, "ast": 1.0, "fg3m": 0.0, "min": 15.0}},
    }
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: boxscores.get(gid, {}))

    games = E.get_player_recent_games(111, last_n=10, team_id=20, before_date="2026-07-14")
    assert games == [
        {"pts": 20.0, "reb": 5.0, "ast": 4.0, "fg3m": 2.0, "min": 30.0},
        {"pts": 18.0, "reb": 6.0, "ast": 3.0, "fg3m": 1.0, "min": 28.0},
    ]
    print("✓ get_player_recent_games pulls this player's line out of each recent game's shared boxscore")


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
