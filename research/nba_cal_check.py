import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for sp in ("NBA", "NHL", "NCAAF", "NFL"):
    r = MS.load_daily_review(sp, "2026-11-14") if hasattr(MS, "load_daily_review") else None
    cal = (r or {}).get("calibration") or {}
    print(sp, "by_side:", json.dumps(cal.get("by_side"), default=str)[:500])
    print(sp, "side_active:", cal.get("side_active"))
    for d in cal.get("auto") or []:
        print(sp, "AUTO", {k: d.get(k) for k in ("side", "active", "new", "n", "dates", "splits", "passed", "gain", "applied", "why", "since")})
