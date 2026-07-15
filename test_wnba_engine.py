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
    assert home_row["_opp_id"] == 1611661329   # Chicago Sky's id -- needed for Hot Hand Engine's defense lookup
    assert home_row["_team_id"] == 1611661330  # Atlanta Dream's own id -- needed for Matchup Lab's H2H lookup
    away_row = next(r for r in rows if r["Player"] == "Away Starter")
    assert away_row["_opp_id"] == 1611661330
    assert away_row["_team_id"] == 1611661329
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


def test_parse_stat_value_side_right_returns_attempts():
    assert E._parse_stat_value("12-24", side="right") == 24.0


def test_parse_stat_value_side_right_on_plain_field_unaffected():
    # No '-' present -> side has no combo to split, same value either way
    assert E._parse_stat_value("32", side="right") == 32.0


def test_parse_stat_value_side_left_is_still_the_default():
    assert E._parse_stat_value("12-24") == 12.0


def test_find_team_stat_side_right_pulls_attempts_from_combo_key():
    stats = {"fieldGoalsMade-fieldGoalsAttempted": "33-82"}
    assert E._find_team_stat(stats, "fieldGoalsMade-fieldGoalsAttempted", side="right") == 82.0
    # default side is unaffected -> still makes
    assert E._find_team_stat(stats, "fieldGoalsMade-fieldGoalsAttempted") == 33.0


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
             "competitions": [{"competitors": [{"team": {"id": "20", "displayName": "Atlanta Dream"}},
                                               {"team": {"id": "19", "displayName": "Chicago Sky"}}]}]},
            {"id": "g2", "date": "2026-07-12T00:00Z",   # not this team -> excluded
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "5", "displayName": "Dallas Wings"}},
                                               {"team": {"id": "19", "displayName": "Chicago Sky"}}]}]},
            {"id": "g3", "date": "2026-07-14T00:00Z",   # this team, but not completed -> excluded
             "status": {"type": {"completed": False}},
             "competitions": [{"competitors": [{"team": {"id": "20", "displayName": "Atlanta Dream"}},
                                               {"team": {"id": "16", "displayName": "Washington Mystics"}}]}]},
            {"id": "g4", "date": "2026-07-13T00:00Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "20", "displayName": "Atlanta Dream"}},
                                               {"team": {"id": "9", "displayName": "New York Liberty"}}]}]},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_scoreboard)

    games = E.get_team_recent_game_ids(20, "2026-07-14", n=10)
    assert [g["gameId"] for g in games] == ["g4", "g1"]   # both involve team 20, completed, newest first
    assert games[0]["opp_name"] == "New York Liberty"
    assert games[1]["opp_name"] == "Chicago Sky"
    print("✓ get_team_recent_game_ids keeps only this team's completed games, newest first, with opponent")


def test_get_team_recent_game_ids_excludes_games_on_the_target_date_itself(monkeypatch):
    # Lookahead-bias guard: a game happening ON before_date (e.g. retrospective grading called
    # after that date's games finished) must never appear in its own "recent form" sample.
    E._response_cache.clear()
    fake_scoreboard = {
        "events": [
            {"id": "g_before", "date": "2026-07-13T00:00Z",
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "20", "displayName": "Atlanta Dream"}},
                                               {"team": {"id": "19", "displayName": "Chicago Sky"}}]}]},
            {"id": "g_same_day", "date": "2026-07-14T00:00Z",   # same calendar day as before_date
             "status": {"type": {"completed": True}},
             "competitions": [{"competitors": [{"team": {"id": "20", "displayName": "Atlanta Dream"}},
                                               {"team": {"id": "16", "displayName": "Washington Mystics"}}]}]},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_scoreboard)
    games = E.get_team_recent_game_ids(20, "2026-07-14", n=10)
    assert [g["gameId"] for g in games] == ["g_before"]
    print("✓ get_team_recent_game_ids excludes games on before_date itself, not just future ones")


