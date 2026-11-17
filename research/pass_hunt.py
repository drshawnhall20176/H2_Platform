"""Nov 17: are winners hiding in the Pass pile? Segment 30 days of graded ⛔ Pass reads by sport x market x side (and
by distance from the line); keep segments that hit well in BOTH halves of the window and make money at their prices."""
import os, sys
from collections import defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR

def dec(p):
    p = float(p); return 1 + (p / 100 if p > 0 else 100 / -p)
morning = "2026-11-17"
for sport in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    days = 63 if sport in ("NFL", "NCAAF") else 30
    cut = (date.fromisoformat(morning) - timedelta(days=days)).isoformat()
    ds = sorted(d for d in MS.snapshot_dates(sport) if cut <= d < morning)
    if not ds: continue
    g = DR.grade_dates(sport, ds)
    mid = ds[len(ds) // 2]
    seg = defaultdict(lambda: [[0, 0, 0.0], [0, 0, 0.0]])
    tot = [0, 0]
    for d, rs in g.items():
        for r in rs:
            if r.get("result") not in ("hit", "miss") or "Pass" not in str(r.get("use_tag") or ""): continue
            side = r.get("side"); price = r.get("over_price") if side == "Over" else r.get("under_price")
            if price is None: continue
            y = r["result"] == "hit"; u = dec(price) - 1 if y else -1.0
            tot[0] += 1; tot[1] += y
            try:
                gap = abs(float(r["projection"]) - float(r["line"])) / max(float(r["line"]), 0.5)
            except (TypeError, ValueError, KeyError):
                gap = 0
            gb = "far" if gap >= 0.15 else "near"
            half = 0 if d < mid else 1
            for key in ((r.get("market"), side, "all"), (r.get("market"), side, gb)):
                s = seg[key][half]; s[0] += 1; s[1] += y; s[2] += u
    print(f"\n{sport}: {tot[0]} graded Pass reads, model side hit {tot[1]/max(tot[0],1):.1%}")
    found = []
    for k, (a, b) in seg.items():
        n = a[0] + b[0]
        if a[0] < 25 or b[0] < 25: continue
        ra, rb = a[2] / a[0], b[2] / b[0]
        if ra > 0.03 and rb > 0.03:
            found.append((k, n, (a[1] + b[1]) / n, (a[2] + b[2]) / n, ra, rb))
    for k, n, hr, roi, ra, rb in sorted(found, key=lambda x: -x[3])[:10]:
        print(f"  HOLDS {k[0]:18} {k[1]:5} {k[2]:4} n {n:4} hit {hr:.1%} profit/$1 {roi:+.1%} (1st half {ra:+.1%}, 2nd half {rb:+.1%})")
    if not found: print("  no segment made money in both halves")
