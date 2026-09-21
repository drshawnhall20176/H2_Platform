"""
test_nba_engine.py — offline unit tests for nba_engine's pure logic.

No network required — get_schedule/get_team_roster/get_player_recent_games (the actual live ESPN
API calls) are monkeypatched out, same convention as test_wnba_engine.py. Functions that are thin
wrappers around basketball_engine.py (get_team_recent_game_ids, get_game_team_totals,
get_team_injuries) get a lighter smoke test here confirming the wiring (right URL, right cache/
diag objects) — the underlying logic itself is already covered directly in
test_basketball_engine.py, so it isn't re-tested exhaustively per sport.

    python test_nba_engine.py     # or: pytest test_nba_engine.py
"""

import pytest
from unittest.mock import patch

import nba_engine as E
import nba_stats_engine as NS


@pytest.fixture(autouse=True)
def _no_real_stats_nba_com_fallback(monkeypatch):
    """get_schedule now falls back to stats.nba.com when ESPN returns nothing. Default that
    fallback to an empty result for every test in this file so no test can ever reach the real
    network through it; tests that exercise the fallback override this themselves."""
    monkeypatch.setattr(NS, "get_schedule", lambda date_str, league_id: [])


def _log(pts, reb, ast, fg3m, minutes, opp="Boston Celtics", date="2026-01-14T00:00Z"):
    return {"pts": pts, "reb": reb, "ast": ast, "fg3m": fg3m, "min": minutes, "opp": opp, "date": date}


# ----------------------------------------------------------------- _get_json: real TLS fingerprint fix
def test_get_json_uses_real_browser_impersonation(monkeypatch):
    # Same real, confirmed fix as wnba_engine.py's own -- already proven working there before
    # being applied here. Confirms _get_json genuinely passes impersonate="chrome" to the real
    # curl_cffi call, not just that the import was swapped.
    captured = {}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"events": []}

    def fake_get(url, params=None, timeout=None, impersonate=None):
        captured["impersonate"] = impersonate
        return _FakeResp()

    monkeypatch.setattr(E.requests, "get", fake_get)
    result = E._get_json("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
                         {"dates": "20260805"})
    assert result == {"events": []}
    assert captured["impersonate"] == "chrome"
    print("✓ _get_json genuinely uses real browser (Chrome) TLS impersonation, the confirmed fix already proven on WNBA")


# ----------------------------------------------------------------- basic module wiring
def test_site_api_and_cdn_api_use_nba_league_slug():
    assert E.SITE_API == "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    assert E.CDN_API == "https://cdn.espn.com/core/nba/boxscore"


def test_parse_stat_value_and_find_team_stat_are_aliased_to_basketball_engine():
    import basketball_engine as BB
    assert E._parse_stat_value is BB.parse_stat_value
    assert E._find_team_stat is BB.find_team_stat


# ----------------------------------------------------------------- get_schedule
def test_get_schedule_parses_espn_scoreboard_shape(monkeypatch):
    fake_response = {
        "events": [
            {
                "id": "401810001",
                "date": "2026-01-14T23:00Z",   # 6 PM Eastern on the requested date
                "competitions": [{
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"}},
                        {"homeAway": "away", "team": {"id": "17", "displayName": "Milwaukee Bucks", "abbreviation": "MIL"}},
                    ]
                }],
            },
            {"id": "bad_event", "competitions": []},
        ]
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)

    games = E.get_schedule("2026-01-14")
    assert len(games) == 1
    g = games[0]
    assert g["home_id"] == 2 and g["home_name"] == "Boston Celtics" and g["home_abbr"] == "BOS"
    assert g["away_id"] == 17 and g["away_name"] == "Milwaukee Bucks" and g["away_abbr"] == "MIL"
    print("✓ get_schedule parses ESPN's NBA scoreboard shape and skips malformed events")


def test_get_schedule_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_schedule("2026-01-14") == []


