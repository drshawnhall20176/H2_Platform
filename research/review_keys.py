import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
rep = MS.load_daily_review("NBA", "2026-11-09") or {}
tr = rep.get("trend") or {}
print("RK trend keys", list(tr.keys()))
for k, v in tr.items():
    print("RK", k, json.dumps(v, default=str)[:400])
