"""
test_ncaaf_data.py — offline tests for ncaaf_data.py (no network, no real CFBD key).

_get is mocked at the module level throughout, the same pattern test_odds.py already uses for
odds_api.fetch_events/fetch_event_props. Two response-shape variants (snake_case and camelCase)
are tested for every parser on purpose -- ncaaf_data.py's own docstring is explicit that which
convention CFBD's raw REST API actually uses is unconfirmed until a real refresh run, so both
paths need real coverage, not just the one that happens to match the published docs' Pydantic
field names.
"""

import os
import tempfile
from unittest.mock import patch

import ncaaf_data as ND


def test_refresh_rosters_snake_case():
    fake = [{"id": "r1", "first_name": "Jane", "last_name": "Doe", "team": "Ohio State",
            "position": "QB", "year": 3, "jersey": 7, "height": 74.0, "weight": 215}]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "roster.csv")
        with patch.object(ND, "_get", return_value=fake):
            ND.refresh_rosters(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_rosters(out)
    assert len(rows) == 1
    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["team"] == "Ohio State"
    print("✓ refresh_rosters parses snake_case fields and builds a combined display name")


def test_refresh_rosters_camel_case():
    fake = [{"id": "r2", "firstName": "John", "lastName": "Smith", "team": "Georgia",
            "position": "RB", "year": 2, "jersey": 21, "height": 71.0, "weight": 205}]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "roster.csv")
        with patch.object(ND, "_get", return_value=fake):
            ND.refresh_rosters(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_rosters(out)
    assert len(rows) == 1
    assert rows[0]["name"] == "John Smith"
    print("✓ refresh_rosters also handles camelCase fields (unconfirmed which convention the "
         "real raw API uses -- both are covered)")


def test_refresh_player_season_stats_pivots_long_format_to_wide():
    # The core, real risk this module exists to handle: CFBD returns one row per
    # (player, category, stat_type), not one row per player. This must pivot correctly.
    fake = [
        {"season": 2026, "player_id": "12345", "player": "Jane Doe", "position": "QB",
         "team": "Ohio State", "conference": "Big Ten", "category": "passing",
         "stat_type": "YDS", "stat": "3245"},
        {"season": 2026, "player_id": "12345", "player": "Jane Doe", "position": "QB",
         "team": "Ohio State", "conference": "Big Ten", "category": "passing",
         "stat_type": "TD", "stat": "28"},
        {"season": 2026, "player_id": "999", "player": "John Smith", "position": "RB",
         "team": "Georgia", "conference": "SEC", "category": "rushing",
         "stat_type": "YDS", "stat": "1120"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "stats.csv")
        with patch.object(ND, "_get", return_value=fake):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_player_stats(out)

    assert len(rows) == 2   # two distinct players, not three rows
    jane = next(r for r in rows if r["player"] == "Jane Doe")
    assert jane["passing_YDS"] == 3245
    assert jane["passing_TD"] == 28
    john = next(r for r in rows if r["player"] == "John Smith")
    assert john["rushing_YDS"] == 1120
    print("✓ refresh_player_season_stats correctly pivots CFBD's long-format rows into one row "
         "per player with a column per (category, stat_type)")


def test_refresh_player_season_stats_camel_case_and_string_stat_value():
    # camelCase field names AND confirms the stat value (a STRING per CFBD's own schema) gets
    # cast to numeric, not left as text.
    fake = [{"season": 2026, "playerId": "1", "player": "X", "position": "QB", "team": "T",
            "conference": "C", "category": "passing", "statType": "YDS", "stat": "2500"}]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "stats.csv")
        with patch.object(ND, "_get", return_value=fake):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_player_stats(out)
    assert rows[0]["passing_YDS"] == 2500
    assert isinstance(rows[0]["passing_YDS"], (int, float))
    print("✓ handles camelCase field names and casts the string stat value to numeric")


def test_refresh_player_season_stats_empty_response():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "stats.csv")
        with patch.object(ND, "_get", return_value=[]):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_player_stats(out)
    assert rows == []
    print("✓ an empty response writes an empty, still-loadable cache instead of crashing")