def test_get_schedule_makes_three_real_safe_single_date_queries_not_a_range(monkeypatch):
    # A SECOND, REAL, CONFIRMED FIX: the first attempt (a single dates=START-END range query)
    # was confirmed directly from a real production log to return a genuine 403 Forbidden on
    # every real request. Reverted to three separate real single-date queries -- the exact same
    # dates=YYYYMMDD format that's always worked.
    calls = []

    def fake_get_json(url, params=None):
        calls.append(params)
        return {"events": []}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    E.get_schedule("2026-01-14")
    assert calls == [{"dates": "20260113"}, {"dates": "20260114"}, {"dates": "20260115"}], (
        f"expected three real, individually-safe single-date queries, got {calls}")
    print("✓ get_schedule makes three real, individually-safe single-date queries, never the real 403-triggering range format")


def test_get_schedule_three_queries_correctly_handle_a_real_month_boundary(monkeypatch):
    calls = []

    def fake_get_json(url, params=None):
        calls.append(params)
        return {"events": []}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    E.get_schedule("2026-01-31")
    assert calls == [{"dates": "20260130"}, {"dates": "20260131"}, {"dates": "20260201"}]
    print("✓ get_schedule's three real single-date queries correctly roll across a real month boundary")


def test_get_schedule_dedupes_the_same_real_event_across_multiple_queries(monkeypatch):
    shared_event = {
        "id": "999", "date": "2026-01-14T23:00Z",
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1", "displayName": "Team A", "abbreviation": "A"}},
            {"homeAway": "away", "team": {"id": "2", "displayName": "Team B", "abbreviation": "B"}},
        ], "status": {"type": {}}}],
    }

    def fake_get_json(url, params=None):
        if params["dates"] in ("20260113", "20260114"):
            return {"events": [shared_event]}
        return {"events": []}

    monkeypatch.setattr(E, "_get_json", fake_get_json)
    games = E.get_schedule("2026-01-14")
    assert len(games) == 1, f"expected the real shared event deduped to exactly 1, got {len(games)}"
    print("✓ get_schedule correctly dedupes the same real event id when it appears in more than one of the three real queries")


# ----------------------------------------------------------------- get_schedule: stats.nba.com fallback
_FALLBACK_GAME = {"gameId": "1", "game_date": "2026-10-22", "home_id": 1, "away_id": 2,
                  "home_name": "Team A", "away_name": "Team B", "home_abbr": "A",
                  "away_abbr": "B", "home_logo": None, "away_logo": None,
                  "status_state": None, "status_detail": "7:30 pm ET"}


def _event(eid, date_utc, home="Team A", away="Team B"):
    return {"id": eid, "date": date_utc, "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"id": "1", "displayName": home, "abbreviation": "A"}},
        {"homeAway": "away", "team": {"id": "2", "displayName": away, "abbreviation": "B"}},
    ], "status": {"type": {}}}]}