def test_get_team_recent_game_ids_empty_on_fetch_failure(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_recent_game_ids(20, "2026-07-14") == []


# ----------------------------------------------------------------- get_game_boxscore
def test_get_game_boxscore_uses_cdn_endpoint(monkeypatch):
    # Regression guard: both site.api.espn.com AND site.web.api.espn.com's summary responses came
    # back with team-level stats only for real WNBA games (no 'players' key anywhere, confirmed
    # via two separate live diagnostic dumps). cdn.espn.com is the confirmed-working source —
    # verified live: gamepackageJSON.boxscore.players is a real sibling array to boxscore.teams,
    # each entry with a genuine 'statistics' key.
    captured = {}

    def fake_get_json(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {"gamepackageJSON": {"boxscore": {"teams": [], "players": []}}}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    E.get_game_boxscore("g1")
    assert captured["url"] == "https://cdn.espn.com/core/wnba/boxscore"
    assert captured["params"] == {"xhr": "1", "gameId": "g1"}
    print("✓ get_game_boxscore hits cdn.espn.com with xhr=1, not the site API summary endpoint")


def test_get_game_boxscore_extracts_every_player_from_both_teams(monkeypatch):
    E._response_cache.clear()
    # CDN shape, confirmed live: boxscore.players is a SIBLING to boxscore.teams (one entry per
    # team), not nested inside each team block the way the "site" API family's docs assumed.
    fake_cdn_response = {
        "gamepackageJSON": {
            "boxscore": {
                "teams": [{"team": {"id": "20"}}, {"team": {"id": "19"}}],
                "players": [
                    {"team": {"id": "20"}, "statistics": [{
                        "names": ["MIN", "FG", "3PT", "FT", "REB", "AST", "STL", "BLK", "TO", "PTS"],
                        "athletes": [
                            {"athlete": {"id": "111"}, "didNotPlay": False,
                             "stats": ["32", "8-15", "3-6", "4-4", "6", "5", "1", "0", "2", "23"]},
                            {"athlete": {"id": "112"}, "didNotPlay": True, "stats": []},
                        ],
                    }]},
                    {"team": {"id": "19"}, "statistics": [{
                        "names": ["MIN", "FG", "3PT", "FT", "REB", "AST", "STL", "BLK", "TO", "PTS"],
                        "athletes": [
                            {"athlete": {"id": "222"}, "didNotPlay": False,
                             "stats": ["28", "5-12", "1-4", "2-2", "9", "3", "0", "1", "3", "13"]},
                        ],
                    }]},
                ],
            }
        }
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn_response)

    box = E.get_game_boxscore("g1")
    assert set(box.keys()) == {111, 222}   # 112 excluded (didNotPlay)
    assert box[111] == {"pts": 23.0, "reb": 6.0, "ast": 5.0, "fg3m": 3.0, "min": 32.0}
    assert box[222]["pts"] == 13.0 and box[222]["min"] == 28.0
    print("✓ get_game_boxscore extracts both teams' players from the CDN's sibling players array, skips DNPs")


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
                        lambda team_id, before_date, n=E.CFG.RECENT_GAMES_N, days_back=45: [
                            {"gameId": "g1", "date": "2026-07-13T23:00Z", "opp_id": 19, "opp_name": "Chicago Sky"},
                            {"gameId": "g2", "date": "2026-07-11T23:00Z", "opp_id": 16, "opp_name": "Washington Mystics"},
                        ])
    boxscores = {
        "g1": {111: {"pts": 20.0, "reb": 5.0, "ast": 4.0, "fg3m": 2.0, "min": 30.0}},
        "g2": {111: {"pts": 18.0, "reb": 6.0, "ast": 3.0, "fg3m": 1.0, "min": 28.0},
               999: {"pts": 10.0, "reb": 2.0, "ast": 1.0, "fg3m": 0.0, "min": 15.0}},
    }
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: boxscores.get(gid, {}))

    games = E.get_player_recent_games(111, last_n=10, team_id=20, before_date="2026-07-14")
    assert len(games) == 2
    assert games[0]["pts"] == 20.0 and games[0]["opp"] == "Chicago Sky" and games[0]["date"] == "2026-07-13T23:00Z"
    assert games[1]["pts"] == 18.0 and games[1]["opp"] == "Washington Mystics"
    print("✓ get_player_recent_games pulls this player's line out of each recent game's shared "
          "boxscore, tagged with the actual opponent and date")


# ----------------------------------------------------------------- get_player_results
def test_get_player_results_merges_across_games(monkeypatch):
    schedule = [{"gameId": "g1"}, {"gameId": "g2"}]
    boxscores = {
        "g1": {111: {"pts": 20.0, "reb": 5.0, "ast": 4.0, "fg3m": 2.0, "min": 30.0}},
        "g2": {222: {"pts": 15.0, "reb": 7.0, "ast": 2.0, "fg3m": 1.0, "min": 25.0}},
    }
    monkeypatch.setattr(E, "get_schedule", lambda date_str: schedule)
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: boxscores.get(gid, {}))

    results = E.get_player_results("2026-07-13")
    assert set(results.keys()) == {111, 222}
    assert results[111]["pts"] == 20.0
    print("✓ get_player_results merges per-player results across every game on the date")


