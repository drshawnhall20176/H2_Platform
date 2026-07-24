"""
test_data_freshness.py — offline tests for data_freshness.py.

No network required — uses real temp files with controlled modification times.
"""

import os
import tempfile
import time

import pandas as pd

import data_freshness as DF


def _write_csv(path, n_rows=100):
    df = pd.DataFrame({"a": range(n_rows), "b": range(n_rows)})
    df.to_csv(path, index=False)


def test_check_source_missing_file_is_red():
    result = DF.check_source("Test Source", "/nonexistent/path/does_not_exist.csv", 24, 50)
    assert result["status"] == "red"
    assert "not found" in result["reason"].lower()
    assert result["row_count"] is None
    print("✓ check_source correctly flags a missing file as red")


def test_check_source_fresh_and_healthy_is_green():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.csv")
        _write_csv(path, n_rows=200)
        now = time.time()
        os.utime(path, (now, now))   # exactly "now" -- zero age
        result = DF.check_source("Test Source", path, 24, 50, now=now)
    assert result["status"] == "green"
    assert result["reason"] is None
    assert result["row_count"] == 200
    assert result["age_hours"] == 0.0
    print("✓ check_source correctly flags a fresh, healthy file as green")


def test_check_source_below_min_rows_is_red():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.csv")
        _write_csv(path, n_rows=3)   # below the min_rows floor of 50
        now = time.time()
        os.utime(path, (now, now))
        result = DF.check_source("Test Source", path, 24, 50, now=now)
    assert result["status"] == "red"
    assert "below the expected floor" in result["reason"]
    assert result["row_count"] == 3
    print("✓ check_source correctly flags a too-thin file as red, even though it's fresh")


def test_check_source_unreadable_file_is_red():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.csv")
        with open(path, "w") as f:
            f.write("this is not a valid csv at all \x00\x01\x02")
        now = time.time()
        os.utime(path, (now, now))
        result = DF.check_source("Test Source", path, 24, 50, now=now)
    # Either it parses as a weird 1-column frame (caught by min_rows) or fails outright (caught
    # by the except branch) -- either way this must never crash, and must never report green.
    assert result["status"] == "red"
    print("✓ check_source never crashes on unreadable content, and never reports it as healthy")


def test_check_source_stale_file_is_yellow():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.csv")
        _write_csv(path, n_rows=200)
        now = time.time()
        stale_time = now - (60 * 3600)   # 60 hours old, cadence=24h, threshold=48h -> stale
        os.utime(path, (stale_time, stale_time))
        result = DF.check_source("Test Source", path, 24, 50, now=now)
    assert result["status"] == "yellow"
    assert "stale" in result["reason"].lower()
    assert result["age_hours"] == 60.0
    print("✓ check_source correctly flags a genuinely stale (2x+ cadence) file as yellow, not red")


def test_check_source_just_under_stale_threshold_is_green():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.csv")
        _write_csv(path, n_rows=200)
        now = time.time()
        # cadence=24h, STALE_MULTIPLIER=2.0 -> threshold is 48h; 47h should still be green,
        # a real boundary check, not just values clearly on either side
        near_time = now - (47 * 3600)
        os.utime(path, (near_time, near_time))
        result = DF.check_source("Test Source", path, 24, 50, now=now)
    assert result["status"] == "green"
    print("✓ check_source correctly stays green just under the stale threshold, not overly eager to flag")


def test_check_source_a_bit_late_is_not_flagged():
    # A source refreshed 26h ago (2h later than its 24h cadence) should NOT be flagged yellow --
    # GitHub Actions queue delays are real and common; only genuinely stale (2x+) should alarm.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.csv")
        _write_csv(path, n_rows=200)
        now = time.time()
        slightly_late = now - (26 * 3600)
        os.utime(path, (slightly_late, slightly_late))
        result = DF.check_source("Test Source", path, 24, 50, now=now)
    assert result["status"] == "green"
    print("✓ check_source doesn't flag a merely-a-bit-late refresh, only a genuinely stale one")


def test_check_all_sources_preserves_order_and_checks_each():
    with tempfile.TemporaryDirectory() as tmp:
        path_a = os.path.join(tmp, "a.csv")
        path_b = os.path.join(tmp, "b.csv")
        _write_csv(path_a, n_rows=200)
        # path_b deliberately not created -- missing
        now = time.time()
        os.utime(path_a, (now, now))
        sources = [("Source A", path_a, 24, 50), ("Source B", path_b, 24, 50)]
        results = DF.check_all_sources(sources, now=now)
    assert [r["name"] for r in results] == ["Source A", "Source B"]
    assert results[0]["status"] == "green"
    assert results[1]["status"] == "red"
    print("✓ check_all_sources correctly checks every source and preserves order")


def test_overall_status_red_if_any_red():
    results = [{"status": "green"}, {"status": "red"}, {"status": "yellow"}]
    assert DF.overall_status(results) == "red"


def test_overall_status_yellow_if_any_yellow_no_red():
    results = [{"status": "green"}, {"status": "yellow"}]
    assert DF.overall_status(results) == "yellow"


def test_overall_status_green_if_all_green():
    results = [{"status": "green"}, {"status": "green"}]
    assert DF.overall_status(results) == "green"
    print("✓ overall_status correctly summarizes to the single worst status across all sources")


def test_tracked_sources_real_paths_match_actual_modules():
    # Confirms TRACKED_SOURCES' own paths are the REAL paths statcast_data.py/matchup_data.py
    # actually use, not stale copies that could silently drift from the real constants.
    import statcast_data as SC
    import matchup_data as MD
    tracked_paths = {name: path for name, path, _, _ in DF.TRACKED_SOURCES}
    assert tracked_paths["Statcast batters"] == SC.DEFAULT_PATH
    assert tracked_paths["Catcher framing"] == SC.CATCHER_FRAMING_PATH
    assert tracked_paths["Pitcher arsenals"] == MD.ARSENAL_PATH
    assert tracked_paths["Hitter pitch splits"] == MD.HITTER_PATH
    assert tracked_paths["Hitter pitch type splits"] == MD.HITTER_TYPE_PATH
    print("✓ TRACKED_SOURCES' paths match the real, current constants in each module, not stale copies")


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
