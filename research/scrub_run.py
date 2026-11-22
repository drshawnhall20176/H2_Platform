import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_picks as IP, pick_records as PRK, tennis_calibration as TC, model_store as MS
print("DRY:", IP.rescore_history("NCAAMB", "2026-11-01", save=lambda p: None))
before = PRK.lean_records("NCAAMB", days=30)
print("lean records BEFORE:", {k: v for k, v in before.items() if isinstance(k, str)})
print("calibration k BEFORE:", TC.current_k(sport="NCAAMB"))
print("WRITE:", IP.rescore_history("NCAAMB", "2026-11-01"))
after = PRK.lean_records("NCAAMB", days=30)
print("lean records AFTER:", {k: v for k, v in after.items() if isinstance(k, str)})
d = TC.auto(sport="NCAAMB")
print("calibration refit:", d)
import money_score as MSC
try:
    print("money score refit:", MSC.refit() if hasattr(MSC, "refit") else "n/a")
except Exception as e: print("money score refit failed", e)