def test_get_schedule_falls_back_to_stats_nba_com_when_espn_returns_nothing(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": []})
    calls = []
    monkeypatch.setattr(NS, "get_schedule", lambda d, lid: calls.append((d, lid)) or [_FALLBACK_GAME])
    assert E.get_schedule("2026-10-22") == [_FALLBACK_GAME]
    assert calls == [("2026-10-22", NS.LEAGUE_ID_NBA)], f"fallback must use the NBA league id, got {calls}"


def test_get_schedule_falls_back_when_espn_fails_outright_not_just_when_empty(monkeypatch):
    # A hard ESPN failure (all three queries return None, e.g. a real 403) used to hit an early
    # `return []` -- the exact production bug fixed on WNBA -- and must reach the fallback too.
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    monkeypatch.setattr(NS, "get_schedule", lambda d, lid: [_FALLBACK_GAME])
    assert E.get_schedule("2026-10-22") == [_FALLBACK_GAME]


def test_get_schedule_never_calls_the_fallback_when_espn_has_real_games(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": [_event("1", "2026-10-22T23:30Z")]})
    with patch.object(NS, "get_schedule") as mock_fallback:
        games = E.get_schedule("2026-10-22")
    assert len(games) == 1
    mock_fallback.assert_not_called()


def test_get_schedule_fallback_fires_when_espn_only_has_adjacent_date_games(monkeypatch):
    # ESPN answers successfully, but every event is from an adjacent day -> after the Eastern
    # filter nothing is left for the requested date, so the fallback gets its chance.
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": [_event("1", "2026-10-21T23:30Z")]})
    monkeypatch.setattr(NS, "get_schedule", lambda d, lid: [_FALLBACK_GAME])
    assert E.get_schedule("2026-10-22") == [_FALLBACK_GAME]


# ----------------------------------------------------------------- get_schedule: Eastern-date filtering
def test_get_schedule_filters_out_a_game_from_an_adjacent_date(monkeypatch):
    # 2026-10-21T23:00Z is 7 PM ET on Oct 21 -- not the requested Oct 22.
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": [_event("1", "2026-10-21T23:00Z")]})
    assert E.get_schedule("2026-10-22") == []


def test_get_schedule_keeps_a_late_game_that_crosses_midnight_utc_but_matches_eastern(monkeypatch):
    # 2026-10-23T02:00Z is 10 PM ET on Oct 22: raw UTC date differs, Eastern date matches.
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": [_event("1", "2026-10-23T02:00Z")]})
    games = E.get_schedule("2026-10-22")
    assert len(games) == 1


def test_get_schedule_handles_both_iso_timestamp_shapes(monkeypatch):
    # ESPN mixes "...T23:00:00Z" and "...T23:00Z" in the same response shape; neither may be dropped.
    events = [_event("1", "2026-10-22T23:00:00Z"), _event("2", "2026-10-22T23:30Z", "Team C", "Team D")]
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": events})
    assert len(E.get_schedule("2026-10-22")) == 2


def test_get_schedule_skips_a_game_with_an_unparseable_date(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": [_event("1", "not-a-date")]})
    assert E.get_schedule("2026-10-22") == []


def test_get_schedule_same_team_never_appears_in_two_games_on_one_slate(monkeypatch):
    # The real reported WNBA bug (a team in two games on one apparent slate, the second from an
    # adjacent date), reproduced for NBA: only the game on the requested date may survive.
    today = _event("1", "2026-10-22T23:30Z", "Boston Celtics", "New York Knicks")
    tomorrow = _event("2", "2026-10-23T23:30Z", "Boston Celtics", "Miami Heat")
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: {"events": [today, tomorrow]})
    games = E.get_schedule("2026-10-22")
    assert [g["gameId"] for g in games] == ["1"]


# ----------------------------------------------------------------- team_abbrs_from_meta
def test_team_abbrs_from_meta_derives_from_build_slate_meta():
    meta = [{"label": "Bucks @ Celtics", "home_id": 2, "home_abbr": "BOS", "away_id": 17, "away_abbr": "MIL"}]
    assert E.team_abbrs_from_meta(meta) == {2: "BOS", 17: "MIL"}


# ----------------------------------------------------------------- get_team_roster
def test_get_team_roster_handles_grouped_shape(monkeypatch):
    fake_response = {"athletes": [
        {"position": "Guards", "items": [{"id": "1966", "displayName": "LeBron James"}]},
        {"position": "Forwards", "items": [{"id": "3975", "displayName": "Anthony Davis"}]},
    ]}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)
    roster = E.get_team_roster(13)
    assert {p["name"] for p in roster} == {"LeBron James", "Anthony Davis"}
    print("✓ get_team_roster correctly flattens the grouped-by-position shape")


def test_get_team_roster_handles_flat_shape(monkeypatch):
    fake_response = {"athletes": [{"id": "1966", "displayName": "LeBron James"}]}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_response)
    roster = E.get_team_roster(13)
    assert roster == [{"id": 1966, "name": "LeBron James"}]
    print("✓ get_team_roster correctly handles a flat (non-grouped) athletes list")


def test_get_team_roster_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_roster(13) == []


# ----------------------------------------------------------------- get_game_boxscore
def test_get_game_boxscore_parses_cdn_shape(monkeypatch):
    E._response_cache.clear()
    fake_cdn = {"gamepackageJSON": {"boxscore": {"players": [
        {"statistics": [{"names": ["MIN", "PTS", "REB", "AST", "3PT"],
                        "athletes": [{"athlete": {"id": "1966"}, "stats": ["36", "25", "8", "7", "3-6"],
                                     "didNotPlay": False}]}]},
    ]}}}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    box = E.get_game_boxscore("g1")
    assert box[1966] == {"pts": 25.0, "reb": 8.0, "ast": 7.0, "fg3m": 3.0, "min": 36.0}
    print("✓ get_game_boxscore correctly parses the CDN player-stats shape")