def test_get_player_results_empty_when_no_games(monkeypatch):
    monkeypatch.setattr(E, "get_schedule", lambda date_str: [])
    assert E.get_player_results("2026-07-13") == {}


# ----------------------------------------------------------------- get_game_team_totals
def test_get_game_team_totals_parses_both_teams(monkeypatch):
    E._response_cache.clear()
    fake_cdn = {
        "gamepackageJSON": {
            "boxscore": {
                "teams": [
                    {"team": {"id": "20"}, "statistics": [
                        {"name": "points", "displayValue": "88"},
                        {"name": "rebounds", "displayValue": "36"},
                        {"name": "assists", "displayValue": "20"},
                        {"name": "threePointFieldGoalsMade", "displayValue": "9"},
                    ]},
                    {"team": {"id": "19"}, "statistics": [
                        {"name": "points", "displayValue": "81"},
                        {"name": "rebounds", "displayValue": "31"},
                        {"name": "assists", "displayValue": "17"},
                        {"name": "threePointFieldGoalsMade", "displayValue": "7"},
                    ]},
                ]
            }
        }
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    totals = E.get_game_team_totals("g1")
    assert totals[20] == {"pts": 88.0, "reb": 36.0, "ast": 20.0, "fg3m": 9.0, "poss": 0.0}
    assert totals[19]["pts"] == 81.0
    print("✓ get_game_team_totals parses team-level totals for both teams")


def test_get_game_team_totals_empty_on_fetch_failure(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_game_team_totals("g1") == {}


def test_get_game_team_totals_handles_real_combo_named_fields(monkeypatch):
    # Regression test for a real production bug: Hot Hand Engine showed "Opp Allows" = 0.0 for
    # EVERY player on a real slate. Root cause, confirmed against a live example (ScrapeCreators'
    # documented CDN boxscore walkthrough): team-level made-count stats use COMBO names —
    # "threePointFieldGoalsMade-threePointFieldGoalsAttempted" — not the bare
    # "threePointFieldGoalsMade" key this module originally guessed. This fixture uses that exact
    # real shape, plus "totalRebounds" instead of "rebounds" (the same naming split already found
    # for player-level stats), to confirm the fallback matching actually handles both surprises.
    E._response_cache.clear()
    fake_cdn = {
        "gamepackageJSON": {
            "boxscore": {
                "teams": [
                    {"team": {"id": "20"}, "statistics": [
                        {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "33-82", "label": "FG"},
                        {"name": "fieldGoalPct", "displayValue": "40.2"},
                        {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
                         "displayValue": "9-25", "label": "3PT"},
                        {"name": "threePointFieldGoalPct", "displayValue": "36.0"},
                        {"name": "totalRebounds", "displayValue": "36"},
                        {"name": "assists", "displayValue": "20"},
                        {"name": "points", "displayValue": "88"},
                    ]},
                ]
            }
        }
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    totals = E.get_game_team_totals("g1")
    assert totals[20]["fg3m"] == 9.0     # from the combo key, makes (left side), not attempts
    assert totals[20]["reb"] == 36.0     # from "totalRebounds", not a "rebounds" key that isn't there
    assert totals[20]["pts"] == 88.0
    assert totals[20]["ast"] == 20.0
    print("✓ get_game_team_totals correctly handles combo-named keys and totalRebounds/rebounds naming split")


def test_get_game_team_totals_estimates_possessions(monkeypatch):
    # Poss = FGA - OREB + TOV + 0.44*FTA. FGA=82 (right side of the combo), OREB=10, TOV=15,
    # FTA=20 (right side of the free-throw combo) -> 82 - 10 + 15 + 0.44*20 = 95.8
    E._response_cache.clear()
    fake_cdn = {
        "gamepackageJSON": {
            "boxscore": {
                "teams": [
                    {"team": {"id": "20"}, "statistics": [
                        {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "33-82"},
                        {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "14-20"},
                        {"name": "offensiveRebounds", "displayValue": "10"},
                        {"name": "totalTurnovers", "displayValue": "15"},
                        {"name": "totalRebounds", "displayValue": "36"},
                        {"name": "assists", "displayValue": "20"},
                        {"name": "points", "displayValue": "88"},
                    ]},
                ]
            }
        }
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    totals = E.get_game_team_totals("g1")
    assert abs(totals[20]["poss"] - 95.8) < 1e-6
    print("✓ get_game_team_totals estimates possessions from FGA/OREB/TOV/FTA")


def test_get_game_team_totals_poss_zero_when_fields_unmatched(monkeypatch):
    # If the possession-input field names don't match anything (no FGA/FTA/OREB/TOV keys present),
    # poss should come back 0.0 rather than a bogus negative number or a crash.
    E._response_cache.clear()
    fake_cdn = {
        "gamepackageJSON": {
            "boxscore": {
                "teams": [
                    {"team": {"id": "20"}, "statistics": [
                        {"name": "points", "displayValue": "88"},
                        {"name": "totalRebounds", "displayValue": "36"},
                        {"name": "assists", "displayValue": "20"},
                    ]},
                ]
            }
        }
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    totals = E.get_game_team_totals("g1")
    assert totals[20]["poss"] == 0.0
    print("✓ get_game_team_totals returns poss=0.0 (not negative) when possession inputs don't match")


# ----------------------------------------------------------------- get_team_recent_allowed_stats
def test_get_team_recent_allowed_stats_averages_opponent_totals(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=E.CFG.RECENT_GAMES_N, days_back=45: [
                            {"gameId": "g1", "date": "2026-07-12T00:00Z", "opp_id": 19, "opp_name": "Chicago Sky"},
                            {"gameId": "g2", "date": "2026-07-10T00:00Z", "opp_id": 16, "opp_name": "Washington Mystics"},
                        ])
    game_totals = {
        "g1": {20: {"pts": 90.0, "reb": 35.0, "ast": 20.0, "fg3m": 8.0, "poss": 96.0},
              19: {"pts": 78.0, "reb": 30.0, "ast": 16.0, "fg3m": 6.0, "poss": 94.0}},
        "g2": {20: {"pts": 85.0, "reb": 33.0, "ast": 19.0, "fg3m": 9.0, "poss": 90.0},
              16: {"pts": 82.0, "reb": 32.0, "ast": 18.0, "fg3m": 8.0, "poss": 92.0}},
    }
    monkeypatch.setattr(E, "get_game_team_totals", lambda gid: game_totals.get(gid, {}))

    allowed = E.get_team_recent_allowed_stats(20, "2026-07-14", n=10)
    # team 20's opponents scored 78 and 82 -> allowed avg pts = 80.0
    assert allowed["pts"] == 80.0
    assert allowed["reb"] == 31.0
    # opponents' own possessions in those same games -> avg poss = (94 + 92) / 2 = 93.0
    assert allowed["poss"] == 93.0
    print("✓ get_team_recent_allowed_stats correctly averages the OPPONENT's totals (incl. poss), not this team's own")


def test_get_team_recent_allowed_stats_empty_when_no_recent_games(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=10, days_back=45: [])
    allowed = E.get_team_recent_allowed_stats(20, "2026-07-14")
    assert allowed == {"pts": 0.0, "reb": 0.0, "ast": 0.0, "fg3m": 0.0, "poss": 0.0}


# ----------------------------------------------------------------- get_team_rest_info
def test_get_team_rest_info_flags_back_to_back(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [
                            {"gameId": "g1", "date": "2026-07-13T00:00Z", "opp_id": 19, "opp_name": "Chicago Sky"},
                        ])
    info = E.get_team_rest_info(20, "2026-07-14")   # played 07-13, tonight is 07-14 -> 1 day rest
    assert info["rest_days"] == 1
    assert info["is_back_to_back"] is True
    assert info["last_game_date"] == "2026-07-13"
    assert info["last_opp_name"] == "Chicago Sky"
    print("✓ get_team_rest_info correctly flags a back-to-back (1 day rest)")


def test_get_team_rest_info_normal_rest_not_flagged(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [
                            {"gameId": "g1", "date": "2026-07-10T00:00Z", "opp_id": 19, "opp_name": "Chicago Sky"},
                        ])
    info = E.get_team_rest_info(20, "2026-07-14")   # last played 4 days ago -> not a back-to-back
    assert info["rest_days"] == 4
    assert info["is_back_to_back"] is False
    print("✓ get_team_rest_info doesn't flag a normal 4-day rest gap as a back-to-back")


def test_get_team_rest_info_unknown_when_no_recent_game(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [])
    info = E.get_team_rest_info(20, "2026-07-14")
    assert info == {"rest_days": None, "is_back_to_back": False, "last_game_date": None, "last_opp_name": None}
    print("✓ get_team_rest_info reports an honest unknown (not a fabricated 'well-rested' guess) when no recent game is found")


# ----------------------------------------------------------------- get_player_history_vs_opponent
def test_get_player_history_vs_opponent_filters_to_that_opponent_only(monkeypatch):
    E._response_cache.clear()
    # opp_id here is a STRING, exactly like the real JSON shape from get_team_recent_game_ids —
    # this is the exact type mismatch that was caught and fixed (comparing against an int param).
    games_info = [
        {"gameId": "g1", "date": "2026-06-01T00:00Z", "opp_id": "19", "opp_name": "Chicago Sky"},
        {"gameId": "g2", "date": "2026-05-15T00:00Z", "opp_id": "16", "opp_name": "Washington Mystics"},
        {"gameId": "g3", "date": "2026-05-01T00:00Z", "opp_id": "19", "opp_name": "Chicago Sky"},
    ]
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=82, days_back=45: games_info)
    boxscores = {
        "g1": {111: {"pts": 22.0, "reb": 5.0, "ast": 3.0, "fg3m": 2.0, "min": 30.0}},
        "g3": {111: {"pts": 18.0, "reb": 6.0, "ast": 4.0, "fg3m": 1.0, "min": 28.0}},
    }
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: boxscores.get(gid, {}))

    history = E.get_player_history_vs_opponent(111, team_id=20, opp_id=19, before_date="2026-07-14")
    assert len(history) == 2   # only g1 and g3 (vs Chicago Sky, opp_id 19) — not g2 (Mystics)
    assert history[0]["pts"] == 22.0 and history[0]["opp"] == "Chicago Sky"
    assert history[1]["pts"] == 18.0
    print("✓ get_player_history_vs_opponent correctly filters to one opponent, handling the "
          "string-vs-int opp_id type mismatch")


def test_get_player_history_vs_opponent_empty_when_teams_havent_met(monkeypatch):
    E._response_cache.clear()
    games_info = [{"gameId": "g1", "date": "2026-06-01T00:00Z", "opp_id": "16", "opp_name": "Washington Mystics"}]
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=82, days_back=45: games_info)
    history = E.get_player_history_vs_opponent(111, team_id=20, opp_id=19, before_date="2026-07-14")
    assert history == []


def test_get_player_history_vs_opponent_days_back_spans_season_start(monkeypatch):
    captured = {}

    def fake_get_team_recent_game_ids(team_id, before_date, n=82, days_back=45):
        captured["days_back"] = days_back
        return []

    monkeypatch.setattr(E, "get_team_recent_game_ids", fake_get_team_recent_game_ids)
    E.get_player_history_vs_opponent(111, team_id=20, opp_id=19, before_date="2026-07-14")
    # from SEASON_START (2026-04-01) to 2026-07-14 is ~104 days -> comfortably wider than the
    # 45-day "recent form" default, confirming this really does scan back to the season start.
    assert captured["days_back"] > 90
    print(f"✓ get_player_history_vs_opponent scans back to season start "
          f"(days_back={captured['days_back']}), not just the 45-day recent-form window")


# ----------------------------------------------------------------- get_player_season_games
def test_get_player_season_games_uses_wide_days_back(monkeypatch):
    captured = {}

    def fake_get_player_recent_games(player_id, last_n=10, team_id=None, before_date=None, days_back=45):
        captured["last_n"] = last_n
        captured["days_back"] = days_back
        return []

    monkeypatch.setattr(E, "get_player_recent_games", fake_get_player_recent_games)
    E.get_player_season_games(111, team_id=20, before_date="2026-07-14")
    assert captured["last_n"] == 82        # a full season's worth of games, not just 10
    assert captured["days_back"] > 90      # spans back to season start, not the 45-day recency window
    print(f"✓ get_player_season_games requests a season-wide window (days_back={captured['days_back']})")


def test_get_player_season_games_delegates_correctly(monkeypatch):
    season_log = [{"pts": 20.0, "reb": 5.0, "ast": 3.0, "fg3m": 2.0, "min": 30.0, "opp": "X", "date": "d"}] * 15
    monkeypatch.setattr(E, "get_player_recent_games",
                        lambda player_id, last_n=10, team_id=None, before_date=None, days_back=45: season_log)
    result = E.get_player_season_games(111, team_id=20, before_date="2026-07-14")
    assert result == season_log


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
