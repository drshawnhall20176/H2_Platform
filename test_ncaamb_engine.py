"""
test_ncaamb_engine.py — offline unit tests for ncaamb_engine's pure logic.

No network required — get_schedule/get_team_roster/get_player_recent_games (the actual live ESPN
API calls) are monkeypatched out, same convention as test_nba_engine.py. Functions that are thin
wrappers around basketball_engine.py get a lighter smoke test here confirming the wiring; the
underlying logic itself is already covered directly in test_basketball_engine.py. Additional
coverage here (not present in WNBA's/NBA's test files) locks in the one genuinely new NCAAMB-
specific quirk: the scoreboard endpoint's Division-I truncation and its groups=50 fix.

    python test_ncaamb_engine.py     # or: pytest test_ncaamb_engine.py
"""

import ncaamb_engine as E


def _log(pts, reb, ast, fg3m, minutes, opp="Duke Blue Devils", date="2027-01-14T00:00Z"):
    return {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3m, "min": minutes, "opp": opp, "date": date}


# ----------------------------------------------------------------- basic module wiring
def test_site_api_and_cdn_api_use_mens_college_basketball_slug():
    assert E.SITE_API == "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
    assert E.CDN_API == "https://cdn.espn.com/core/mens-college-basketball/boxscore"


def test_parse_stat_value_and_find_team_stat_are_aliased_to_basketball_engine():
    import basketball_engine as BB
    assert E._parse_stat_value is BB.parse_stat_value
    assert E._find_team_stat is BB.find_team_stat


# ----------------------------------------------------------------- Division-I truncation fix
def test_get_schedule_includes_groups_50(monkeypatch):
    # THE real, confirmed-live quirk this build exists to handle: without groups=50, ESPN's
    # scoreboard endpoint silently truncates Division I's 350+ teams to a partial slate.
    captured = {}

    def fake_get_json(url, params=None):
        captured["params"] = params
        return {"events": []}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    E.get_schedule("2027-01-14")
    assert captured["params"]["groups"] == 50
    assert captured["params"]["limit"] == 500
    print("✓ get_schedule includes groups=50, avoiding the confirmed Division-I truncation bug")


def test_get_team_recent_game_ids_passes_groups_50_through(monkeypatch):
    captured = {}

    def fake_get_team_recent_game_ids(team_id, before_date, site_api, fetch, diag, **kwargs):
        captured["extra_params"] = kwargs.get("extra_params")
        return []

    import basketball_engine as BB
    monkeypatch.setattr(BB, "get_team_recent_game_ids", fake_get_team_recent_game_ids)
    E.get_team_recent_game_ids(2, "2027-01-14")
    assert captured["extra_params"] == {"groups": 50}
    print("✓ get_team_recent_game_ids passes groups=50 through to the shared implementation via extra_params")


# ----------------------------------------------------------------- get_schedule
def test_get_schedule_parses_espn_scoreboard_shape(monkeypatch):
    fake_response = {
        "events": [
            {
                "id": "401900001",
                "date": "2027-01-14T00:00Z",
                "competitions": [{
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "150", "displayName": "Duke Blue Devils", "abbreviation": "DUKE"}},
                        {"homeAway": "away", "team": {"id": "41", "displayName": "UConn Huskies", "abbreviation": "UCONN"}},
                    ]
                }],
            },
            {"id": "bad_event", "competitions": []},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)

    games = E.get_schedule("2027-01-14")
    assert len(games) == 1
    g = games[0]
    assert g["home_id"] == 150 and g["home_name"] == "Duke Blue Devils" and g["home_abbr"] == "DUKE"
    assert g["away_id"] == 41 and g["away_name"] == "UConn Huskies" and g["away_abbr"] == "UCONN"
    print("✓ get_schedule parses ESPN's NCAAMB scoreboard shape and skips malformed events")


def test_get_schedule_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_schedule("2027-01-14") == []