def test_refresh_schedule_camel_case():
    fake = [{"id": 1, "season": 2026, "week": 1, "startDate": "2026-08-29T19:30:00.000Z",
            "startTimeTBD": False, "completed": False, "neutralSite": True,
            "venue": "Aviva Stadium", "homeId": 1, "homeTeam": "North Carolina",
            "homeConference": "ACC", "homePoints": None,
            "awayId": 2, "awayTeam": "TCU", "awayConference": "Big 12", "awayPoints": None}]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "sched.csv")
        with patch.object(ND, "_get", return_value=fake):
            ND.refresh_schedule([2026], "FAKE_KEY", out_path=out)
        rows = ND.load_schedule(out)
    assert len(rows) == 1
    assert rows[0]["home_team"] == "North Carolina" and rows[0]["away_team"] == "TCU"
    assert rows[0]["neutral_site"] is True
    assert rows[0]["week"] == 1
    print("✓ refresh_schedule parses camelCase game fields correctly")


def test_refresh_schedule_merges_multiple_years_into_one_cache():
    # Regression guard for a real, live-confirmed bug: refresh_schedule used to accept only a
    # single year, but roster/player-stats can fall back to year-1 while the schedule stays on
    # the target year -- ncaaf_engine._team_games_played_for_stats_season then needs the
    # FALLBACK year's own schedule too (to count its real completed games), and it simply didn't
    # exist. Confirmed live: a real refresh_ncaaf.py run showed a real 2026 schedule alongside
    # 2025-fallback stats, and Best Bets showed zero plays for every date tried. This is the fix:
    # one call per requested year, merged into a single cache get_schedule(season) can filter.
    fake_2026 = [{"id": 1, "season": 2026, "week": 1, "home_team": "A", "away_team": "B"}]
    fake_2025 = [{"id": 2, "season": 2025, "week": 6, "home_team": "C", "away_team": "D"}]
    calls = []

    def fake_get(path, params, api_key):
        calls.append(params["year"])
        return fake_2026 if params["year"] == 2026 else fake_2025

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "sched.csv")
        with patch.object(ND, "_get", side_effect=fake_get):
            ND.refresh_schedule([2026, 2025], "FAKE_KEY", out_path=out)
        rows = ND.load_schedule(out)

    assert calls == [2026, 2025]   # one call per requested year
    assert len(rows) == 2
    seasons = {r["season"] for r in rows}
    assert seasons == {2026, 2025}   # both years present in the merged cache, not just one
    print("✓ refresh_schedule pulls and merges multiple years into one cache, so "
         "get_schedule(fallback_year) can find real games instead of coming back empty")


def test_refresh_player_game_stats_parses_nested_structure_and_tracks_opponent():
    # This function existed with only manual bash verification, never real pytest coverage --
    # closing that gap now, including the opponent_team field (derived from the OTHER team
    # already present in the same game's raw teams list, no extra call needed).
    fake_response = [{
        "id": 12345,
        "teams": [
            {"school": "Ohio State", "categories": [{"name": "passing", "types": [
                {"name": "YDS", "athletes": [{"id": "p1", "name": "Star QB", "stat": "312"}]},
                {"name": "TD", "athletes": [{"id": "p1", "name": "Star QB", "stat": "3"}]},
            ]}]},
            {"school": "Texas", "categories": [{"name": "passing", "types": [
                {"name": "YDS", "athletes": [{"id": "p2", "name": "Other QB", "stat": "250"}]},
            ]}]},
        ],
    }]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "games.csv")
        with patch.object(ND, "_get", return_value=fake_response):
            ND.refresh_player_game_stats(2025, "FAKE_KEY", completed_weeks=[6], out_path=out)
        rows = ND.load_player_game_stats(out)

    assert len(rows) == 2
    osu = next(r for r in rows if r["player"] == "Star QB")
    tex = next(r for r in rows if r["player"] == "Other QB")
    assert osu["team"] == "Ohio State" and osu["opponent_team"] == "Texas"
    assert osu["passing_YDS"] == 312 and osu["passing_TD"] == 3
    assert tex["team"] == "Texas" and tex["opponent_team"] == "Ohio State"
    assert osu["week"] == 6 and osu["game_id"] == 12345
    print("✓ refresh_player_game_stats parses the nested structure correctly and tracks each "
         "player's real opponent for that game")


