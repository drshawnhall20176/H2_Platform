"""Nov 11: what the automatic calibration decided this morning, and why (from the saved review reports)."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS     # noqa: E402

for sp in ("NBA", "NHL", "NCAAF", "NFL"):
    rep = MS.load_daily_review(sp, "2026-11-11") or {}
    cal = rep.get("calibration") or rep.get("cal") or {}
    for d in (cal.get("auto") or []):
        print("AC", sp, json.dumps({k: d.get(k) for k in ("side", "active", "new", "applied", "why", "n", "dates",
                                                            "since")}, default=str))
    for t in (rep.get("auto_tuning") or []):
        print("AT", sp, json.dumps(t, default=str)[:300])
    if not cal:
        print("AC", sp, "keys", list(rep)[:30])
