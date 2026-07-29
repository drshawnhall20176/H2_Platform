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


def test_refresh_player_season_stats_falls_back_to_prior_year_when_current_year_is_empty():
    # Same real-world cause as the roster fallback above, applied to season stats: a
    # not-yet-started season has zero games played, so /stats/player/season for the current
    # year is empty by definition until the season is underway.
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
    print("✓ refresh_player_season_stats falls back to year-1 when the current season has no "
         "games played yet")


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
