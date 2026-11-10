import os, sys, json
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, pick_records as PR
snaps = MS.load_snapshots("NBA", ["2026-11-09"])
print("CK NBA snapshot markets", Counter(s.get("market") for s in snaps).most_common())
mc = PR.market_counts("NBA")
print("CK NBA graded per market (30d)", {k: mc.get(k) for k in ("Points", "Rebounds", "Assists", "Threes Made", "PRA", "PR", "PA", "RA")})
for sp in ("NFL", "NBA", "NHL", "NCAAF"):
    rows = MS.load_calibration_history(sp) if hasattr(MS, "load_calibration_history") else None
    print("CK cal", sp, str(rows)[:300] if rows else MS.active_calibration(sp) if hasattr(MS, "active_calibration") else "")
for sp in ("NFL", "NCAAF", "NBA", "NHL"):
    got = MS.get_setting(f"script_learn:{sp}")
    d = json.loads(got) if isinstance(got, str) else (got or {})
    print("CK script_learn", sp, "games", d.get("games"), "groups", len(d.get("effects") or {}))
