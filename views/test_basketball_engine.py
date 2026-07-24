"""
test_basketball_engine.py — offline unit tests for basketball_engine.py, the shared
league-agnostic layer (WNBA today, NBA whenever that build starts).

These tests call the module directly with fake `fetch`/`diag` callables (dependency injection,
not monkeypatch) — this module owns no HTTP client or module-level cache of its own, by design
(see the module docstring for why), so there's nothing to monkeypatch; a fake fetch function is
simpler and more direct than patching would be.

    python test_basketball_engine.py     # or: pytest test_basketball_engine.py
"""

import basketball_engine as BB

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
CDN_API = "https://cdn.espn.com/core/wnba/boxscore"


# ----------------------------------------------------------------- parse_stat_value
def test_parse_stat_value_plain_number():
    assert BB.parse_stat_value("32") == 32.0


def test_parse_stat_value_combo_left_is_makes():
    assert BB.parse_stat_value("12-24") == 12.0


def test_parse_stat_value_combo_right_is_attempts():
    assert BB.parse_stat_value("12-24", side="right") == 24.0


def test_parse_stat_value_handles_junk():
    assert BB.parse_stat_value(None) == 0.0
    assert BB.parse_stat_value("DNP") == 0.0
    assert BB.parse_stat_value("") == 0.0


# ----------------------------------------------------------------- find_team_stat
def test_find_team_stat_exact_then_prefix_fallback():
    stats = {"threePointFieldGoalsMade-threePointFieldGoalsAttempted": "9-25"}
    assert BB.find_team_stat(stats, "threePointFieldGoalsMade") == 9.0   # prefix fallback
    assert BB.find_team_stat(stats, "threePointFieldGoalsMade-threePointFieldGoalsAttempted") == 9.0


def test_find_team_stat_side_right():
    stats = {"fieldGoalsMade-fieldGoalsAttempted": "33-82"}
    assert BB.find_team_stat(stats, "fieldGoalsMade-fieldGoalsAttempted", side="right") == 82.0


def test_find_team_stat_no_match_returns_zero():
    assert BB.find_team_stat({"points": "88"}, "totallyMadeUpField") == 0.0


# ----------------------------------------------------------------- get_team_recent_game_ids
def test_get_team_recent_game_ids_filters_to_completed_games_for_that_team():
    fake_events = {"events": [{
        "id": "g1", "date": "2026-07-10T00:00Z",
        "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"team": {"id": "20"}},
            {"team": {"id": "19", "displayName": "Chicago Sky"}},
        ]}],
    }]}

    def fake_fetch(url, params=None):
        return fake_events

    games = BB.get_team_recent_game_ids(20, "2026-07-14", SITE_API, fake_fetch, n=10)
    assert len(games) == 1
    assert games[0]["gameId"] == "g1"
    assert games[0]["opp_id"] == "19"
    print("✓ get_team_recent_game_ids filters to completed games where the team is a competitor")


def test_get_team_recent_game_ids_excludes_incomplete_games():
    fake_events = {"events": [{
        "id": "g1", "date": "2026-07-13T00:00Z",
        "status": {"type": {"completed": False}},   # scheduled, not yet played
        "competitions": [{"competitors": [{"team": {"id": "20"}}, {"team": {"id": "19"}}]}],
    }]}
    games = BB.get_team_recent_game_ids(20, "2026-07-14", SITE_API,
                                        lambda url, params=None: fake_events, n=10)
    assert games == []


def test_get_team_recent_game_ids_empty_on_fetch_failure():
    games = BB.get_team_recent_game_ids(20, "2026-07-14", SITE_API,
                                        lambda url, params=None: None, n=10)
    assert games == []


def test_get_team_recent_game_ids_extra_params_merged_into_request():
    # Added for NCAAMB: the scoreboard endpoint truncates by default for a 350+-team league,
    # confirmed live to need groups=50 to return the full slate. extra_params is how a caller
    # (NCAAMB's engine) opts into that without changing WNBA/NBA's existing request shape at all.
    captured = {}

    def fake_fetch(url, params=None):
        captured["params"] = params
        return {"events": []}

    BB.get_team_recent_game_ids(20, "2026-07-14", SITE_API, fake_fetch, n=10,
                                extra_params={"groups": 50})
    assert captured["params"]["groups"] == 50
    assert captured["params"]["limit"] == 500   # the existing param is still present, not replaced
    print("✓ get_team_recent_game_ids merges extra_params into the scoreboard request without dropping existing params")


def test_get_team_recent_game_ids_extra_params_none_by_default():
    # Confirms omitting extra_params (WNBA/NBA's existing call pattern) produces the exact same
    # request shape as before this parameter was added — a real regression guard, not just a
    # smoke test, since this function is shared and already live for two sports.
    captured = {}

    def fake_fetch(url, params=None):
        captured["params"] = params
        return {"events": []}

    BB.get_team_recent_game_ids(20, "2026-07-14", SITE_API, fake_fetch, n=10)
    assert "groups" not in captured["params"]
    assert captured["params"] == {"dates": captured["params"]["dates"], "limit": 500}