# ----------------------------------------------------------------- team_abbrs_from_meta
def test_team_abbrs_from_meta_derives_from_build_slate_meta():
    meta = [{"label": "UConn @ Duke", "home_id": 150, "home_abbr": "DUKE", "away_id": 41, "away_abbr": "UCONN"}]
    assert E.team_abbrs_from_meta(meta) == {150: "DUKE", 41: "UCONN"}


# ----------------------------------------------------------------- get_team_roster
def test_get_team_roster_handles_grouped_shape(monkeypatch):
    fake_response = {"athletes": [
        {"position": "Guards", "items": [{"id": "5001", "displayName": "Test Guard"}]},
        {"position": "Forwards", "items": [{"id": "5002", "displayName": "Test Forward"}]},
    ]}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)
    roster = E.get_team_roster(150)
    assert {p["name"] for p in roster} == {"Test Guard", "Test Forward"}
    print("✓ get_team_roster correctly flattens the grouped-by-position shape")


def test_get_team_roster_handles_flat_shape(monkeypatch):
    fake_response = {"athletes": [{"id": "5001", "displayName": "Test Guard"}]}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)
    roster = E.get_team_roster(150)
    assert roster == [{"id": 5001, "name": "Test Guard"}]
    print("✓ get_team_roster correctly handles a flat (non-grouped) athletes list")


def test_get_team_roster_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_roster(150) == []


# ----------------------------------------------------------------- get_game_boxscore
def test_get_game_boxscore_parses_cdn_shape(monkeypatch):
    # NOT independently confirmed live for NCAAMB specifically (see module docstring) — this
    # tests the code parses the shape it's WRITTEN against (the same shape confirmed live for
    # both WNBA and NBA), not a claim that NCAAMB's real response has been verified to match.
    E._response_cache.clear()
    fake_cdn = {"gamepackageJSON": {"boxscore": {"players": [
        {"statistics": [{"names": ["MIN", "PTS", "REB", "AST", "3PT"],
                        "athletes": [{"athlete": {"id": "5001"}, "stats": ["30", "18", "6", "4", "2-5"],
                                     "didNotPlay": False}]}]},
    ]}}}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    box = E.get_game_boxscore("g1")
    assert box[5001] == {"pts": 18.0, "reb": 6.0, "ast": 4.0, "fg3m": 2.0, "min": 30.0}
    print("✓ get_game_boxscore correctly parses the CDN player-stats shape (as coded against, not yet live-confirmed for NCAAMB)")


def test_get_game_boxscore_real_confirmed_live_shape(monkeypatch):
    # CONFIRMED LIVE, not assumed — Shawn fetched the actual raw CDN JSON directly
    # (cdn.espn.com/core/mens-college-basketball/boxscore?xhr=1&gameId=401856577) and pasted the
    # literal response back, the same bar NBA's build cleared. This is the real names/keys/
    # athletes/stats array structure, not a guess: UConn 73, Duke 72, an NCAA Tournament Elite
    # Eight game (March 29 2026) where UConn upset the #1 overall seed on a buzzer-beater. Two
    # real players' real lines, both verified correct with zero code changes needed:
    #   Alex Karaban:    38 MIN,  5 PTS, 2-10 FG, 1-6 3PT, 0-0 FT, 3 REB, 3 AST
    #   Tarris Reed Jr.: 32 MIN, 26 PTS, 10-16 FG, 0-0 3PT, 6-9 FT, 9 REB, 3 AST
    E._response_cache.clear()
    names = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF"]
    fake_cdn = {"gamepackageJSON": {"boxscore": {"players": [
        {"team": {"id": "41"}, "statistics": [{"names": names, "athletes": [
            {"athlete": {"id": "4917149"}, "didNotPlay": False,
            "stats": ["38", "5", "2-10", "1-6", "0-0", "3", "3", "0", "0", "2", "2", "1", "2"]},
            {"athlete": {"id": "5105809"}, "didNotPlay": False,
            "stats": ["32", "26", "10-16", "0-0", "6-9", "9", "3", "2", "2", "4", "4", "5", "3"]},
        ]}]},
    ]}}}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    box = E.get_game_boxscore("401856577")
    assert box[4917149] == {"pts": 5.0, "reb": 3.0, "ast": 3.0, "fg3m": 1.0, "min": 38.0}     # Alex Karaban
    assert box[5105809] == {"pts": 26.0, "reb": 9.0, "ast": 3.0, "fg3m": 0.0, "min": 32.0}    # Tarris Reed Jr.
    print("✓ get_game_boxscore correctly parses the real, confirmed-live UConn/Duke CDN response — zero bugs found")


