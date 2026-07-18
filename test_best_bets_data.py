"""
test_best_bets_data.py — offline tests for best_bets_data.py, the shared MLB best-bets board
loader used by both Best Bets and Command Center.

Regression guard for a real production bug: before this shared module existed, Best Bets and
Command Center each had their OWN separate copy of this loading logic. When the bullpen-blend
re-pricing fix was added, it only landed in Best Bets' own copy — Command Center's separate copy
silently kept showing the old, unblended conviction numbers for the same plays, with no error.
These tests exist to make sure that specific class of drift can't happen again: both view files
now call the exact same function, and these tests exercise that function directly.

No network required.
"""

import inspect
from unittest.mock import patch

import best_bets_data as BBD
import mlb_engine as E
import projections as P


def test_module_imports_mlb_modules_directly_not_via_sport_dispatch():
    # Regression guard for a real risk found and fixed while building this module: routing E/P
    # through sports.active() at module import time would freeze them to whatever sport was
    # active on FIRST import (Python only runs a module's top-level code once per process), a
    # real risk this module didn't have when the same logic was inline in each view file (which
    # re-runs fresh on every Streamlit page load). Confirms the actual fix, not just the intent.
    assert BBD.E is E
    assert BBD.P is P
    print("✓ best_bets_data.E/P are directly mlb_engine/projections, not sports.active()-dependent")


def test_load_mlb_best_bets_board_signature():
    sig = inspect.signature(BBD.load_mlb_best_bets_board)
    assert list(sig.parameters.keys()) == ["date_str", "fip_constant"]


def _fake_row_and_meta():
    fake_hitter_stat = dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                            homeRuns=38, baseOnBalls=55, strikeOuts=140)
    bad_starter_stat = dict(gamesStarted=15, inningsPitched="75.0", battersFaced=400,
                            strikeOuts=60, baseOnBalls=45, homeRuns=20, hits=115)
    fake_row = {
        "Hitter": "Test Slugger", "Team": "Test Team", "GameLabel": "Away @ Home (Game 1)",
        "Hand": "L", "Opp Pitcher": "Bad Starter", "Opp Hand": "R", "Opp HR/9": 1.8,
        "Advantage": "Advantage", "Lineup": "Confirmed", "HR": 38, "Hits": 165, "TB": 300,
        "AVG": 0.28, "OBP": 0.36, "SLG": 0.52, "OPS": 0.88, "ISO": 0.24, "K%": 0.14,
        "PowerIndex": 50.0, "_pid": 501, "_stat": fake_hitter_stat, "_exp_pa": 4.55,
        "_venue_id": None, "_opp_stat": bad_starter_stat, "_opp_pid": 601, "_opp_id": 114,
        "_split_stat": None, "_lineup_idx": 0,
    }
    fake_meta = [{"label": "Away @ Home (Game 1)", "game_date": "2026-07-18", "venue": "Test Park",
                 "venue_id": None, "home_name": "Home Team", "away_name": "Away Team",
                 "home_id": 999, "away_id": 114,
                 "home_pm": E.PitcherMetrics(id=601, name="Bad Starter", hand="R", stat=bad_starter_stat),
                 "away_pm": E.PitcherMetrics(id=701, name="Home Starter", hand="R", stat=bad_starter_stat)}]
    return fake_row, fake_meta


def test_load_mlb_best_bets_board_full_pipeline_runs_and_blends():
    fake_row, fake_meta = _fake_row_and_meta()
    good_pen_stat = dict(strikeOuts=350, baseOnBalls=100, hitByPitch=12, homeRuns=38,
                         battersFaced=2000, hits=420, atBats=1780, earnedRuns=200,
                         inningsPitched="500.0")

    with patch.object(BBD.E, "build_slate", lambda date_str, fip: ([fake_row], fake_meta)), \
        patch.object(BBD.E, "get_bullpen_aggregate_stat",
                    lambda tid, exclude_pid=None, fip_constant=3.10: good_pen_stat), \
        patch("statcast_data.load", lambda: ({}, None)), \
        patch("weather.get_game_weather", lambda *a, **k: None):
        plays, meta = BBD.load_mlb_best_bets_board("2026-07-18", BBD.E.FIP_CONSTANT_DEFAULT)

    assert len(meta) == 1
    assert len(plays) > 0
    hr_play = next(p for p in plays if p["Market"] == "Batter HR")
    assert hr_play.get("_bullpen_blended") is True
    print("✓ load_mlb_best_bets_board runs the full pipeline end to end, including the bullpen blend")


def test_load_mlb_best_bets_board_returns_meta_not_just_count():
    # A real interface bug caught while wiring this in: Command Center needs the full meta list
    # (it never did Slot/Time enrichment at all), while Best Bets needs it to build its own
    # Slot/Time enrichment. An earlier draft returned len(meta) instead, breaking both callers'
    # actual needs. This locks in the correct return shape.
    fake_row, fake_meta = _fake_row_and_meta()

    with patch.object(BBD.E, "build_slate", lambda date_str, fip: ([fake_row], fake_meta)), \
        patch.object(BBD.E, "get_bullpen_aggregate_stat", lambda *a, **k: None), \
        patch("statcast_data.load", lambda: ({}, None)), \
        patch("weather.get_game_weather", lambda *a, **k: None):
        plays, meta = BBD.load_mlb_best_bets_board("2026-07-18", BBD.E.FIP_CONSTANT_DEFAULT)

    assert isinstance(meta, list)
    assert meta[0]["label"] == "Away @ Home (Game 1)"
    assert meta[0]["game_date"] == "2026-07-18"
    print("✓ load_mlb_best_bets_board returns the full meta list, not just its count")


def test_load_mlb_graded_picks_board_returns_rows_too():
    fake_row, fake_meta = _fake_row_and_meta()

    with patch.object(BBD.E, "build_slate", lambda date_str, fip: ([fake_row], fake_meta)), \
        patch.object(BBD.E, "get_bullpen_aggregate_stat", lambda *a, **k: None), \
        patch("statcast_data.load", lambda: ({}, None)), \
        patch("weather.get_game_weather", lambda *a, **k: None):
        plays, meta, rows = BBD.load_mlb_graded_picks_board("2026-07-18", BBD.E.FIP_CONSTANT_DEFAULT)

    assert len(plays) > 0
    assert len(meta) == 1
    assert len(rows) == 1
    assert rows[0]["Hitter"] == "Test Slugger"
    assert rows[0]["Opp HR/9"] == 1.8
    print("✓ load_mlb_graded_picks_board returns the raw hitter rows, needed for the one-sided banner")


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
