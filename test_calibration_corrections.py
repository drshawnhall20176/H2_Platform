"""
test_calibration_corrections.py — offline tests for calibration_corrections.py (temp SQLite, no
network).

    python test_calibration_corrections.py     # or: pytest test_calibration_corrections.py
"""

import os
import tempfile

import calibration_corrections as CC


def _fit(slope=1.05, intercept=0.03, n=150, weight=0.6, raw_slope=1.08, raw_intercept=0.05):
    return {"slope": slope, "intercept": intercept, "raw_slope": raw_slope,
           "raw_intercept": raw_intercept, "n": n, "weight": weight}


def test_record_fit_writes_a_row_and_latest_fit_reads_it_back():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        row_id = CC.record_fit("MLB", "Batter HR", _fit(), min_n_used=100, db_path=db)
        assert row_id == 1
        latest = CC.latest_fit("MLB", "Batter HR", db_path=db)
        assert latest is not None
        assert latest["slope"] == 1.05 and latest["intercept"] == 0.03 and latest["n"] == 150
        print("✓ record_fit writes a real row, latest_fit reads it back correctly")


def test_latest_fit_returns_none_when_nothing_recorded_yet():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        assert CC.latest_fit("MLB", "Batter HR", db_path=db) is None
        print("✓ latest_fit returns None (an honest 'no real fit exists yet') for a market that's never been fit")


def test_record_fit_is_append_only_not_replace():
    # THE deliberate design choice this module's own docstring documents: every real refit is
    # its own permanent audit entry, unlike grading_history's own per-day REPLACE semantics.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Batter HR", _fit(n=100), db_path=db)
        CC.record_fit("MLB", "Batter HR", _fit(n=250), db_path=db)
        CC.record_fit("MLB", "Batter HR", _fit(n=400), db_path=db)
        history = CC.fit_history("MLB", "Batter HR", db_path=db)
        assert len(history) == 3, f"expected all 3 real fits to be kept as separate rows, got {len(history)}"
        assert [h["n"] for h in history] == [100, 250, 400]   # oldest first
        print("✓ record_fit is append-only — every real refit stays a separate, permanent audit row, never overwritten")


def test_latest_fit_returns_the_most_recent_one():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Batter HR", _fit(slope=1.02), db_path=db)
        CC.record_fit("MLB", "Batter HR", _fit(slope=1.09), db_path=db)   # the real, current one
        latest = CC.latest_fit("MLB", "Batter HR", db_path=db)
        assert latest["slope"] == 1.09
        print("✓ latest_fit returns the most recently recorded fit, not the first one ever made")


def test_different_markets_dont_collide():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Batter HR", _fit(slope=1.10), db_path=db)
        CC.record_fit("MLB", "Pitcher Strikeouts", _fit(slope=0.95), db_path=db)
        assert CC.latest_fit("MLB", "Batter HR", db_path=db)["slope"] == 1.10
        assert CC.latest_fit("MLB", "Pitcher Strikeouts", db_path=db)["slope"] == 0.95
        print("✓ separate markets are stored and looked up independently, no cross-contamination")


def test_different_sports_dont_collide():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Points", _fit(slope=1.10), db_path=db)
        CC.record_fit("WNBA", "Points", _fit(slope=0.90), db_path=db)
        assert CC.latest_fit("MLB", "Points", db_path=db)["slope"] == 1.10
        assert CC.latest_fit("WNBA", "Points", db_path=db)["slope"] == 0.90
        print("✓ the same market name for two different sports is stored and looked up independently")


def test_fit_history_narrows_to_one_market_when_asked():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Batter HR", _fit(), db_path=db)
        CC.record_fit("MLB", "Pitcher Strikeouts", _fit(), db_path=db)
        hr_only = CC.fit_history("MLB", market="Batter HR", db_path=db)
        assert len(hr_only) == 1 and hr_only[0]["market"] == "Batter HR"
        print("✓ fit_history correctly narrows to one market when asked")


def test_fit_history_all_markets_when_market_not_given():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Batter HR", _fit(), db_path=db)
        CC.record_fit("MLB", "Pitcher Strikeouts", _fit(), db_path=db)
        every_market = CC.fit_history("MLB", db_path=db)
        assert len(every_market) == 2
        print("✓ fit_history returns every market's fits when market isn't narrowed")


def test_record_fit_stores_raw_values_and_weight_for_audit():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cc.db")
        CC.record_fit("MLB", "Batter HR", _fit(raw_slope=1.15, raw_intercept=0.08, weight=0.7),
                      min_n_used=100, db_path=db)
        row = CC.latest_fit("MLB", "Batter HR", db_path=db)
        assert row["raw_slope"] == 1.15 and row["raw_intercept"] == 0.08
        assert row["weight"] == 0.7 and row["min_n_used"] == 100
        print("✓ record_fit persists the raw (unshrunk) fit and shrinkage weight too, not just the final applied slope/intercept — the real audit trail")


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
