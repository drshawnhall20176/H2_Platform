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
            ND.refresh_schedule(2026, "FAKE_KEY", out_path=out)
        rows = ND.load_schedule(out)
    assert len(rows) == 1
    assert rows[0]["home_team"] == "North Carolina" and rows[0]["away_team"] == "TCU"
    assert rows[0]["neutral_site"] is True
    assert rows[0]["week"] == 1
    print("✓ refresh_schedule parses camelCase game fields correctly")


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
