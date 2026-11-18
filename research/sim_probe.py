import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR
from collections import Counter
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    ds = sorted(MS.snapshot_dates(sp))
    print("DATES", sp, len(ds), ds[:1], ds[-1:])
    if not ds: continue
    g = DR.grade_dates(sp, ds[-3:-1])
    rows = [r for rs in g.values() for r in rs]
    if rows:
        print("KEYS", sp, sorted(rows[0].keys()))
        print("EX", sp, {k: rows[0].get(k) for k in rows[0] if k not in ("values",)})
        print("MK", sp, Counter(r.get("market") for r in rows).most_common(30))