# ----------------------------------------------------------------- get_game_team_totals
def test_get_game_team_totals_estimates_possessions():
    # Poss = FGA - OREB + TOV + 0.44*FTA = 82 - 10 + 15 + 0.44*20 = 95.8
    fake_cdn = {"gamepackageJSON": {"boxscore": {"teams": [
        {"team": {"id": "20"}, "statistics": [
            {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "33-82"},
            {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "14-20"},
            {"name": "offensiveRebounds", "displayValue": "10"},
            {"name": "totalTurnovers", "displayValue": "15"},
            {"name": "totalRebounds", "displayValue": "36"},
            {"name": "assists", "displayValue": "20"},
            {"name": "points", "displayValue": "88"},
        ]},
    ]}}}
    totals = BB.get_game_team_totals("g1", CDN_API, lambda url, params=None: fake_cdn)
    assert abs(totals[20]["poss"] - 95.8) < 1e-6
    assert totals[20]["pts"] == 88.0
    print("✓ get_game_team_totals estimates possessions from FGA/OREB/TOV/FTA")


def test_get_game_team_totals_empty_on_fetch_failure():
    assert BB.get_game_team_totals("g1", CDN_API, lambda url, params=None: None) == {}


def test_get_game_team_totals_falls_back_to_header_score_when_points_stat_missing():
    # Real finding from NBA verification (confirmed live, twice — a 2016 game and a real 2026
    # Nets/Clippers game, both pasted back during verification): "points" does NOT exist anywhere
    # in boxscore.teams[].statistics[]. The team's score instead lives in a completely different
    # part of the response: gamepackageJSON.header.competitions[0].competitors[], matched by
    # team id — NOT a sibling "score" field on the boxscore.teams[] block itself (an earlier,
    # wrong version of this fix assumed that; this fixture uses the real, confirmed location).
    fake_cdn = {"gamepackageJSON": {
        "header": {"competitions": [{"competitors": [
            {"id": "5", "score": "112"}, {"id": "9", "score": "108"},
        ]}]},
        "boxscore": {"teams": [
            {"team": {"id": "5"}, "statistics": [
                {"name": "totalRebounds", "displayValue": "45"},
                {"name": "assists", "displayValue": "24"},
                {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "12-30"},
                # deliberately no "points" entry anywhere, matching the real confirmed shape
            ]},
        ]},
    }}
    totals = BB.get_game_team_totals("g1", CDN_API, lambda url, params=None: fake_cdn)
    assert totals[5]["pts"] == 112.0   # recovered from header.competitions[0].competitors[], not silently 0.0
    print("✓ get_game_team_totals falls back to the real header-derived score, not team_block['score']")


