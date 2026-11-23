import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
for sp in ("NBA", "NHL", "NCAAMB", "NFL"):
    for d in ("2026-11-22", "2026-11-23"):
        b = TB.load_props(sp, d) or {}
        print(sp, d, "rows", len(b.get("rows") or []), "saved_at", b.get("saved_at") or b.get("at") or list(b.keys())[:6])