def test_get_game_boxscore_real_confirmed_live_shape(monkeypatch):
    # Built directly from a real, live CDN response pasted back during verification: Nets @
    # Clippers, Jan 25 2026 (gameId 401810511). This is Michael Porter Jr.'s actual real line —
    # confirms the full 14-field names/stats shape (MIN/PTS/FG/3PT/FT/REB/AST/TO/STL/BLK/OREB/
    # DREB/PF/+/-) genuinely matches what get_game_boxscore parses, not just the synthetic
    # 5-field fixture above. The single biggest unconfirmed piece of the NBA build before this.
    E._response_cache.clear()
    names = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]
    fake_cdn = {"gamepackageJSON": {"boxscore": {"players": [
        {"team": {"id": "17"}, "statistics": [{"names": names, "athletes": [
            {"athlete": {"id": "4278104"}, "didNotPlay": False,
            "stats": ["22", "9", "3-11", "0-4", "3-3", "2", "4", "1", "0", "0", "0", "2", "2", "-25"]},
        ]}]},
    ]}}}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    box = E.get_game_boxscore("g1")
    # Michael Porter Jr.'s real confirmed line: 22 MIN, 9 PTS, 3-11 FG, 0-4 3PT (0 makes), 2 REB, 4 AST
    assert box[4278104] == {"pts": 9.0, "reb": 2.0, "ast": 4.0, "fg3m": 0.0, "min": 22.0}
    print("✓ get_game_boxscore correctly parses the real, confirmed-live Nets/Clippers player data")


def test_get_game_boxscore_skips_did_not_play(monkeypatch):
    E._response_cache.clear()
    fake_cdn = {"gamepackageJSON": {"boxscore": {"players": [
        {"statistics": [{"names": ["MIN", "PTS"],
                        "athletes": [{"athlete": {"id": "1966"}, "stats": ["0", "0"], "didNotPlay": True}]}]},
    ]}}}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: fake_cdn)
    assert E.get_game_boxscore("g1") == {}


def test_get_game_boxscore_empty_on_fetch_failure(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_game_boxscore("g1") == {}


# ----------------------------------------------------------------- wrapper wiring (thin delegation)
def test_get_team_recent_game_ids_wires_nba_site_api(monkeypatch):
    captured = {}

    def fake_get_team_recent_game_ids(team_id, before_date, site_api, fetch, diag, **kwargs):
        captured["site_api"] = site_api
        return []

    import basketball_engine as BB
    monkeypatch.setattr(BB, "get_team_recent_game_ids", fake_get_team_recent_game_ids)
    E.get_team_recent_game_ids(2, "2026-01-14")
    assert captured["site_api"] == E.SITE_API
    print("✓ get_team_recent_game_ids passes NBA's own SITE_API into the shared implementation")


def test_get_game_team_totals_wires_nba_cdn_api(monkeypatch):
    captured = {}

    def fake_get_game_team_totals(game_id, cdn_api, fetch, diag, **kwargs):
        captured["cdn_api"] = cdn_api
        return {}

    import basketball_engine as BB
    monkeypatch.setattr(BB, "get_game_team_totals", fake_get_game_team_totals)
    E.get_game_team_totals("g1")
    assert captured["cdn_api"] == E.CDN_API
    print("✓ get_game_team_totals passes NBA's own CDN_API into the shared implementation")


def test_get_team_injuries_wires_nba_site_api(monkeypatch):
    captured = {}

    def fake_get_team_injuries(team_abbr, site_api, fetch, diag=None, **kwargs):
        captured["site_api"] = site_api
        return []

    import basketball_engine as BB
    monkeypatch.setattr(BB, "get_team_injuries", fake_get_team_injuries)
    E.get_team_injuries("BOS")
    assert captured["site_api"] == E.SITE_API
    print("✓ get_team_injuries passes NBA's own SITE_API into the shared implementation")


# ----------------------------------------------------------------- get_team_recent_allowed_stats
def test_get_team_recent_allowed_stats_averages_opponent_totals(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=10, days_back=45: [
                            {"gameId": "g1", "date": "2026-01-10T00:00Z", "opp_id": "17", "opp_name": "Milwaukee Bucks"},
                            {"gameId": "g2", "date": "2026-01-05T00:00Z", "opp_id": "6", "opp_name": "Miami Heat"},
                        ])
    game_totals = {
        "g1": {17: {"pts": 118.0, "reb": 44.0, "ast": 26.0, "fg3m": 14.0, "poss": 100.0}},
        "g2": {6: {"pts": 104.0, "reb": 40.0, "ast": 22.0, "fg3m": 10.0, "poss": 96.0}},
    }
    monkeypatch.setattr(E, "get_game_team_totals", lambda gid: game_totals.get(gid, {}))
    allowed = E.get_team_recent_allowed_stats(2, "2026-01-14", n=10)
    assert allowed["pts"] == 111.0   # avg(118, 104)
    assert allowed["poss"] == 98.0   # avg(100, 96)
    print("✓ get_team_recent_allowed_stats correctly averages the OPPONENT's totals across games")


def test_get_team_recent_scored_stats_averages_own_totals(monkeypatch):
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

    scored = E.get_team_recent_scored_stats(20, "2026-07-14", n=10)
    # REAL, CONFIRMED FIX -- the mirror image of get_team_recent_allowed_stats just above: team
    # 20's OWN points were 90 and 85 -> scored avg pts = 87.5, NOT the opponents' 78/82 that the
    # allowed-stats test above correctly returns. This is the exact distinction the whole
    # TeamTrend feature depends on -- confusing these two would silently invert every trend.
    assert scored["pts"] == 87.5
    assert scored["reb"] == 34.0
    assert scored["poss"] == 93.0
    print("✓ get_team_recent_scored_stats correctly averages THIS team's own totals, not the opponents'")


def test_get_team_recent_scored_stats_empty_when_no_recent_games(monkeypatch):
    E._response_cache.clear()
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=10, days_back=45: [])
    scored = E.get_team_recent_scored_stats(20, "2026-07-14")
    assert scored == {"pts": 0.0, "reb": 0.0, "ast": 0.0, "fg3m": 0.0, "poss": 0.0}