def test_get_game_team_totals_real_confirmed_live_shape():
    # Built directly from a real, live CDN response pasted back during verification: Nets @
    # Clippers, Jan 25 2026 (gameId 401810511). Team-level statistics[] trimmed to the fields
    # get_game_team_totals actually reads; "points" genuinely absent, exactly as confirmed live.
    clippers_stats = [
        {"displayValue": "44-78", "name": "fieldGoalsMade-fieldGoalsAttempted", "label": "FG"},
        {"displayValue": "12-25", "name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "label": "3PT"},
        {"displayValue": "26-29", "name": "freeThrowsMade-freeThrowsAttempted", "label": "FT"},
        {"displayValue": "51", "name": "totalRebounds", "label": "Rebounds"},
        {"displayValue": "7", "name": "offensiveRebounds", "label": "Offensive Rebounds"},
        {"displayValue": "20", "name": "assists", "label": "Assists"},
        {"displayValue": "19", "name": "totalTurnovers", "label": "Total Turnovers"},
    ]
    fake_cdn = {"gamepackageJSON": {
        "header": {"competitions": [{"competitors": [
            {"id": "12", "score": "126"}, {"id": "17", "score": "89"},
        ]}]},
        "boxscore": {"teams": [
            {"homeAway": "away", "team": {"id": "17"}, "statistics": []},   # Nets: stats trimmed for brevity
            {"homeAway": "home", "team": {"id": "12"}, "statistics": clippers_stats},   # Clippers
        ]},
    }}
    totals = BB.get_game_team_totals("g1", CDN_API, lambda url, params=None: fake_cdn)
    assert totals[12]["pts"] == 126.0                     # recovered via header fallback
    assert totals[12]["reb"] == 51.0
    assert totals[12]["fg3m"] == 12.0
    # Poss = FGA - OREB + TOV + 0.44*FTA = 78 - 7 + 19 + 0.44*29 = 102.76
    assert abs(totals[12]["poss"] - 102.76) < 1e-6
    print("✓ get_game_team_totals correctly parses the real, confirmed-live Nets/Clippers CDN response")


def test_get_game_team_totals_diagnostic_fires_on_partial_failure():
    # A PARTIAL failure (only one field wrong) must still trigger the diagnostic dump, not just a
    # total failure — this was a real gap: the old condition only fired when ALL FOUR core fields
    # were zero simultaneously, so one silently-wrong field name (like "points" being absent)
    # produced a wrong number with zero diagnostic signal. No header/score data here either, so
    # the pts fallback also comes up empty — pts genuinely stays 0.0, which is what should trip
    # the diagnostic dump.
    calls = []
    fake_cdn = {"gamepackageJSON": {"boxscore": {"teams": [
        {"team": {"id": "5"}, "statistics": [
            {"name": "totalRebounds", "displayValue": "45"},
            {"name": "assists", "displayValue": "24"},
            {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "12-30"},
        ]},
    ]}}}
    BB.get_game_team_totals("g1", CDN_API, lambda url, params=None: fake_cdn, diag=calls.append)
    assert any("PARTIAL failure" in c for c in calls)
    assert any("pts" in c for c in calls if "PARTIAL failure" in c)
    print("✓ get_game_team_totals's diagnostic dump now fires on a partial (not just total) failure")


# ----------------------------------------------------------------- get_team_recent_allowed_stats
def test_get_team_recent_allowed_stats_averages_opponent_totals():
    events = {"events": [
        {"id": "g1", "date": "2026-07-10T00:00Z", "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [{"team": {"id": "20"}},
                                          {"team": {"id": "19", "displayName": "Chicago Sky"}}]}]},
        {"id": "g2", "date": "2026-07-05T00:00Z", "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [{"team": {"id": "20"}},
                                          {"team": {"id": "16", "displayName": "Washington Mystics"}}]}]},
    ]}
    boxscores = {
        "g1": {"gamepackageJSON": {"boxscore": {"teams": [
            {"team": {"id": "19"}, "statistics": [{"name": "points", "displayValue": "90"},
                                                  {"name": "totalRebounds", "displayValue": "35"},
                                                  {"name": "assists", "displayValue": "20"},
                                                  {"name": "threePointFieldGoalsMade", "displayValue": "8"}]},
        ]}}},
        "g2": {"gamepackageJSON": {"boxscore": {"teams": [
            {"team": {"id": "16"}, "statistics": [{"name": "points", "displayValue": "70"},
                                                  {"name": "totalRebounds", "displayValue": "30"},
                                                  {"name": "assists", "displayValue": "16"},
                                                  {"name": "threePointFieldGoalsMade", "displayValue": "6"}]},
        ]}}},
    }

    def fake_fetch(url, params=None):
        if url == SITE_API + "/scoreboard":
            return events
        gid = (params or {}).get("gameId")
        return boxscores.get(gid)

    allowed = BB.get_team_recent_allowed_stats(20, "2026-07-14", SITE_API, CDN_API, fake_fetch, n=10)
    assert allowed["pts"] == 80.0   # avg(90, 70)
    assert allowed["reb"] == 32.5   # avg(35, 30)
    print("✓ get_team_recent_allowed_stats correctly averages the OPPONENT's totals across games")


# ----------------------------------------------------------------- get_team_rest_info
def test_get_team_rest_info_flags_back_to_back():
    events = {"events": [{
        "id": "g1", "date": "2026-07-13T00:00Z", "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [{"team": {"id": "20"}},
                                          {"team": {"id": "19", "displayName": "Chicago Sky"}}]}],
    }]}
    info = BB.get_team_rest_info(20, "2026-07-14", SITE_API, lambda url, params=None: events)
    assert info["rest_days"] == 1
    assert info["is_back_to_back"] is True
    print("✓ get_team_rest_info correctly flags a back-to-back")


def test_get_team_rest_info_unknown_when_no_recent_game():
    info = BB.get_team_rest_info(20, "2026-07-14", SITE_API, lambda url, params=None: {"events": []})
    assert info == {"rest_days": None, "is_back_to_back": False, "last_game_date": None, "last_opp_name": None}
    print("✓ get_team_rest_info reports an honest unknown when no recent game is found")


# ----------------------------------------------------------------- get_team_injuries
def test_get_team_injuries_parses_confirmed_live_shape():
    fake_response = {"injuries": [
        {"id": "-50368", "status": "Out", "shortComment": "Signed a two-way contract.",
         "athlete": {"displayName": "Keshon Gilbert", "position": {"abbreviation": "G"}},
         "details": {"returnDate": "2026-07-02"}},
    ]}
    injuries = BB.get_team_injuries("ATL", SITE_API, lambda url, params=None: fake_response)
    assert injuries == [{"player": "Keshon Gilbert", "status": "Out", "position": "G",
                        "return_date": "2026-07-02", "comment": "Signed a two-way contract."}]
    print("✓ get_team_injuries parses the confirmed-live ESPN injuries shape correctly")


def test_get_team_injuries_empty_team_abbr():
    assert BB.get_team_injuries("", SITE_API, lambda url, params=None: {}) == []


def test_get_team_injuries_healthy_team_returns_empty_list():
    assert BB.get_team_injuries("SEA", SITE_API, lambda url, params=None: {"injuries": []}) == []


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