def test_refresh_player_game_stats_uses_multiple_key_name_fallbacks():
    # The two deepest models (PlayerGameTypes, PlayerGameAthletes) resisted full documentation
    # confirmation -- this locks in that the defensive multi-key-name lookups actually work,
    # not just that the happy path does.
    fake_response = [{
        "id": 1,
        "teams": [
            {"school": "A", "categories": [{"name": "rushing", "types": [
                {"type": "YDS", "athletes": [{"athleteId": "p9", "player": "Alt Keys", "value": "88"}]},
            ]}]},
            {"school": "B", "categories": []},
        ],
    }]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "games.csv")
        with patch.object(ND, "_get", return_value=fake_response):
            ND.refresh_player_game_stats(2025, "FAKE_KEY", completed_weeks=[1], out_path=out)
        rows = ND.load_player_game_stats(out)
    assert len(rows) == 1
    assert rows[0]["player_id"] == "p9" and rows[0]["player"] == "Alt Keys"
    assert rows[0]["rushing_YDS"] == 88
    print("✓ refresh_player_game_stats' defensive key-name fallbacks (type/athleteId/value) work, "
         "not just the primary name/id/stat keys")


def test_refresh_player_game_stats_empty_completed_weeks_writes_empty_cache():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "games.csv")
        ND.refresh_player_game_stats(2025, "FAKE_KEY", completed_weeks=[], out_path=out)
        rows = ND.load_player_game_stats(out)
    assert rows == []
    print("✓ refresh_player_game_stats writes a loadable empty cache when there are no "
         "completed weeks to pull (no API calls made, no crash)")


def test_resolve_week_finds_upcoming_and_falls_back_to_last_week():
    schedule = [
        {"week": 1, "start_date": "2026-08-29T19:30:00Z"},
        {"week": 2, "start_date": "2026-09-05T19:30:00Z"},
        {"week": 3, "start_date": "2026-09-12T19:30:00Z"},
    ]
    # A date before week 1 -> resolves to week 1 (the next upcoming week)
    assert ND.resolve_week("2026-08-20", schedule=schedule) == 1
    # A date between week 1 and week 2 -> resolves to week 2 (the next upcoming)
    assert ND.resolve_week("2026-08-30", schedule=schedule) == 2
    # A date past every game in the schedule -> falls back to the LAST week, same fallback
    # nfl_engine.py's own _resolve_week uses, not None (a date picker landing on an off day
    # shouldn't leave the page with nothing to show).
    assert ND.resolve_week("2026-12-01", schedule=schedule) == 3
    print("✓ resolve_week finds the next upcoming week and falls back to the season's last week")


def test_resolve_week_empty_schedule_returns_none():
    assert ND.resolve_week("2026-08-29", schedule=[]) is None
    print("✓ resolve_week returns None (not a crash) for an empty schedule")


def test_get_raises_cfbd_error_on_401():
    import requests as _requests

    class _FakeResp:
        status_code = 401
        text = "unauthorized"

    with patch.object(_requests, "get", return_value=_FakeResp()):
        try:
            ND._get("/roster", {"year": 2026}, "BAD_KEY")
            assert False, "expected CFBDError"
        except ND.CFBDError as e:
            assert "401" in str(e)
    print("✓ _get raises a clear CFBDError on 401 (bad/missing key), matching odds_api.py's "
         "own error-handling convention")