def test_get_game_team_totals_real_confirmed_live_shape(monkeypatch):
    # Same real UConn @ Duke game, team-level side — also confirmed live: "points" is genuinely
    # absent from statistics[] here too (25 fields, same as WNBA/NBA), and the header-fallback fix
    # built during NBA's verification works correctly for NCAAMB with zero changes needed. Real
    # final score 73-72 recovered exactly via header.competitions[0].competitors[].score.
    E._response_cache.clear()
    fake_cdn = {"gamepackageJSON": {
        "header": {"competitions": [{"competitors": [
            {"id": "150", "homeAway": "home", "score": "72"},
            {"id": "41", "homeAway": "away", "score": "73"},
        ]}]},
        "boxscore": {"teams": [
            {"team": {"id": "41"}, "statistics": [
                {"displayValue": "28-64", "name": "fieldGoalsMade-fieldGoalsAttempted", "label": "FG"},
                {"displayValue": "5-23", "name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "label": "3PT"},
                {"displayValue": "12-17", "name": "freeThrowsMade-freeThrowsAttempted", "label": "FT"},
                {"displayValue": "28", "name": "totalRebounds", "label": "Rebounds"},
                {"displayValue": "13", "name": "offensiveRebounds", "label": "Offensive Rebounds"},
                {"displayValue": "16", "name": "assists", "label": "Assists"},
                {"displayValue": "5", "name": "totalTurnovers", "label": "Total Turnovers"},
                # deliberately no "points" entry — confirmed genuinely absent in the real response
            ]},
        ]},
    }}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    totals = E.get_game_team_totals("401856577")
    assert totals[41]["pts"] == 73.0     # recovered via header fallback — matches the real final score
    assert totals[41]["reb"] == 28.0
    assert totals[41]["ast"] == 16.0
    assert totals[41]["fg3m"] == 5.0
    print("✓ get_game_team_totals correctly parses the real, confirmed-live UConn/Duke team totals — zero bugs found")


def test_get_game_boxscore_skips_did_not_play(monkeypatch):
    E._response_cache.clear()
    fake_cdn = {"gamepackageJSON": {"boxscore": {"players": [
        {"statistics": [{"names": ["MIN", "PTS"],
                        "athletes": [{"athlete": {"id": "5001"}, "stats": ["0", "0"], "didNotPlay": True}]}]},
    ]}}}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    assert E.get_game_boxscore("g1") == {}


def test_get_game_boxscore_empty_on_fetch_failure(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_game_boxscore("g1") == {}


# ----------------------------------------------------------------- wrapper wiring (thin delegation)
def test_get_game_team_totals_wires_ncaamb_cdn_api(monkeypatch):
    captured = {}

    def fake_get_game_team_totals(game_id, cdn_api, fetch, diag, **kwargs):
        captured["cdn_api"] = cdn_api
        return {}

    import basketball_engine as BB
    monkeypatch.setattr(BB, "get_game_team_totals", fake_get_game_team_totals)
    E.get_game_team_totals("g1")
    assert captured["cdn_api"] == E.CDN_API
    print("✓ get_game_team_totals passes NCAAMB's own CDN_API into the shared implementation")


def test_get_team_injuries_wires_ncaamb_site_api(monkeypatch):
    captured = {}

    def fake_get_team_injuries(team_abbr, site_api, fetch, diag=None, **kwargs):
        captured["site_api"] = site_api
        return []

    import basketball_engine as BB
    monkeypatch.setattr(BB, "get_team_injuries", fake_get_team_injuries)
    E.get_team_injuries("DUKE")
    assert captured["site_api"] == E.SITE_API
    print("✓ get_team_injuries passes NCAAMB's own SITE_API into the shared implementation")


# ----------------------------------------------------------------- get_team_recent_allowed_stats
def test_get_team_recent_allowed_stats_averages_opponent_totals(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=10, days_back=45: [
                            {"gameId": "g1", "date": "2027-01-10T00:00Z", "opp_id": "41", "opp_name": "UConn Huskies"},
                            {"gameId": "g2", "date": "2027-01-05T00:00Z", "opp_id": "99", "opp_name": "Villanova Wildcats"},
                        ])
    game_totals = {
        "g1": {41: {"pts": 78.0, "reb": 34.0, "ast": 16.0, "fg3m": 8.0, "poss": 68.0}},
        "g2": {99: {"pts": 70.0, "reb": 30.0, "ast": 14.0, "fg3m": 6.0, "poss": 64.0}},
    }
    monkeypatch.setattr(E, "get_game_team_totals", lambda gid: game_totals.get(gid, {}))
    allowed = E.get_team_recent_allowed_stats(150, "2027-01-14", n=10)
    assert allowed["pts"] == 74.0   # avg(78, 70)
    assert allowed["poss"] == 66.0   # avg(68, 64)
    print("✓ get_team_recent_allowed_stats correctly averages the OPPONENT's totals across games")


# ----------------------------------------------------------------- get_team_rest_info
def test_get_team_rest_info_flags_back_to_back(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [
                            {"gameId": "g1", "date": "2027-01-13T00:00Z", "opp_id": "41", "opp_name": "UConn Huskies"},
                        ])
    info = E.get_team_rest_info(150, "2027-01-14")
    assert info["rest_days"] == 1 and info["is_back_to_back"] is True
    print("✓ get_team_rest_info correctly flags a back-to-back")


def test_get_team_rest_info_unknown_when_no_recent_game(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [])
    info = E.get_team_rest_info(150, "2027-01-14")
    assert info == {"rest_days": None, "is_back_to_back": False, "last_game_date": None, "last_opp_name": None}


# ----------------------------------------------------------------- pure logic
def test_avg_minutes():
    log = [_log(20, 5, 3, 2, 30), _log(18, 4, 4, 1, 34)]
    assert E.avg_minutes(log) == 32.0


def test_player_row_filters_below_rotation_bar():
    player = {"id": 5001, "name": "Test Guard"}
    low_minutes_log = [_log(4, 1, 1, 0, 6)]
    assert E.player_row(player, "Duke", "UConn", "UConn @ Duke", "2027-01-14T00:00Z",
                        low_minutes_log, min_avg_minutes=12.0) is None
    print("✓ player_row filters out players below the rotation-minutes bar")


def test_player_row_builds_correctly_for_a_rotation_player():
    player = {"id": 5001, "name": "Test Guard"}
    log = [_log(18, 6, 4, 2, 30), _log(20, 5, 5, 3, 32)]
    row = E.player_row(player, "Duke", "UConn", "UConn @ Duke", "2027-01-14T00:00Z",
                       log, min_avg_minutes=12.0, opp_id=41, team_id=150)
    assert row["Player"] == "Test Guard"
    assert row["PTS"] == 19.0
    assert row["_opp_id"] == 41 and row["_team_id"] == 150
    print("✓ player_row builds a correct flat row for a rotation player")


# ----------------------------------------------------------------- season-start bound
def test_season_start_is_confirmed_november_1_2026():
    # Genuinely confirmed live during scoping (NCAA's own published 2026-27 calendar), not a
    # placeholder — unlike NBA's build, which happened during the NBA's off-season with no
    # announced schedule to confirm against yet.
    assert E.SEASON_START == "2026-11-01"


def test_season_start_bounds_days_since_start():
    days = E._days_since_season_start("2026-12-01")
    assert days == (30 + 1)   # Dec 1 minus SEASON_START (2026-11-01) = 30 days, +1


def test_days_since_season_start_falls_back_on_bad_date():
    assert E._days_since_season_start("not-a-date") == 200


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
