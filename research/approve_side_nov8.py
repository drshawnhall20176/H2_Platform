"""Nov 8: approve the per-side factors that passed the held-out test (research/side_calibration_test_nhl_ncaaf.py)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calibration as CAL    # noqa: E402
import model_store as MS     # noqa: E402

print("AP before", {c["sport"]: c["s"] for c in MS.list_calibration()})
ok1 = MS.approve_calibration("NHL:Under", 0.88, {"morning": "2026-11-08", "n": 1471, "fit": 0.88,
                                                "held_out": "beat or tied as-shown in 6 of 6 splits (0.83-0.95)"})
ok2 = MS.approve_calibration("NCAAF:Over", 0.67, {"morning": "2026-11-08", "n": 402, "fit": 0.67,
                                                 "held_out": "Nov 7: singles 15-10 (+11%) vs 21-21 (-7%) as shown"})
CAL.clear_cache()
print("AP approved", ok1, ok2, "| now", {c["sport"]: c["s"] for c in MS.list_calibration()},
      "| NHL", CAL.side_factors("NHL"), "NCAAF", CAL.side_factors("NCAAF"))