def test_load_rosters_handles_a_genuinely_empty_api_response_without_crashing():
    # Regression guard for a real, live-confirmed crash: a GitHub Actions run against the real
    # CFBD API returned 0 roster rows for 2026 (a month before the season -- rosters likely
    # aren't posted yet, see refresh_ncaaf.py's own diagnostic for that). pd.DataFrame([]) (zero
    # rows) has NO COLUMNS at all, not just zero rows, so it writes an essentially blank CSV --
    # and pd.read_csv on that raised pandas.errors.EmptyDataError: "No columns to parse from
    # file", crashing the whole refresh job instead of just reporting 0 players cached.
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "roster.csv")
        with patch.object(ND, "_get", return_value=[]):
            ND.refresh_rosters(2026, "FAKE_KEY", out_path=out)
        result = ND.load_rosters(out)   # must not raise
    assert result == []
    print("✓ load_rosters returns [] instead of crashing on a genuinely empty API response, "
         "reproducing the exact real failure from a live workflow run")


def test_load_player_stats_and_load_schedule_also_handle_empty_responses():
    with tempfile.TemporaryDirectory() as tmp:
        stats_out = os.path.join(tmp, "stats.csv")
        sched_out = os.path.join(tmp, "sched.csv")
        with patch.object(ND, "_get", return_value=[]):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=stats_out)
            ND.refresh_schedule([2026], "FAKE_KEY", out_path=sched_out)
        assert ND.load_player_stats(stats_out) == []
        assert ND.load_schedule(sched_out) == []
    print("✓ load_player_stats and load_schedule are equally robust to an empty API response")


def test_refresh_rosters_falls_back_to_prior_year_when_current_year_is_empty():
    # Regression guard for a real production bug: GET /roster?year=2026 returned 0 players on a
    # live run (confirmed via a real GitHub Actions log, not theoretical) -- weeks before the
    # 2026 season's own Week 0 kickoff. The endpoint call itself succeeded (no 401/429), it's
    # just that a not-yet-started season's roster genuinely isn't populated yet. Falls back to
    # year-1 and clearly logs it as a fallback, rather than caching nothing (which crashed
    # load_rosters downstream with EmptyDataError before this fix existed at all).
    fake_2025 = [{"id": "r1", "first_name": "Jane", "last_name": "Doe", "team": "Ohio State",
                 "position": "QB", "year": 3, "jersey": 7, "height": 74.0, "weight": 215}]
    calls = []

    def fake_get(path, params, api_key):
        calls.append(params["year"])
        return [] if params["year"] == 2026 else fake_2025

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "roster.csv")
        with patch.object(ND, "_get", side_effect=fake_get):
            ND.refresh_rosters(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_rosters(out)

    assert calls == [2026, 2025]   # tried the requested year first, THEN fell back
    assert len(rows) == 1 and rows[0]["name"] == "Jane Doe"
    print("✓ refresh_rosters falls back to year-1 when the requested year's roster is empty, "
         "exactly reproducing and fixing the real GET /roster?year=2026 -> 0 players failure")


def test_refresh_rosters_stays_on_requested_year_when_it_has_real_data():
    # The fallback must not trigger when the requested year DOES have data -- a real, non-empty
    # roster should never be silently swapped for last year's.
    fake_2026 = [{"id": "r2", "first_name": "New", "last_name": "Guy", "team": "Georgia",
                 "position": "RB", "year": 1, "jersey": 1, "height": 70.0, "weight": 190}]
    calls = []

    def fake_get(path, params, api_key):
        calls.append(params["year"])
        return fake_2026

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "roster.csv")
        with patch.object(ND, "_get", side_effect=fake_get):
            ND.refresh_rosters(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_rosters(out)

    assert calls == [2026]   # only ONE call -- no unnecessary fallback attempt
    assert rows[0]["name"] == "New Guy"
    print("✓ refresh_rosters does not fall back when the requested year already has real data")


def test_refresh_player_season_stats_year_1_still_contributes_when_year_is_empty():
    # RENAMED AND REWRITTEN, not just re-verified: the OLD conditional "only fetch year-1 if
    # year returned zero rows" logic is gone entirely, replaced by "always fetch both, always
    # keep both" -- this test now confirms the specific case that logic still needs to handle
    # correctly: when the target year genuinely has 0 rows, the prior year's real rows must
    # still make it into the combined output, not get lost.
    fake_2025 = [{"season": 2025, "player_id": "1", "player": "X", "position": "QB", "team": "T",
                 "conference": "C", "category": "passing", "stat_type": "YDS", "stat": "3000"}]
    calls = []

    def fake_get(path, params, api_key):
        calls.append(params["year"])
        return [] if params["year"] == 2026 else fake_2025

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "stats.csv")
        with patch.object(ND, "_get", side_effect=fake_get):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_player_stats(out)

    assert calls == [2026, 2025]
    assert len(rows) == 1 and rows[0]["passing_YDS"] == 3000
    print("✓ refresh_player_season_stats still surfaces year-1's real rows when the target year genuinely has none")