# ----------------------------------------------------------------- get_team_rest_info
def test_get_team_rest_info_flags_back_to_back(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [
                            {"gameId": "g1", "date": "2026-01-13T00:00Z", "opp_id": "17", "opp_name": "Milwaukee Bucks"},
                        ])
    info = E.get_team_rest_info(2, "2026-01-14")
    assert info["rest_days"] == 1 and info["is_back_to_back"] is True
    print("✓ get_team_rest_info correctly flags a back-to-back")


def test_get_team_rest_info_unknown_when_no_recent_game(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda team_id, before_date, n=1, days_back=10: [])
    info = E.get_team_rest_info(2, "2026-01-14")
    assert info == {"rest_days": None, "is_back_to_back": False, "last_game_date": None, "last_opp_name": None}


# ----------------------------------------------------------------- pure logic
def test_avg_minutes():
    log = [_log(20, 5, 3, 2, 30), _log(18, 4, 4, 1, 34)]
    assert E.avg_minutes(log) == 32.0


def test_player_row_filters_below_rotation_bar():
    player = {"id": 1966, "name": "LeBron James"}
    low_minutes_log = [_log(4, 1, 1, 0, 6)]
    assert E.player_row(player, "Lakers", "Celtics", "Celtics @ Lakers", "2026-01-14T00:00Z",
                        low_minutes_log, min_avg_minutes=12.0) is None
    print("✓ player_row filters out players below the rotation-minutes bar")


def test_player_row_builds_correctly_for_a_rotation_player():
    player = {"id": 1966, "name": "LeBron James"}
    log = [_log(25, 8, 7, 3, 36), _log(28, 6, 9, 2, 34)]
    row = E.player_row(player, "Lakers", "Celtics", "Celtics @ Lakers", "2026-01-14T00:00Z",
                       log, min_avg_minutes=12.0, opp_id=2, team_id=13)
    assert row["Player"] == "LeBron James"
    assert row["PTS"] == 26.5
    assert row["_opp_id"] == 2 and row["_team_id"] == 13
    print("✓ player_row builds a correct flat row for a rotation player")


# ----------------------------------------------------------------- season-start bound
def test_season_start_bounds_days_since_start():
    assert E.SEASON_START == "2026-10-20"   # the confirmed 2026-27 opener, not a placeholder
    days = E._days_since_season_start("2026-11-01")
    assert days == (12 + 1)   # Nov 1 minus SEASON_START (2026-10-20) = 12 days, +1


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
