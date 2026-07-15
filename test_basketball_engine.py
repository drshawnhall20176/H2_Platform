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


def test_get_game_team_totals_falls_back_to_team_score_when_points_stat_missing():
    # Real finding from NBA verification: a live NBA sample had NO "points" entry anywhere in
    # statistics[] (only FG/3PT/FT/rebounds/assists/turnovers etc.) — team score can live as a
    # sibling "score" field on the team block itself instead of inside statistics[].
    fake_cdn = {"gamepackageJSON": {"boxscore": {"teams": [
        {"team": {"id": "5"}, "score": "112", "statistics": [
            {"name": "totalRebounds", "displayValue": "45"},
            {"name": "assists", "displayValue": "24"},
            {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "12-30"},
            # deliberately no "points" entry anywhere
        ]},
    ]}}}
    totals = BB.get_game_team_totals("g1", CDN_API, lambda url, params=None: fake_cdn)
    assert totals[5]["pts"] == 112.0   # recovered from team_block["score"], not silently 0.0
    print("✓ get_game_team_totals falls back to team_block['score'] when 'points' isn't in statistics[]")


def test_get_game_team_totals_diagnostic_fires_on_partial_failure():
    # A PARTIAL failure (only one field wrong) must still trigger the diagnostic dump, not just a
    # total failure — this was a real gap: the old condition only fired when ALL FOUR core fields
    # were zero simultaneously, so one silently-wrong field name (like "points" being absent)
    # produced a wrong number with zero diagnostic signal.
    calls = []
    fake_cdn = {"gamepackageJSON": {"boxscore": {"teams": [
        {"team": {"id": "5"}, "statistics": [   # no "score" fallback here either -> pts stays 0.0
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
