"""Nov 12: run the automatic tennis calibration once now (the morning review does it daily from tomorrow)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tennis_calibration as TC      # noqa: E402
import model_store as MS             # noqa: E402

rs = TC.rows(MS.load_game_picks("TENNIS"))
print("TK graded", len(rs), "days", len({r["day"] for r in rs}), "best k on all", TC.fit(rs))
print("TK holdout vs 1.00", TC.holdout(rs, 1.0))
d = TC.auto(write=True)
print("TK decision", d)
print("TK now", TC.current_k(), "-> model 60/70/75/80/90% read",
      [round(TC.shrink(p, TC.current_k()), 3) for p in (0.6, 0.7, 0.75, 0.8, 0.9)])