def test_refresh_player_season_stats_always_fetches_both_years_even_when_target_has_real_data():
    # THE real, direct regression guard for the actual live bug this whole rewrite exists to
    # fix: confirms BOTH years are fetched even when the target year ALREADY has real, non-empty
    # data -- the old code would have stopped after year alone here, exactly the gap that let a
    # real, live pull return 1,082 real rows for the wrong 37 teams and silently never even try
    # year-1 for the 138 real FBS teams missing from it.
    fake_2026 = [{"season": 2026, "player_id": "1", "player": "FCS Player", "position": "QB",
                 "team": "Elon", "conference": "CAA", "category": "passing", "stat_type": "YDS", "stat": "500"}]
    fake_2025 = [{"season": 2025, "player_id": "2", "player": "FBS Player", "position": "QB",
                 "team": "Alabama", "conference": "SEC", "category": "passing", "stat_type": "YDS", "stat": "3500"}]
    calls = []

    def fake_get(path, params, api_key):
        calls.append(params["year"])
        return fake_2026 if params["year"] == 2026 else fake_2025

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "stats.csv")
        with patch.object(ND, "_get", side_effect=fake_get):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_player_stats(out)

    assert calls == [2026, 2025], (
        "year-1 must genuinely be fetched even though year already returned real, non-empty "
        "data -- this is the actual real-world bug this rewrite fixes")
    assert len(rows) == 2   # both years' real rows present, neither dropped
    seasons_present = {r["season"] for r in rows}
    assert seasons_present == {2026, 2025}
    print("✓ refresh_player_season_stats genuinely fetches AND KEEPS both years even when the target year already has real data -- the actual fix for the live FCS/FBS team-coverage gap")


def test_refresh_player_season_stats_keeps_a_returning_players_two_seasons_separate():
    # A REAL edge case worth its own direct test: the same real player (same player_id) has a
    # real row in BOTH years -- confirms the (player_id, season) composite key genuinely keeps
    # both, rather than the old single-player_id dedup silently collapsing them into one.
    fake_2026 = [{"season": 2026, "player_id": "99", "player": "Returning Player", "position": "QB",
                 "team": "Georgia", "conference": "SEC", "category": "passing", "stat_type": "YDS", "stat": "400"}]
    fake_2025 = [{"season": 2025, "player_id": "99", "player": "Returning Player", "position": "QB",
                 "team": "Georgia", "conference": "SEC", "category": "passing", "stat_type": "YDS", "stat": "3200"}]

    def fake_get(path, params, api_key):
        return fake_2026 if params["year"] == 2026 else fake_2025

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "stats.csv")
        with patch.object(ND, "_get", side_effect=fake_get):
            ND.refresh_player_season_stats(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_player_stats(out)

    assert len(rows) == 2, "the same real player_id in two different real seasons must produce two rows, not one collapsed row"
    by_season = {r["season"]: r for r in rows}
    assert by_season[2026]["passing_YDS"] == 400
    assert by_season[2025]["passing_YDS"] == 3200
    print("✓ refresh_player_season_stats keeps a real returning player's two distinct season rows separate, not silently collapsed into one")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
