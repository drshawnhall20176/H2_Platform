"""Nov 17: bet-tagged Overs underperform Unders. Where should the Over bar sit? Profit per $1 by chance floor."""
import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR, props_engine as PE
def dec(p):
    p = float(p); return 1 + (p / 100 if p > 0 else 100 / -p)
for sp in ("NBA", "NFL", "NCAAF", "NHL"):
    days = 63 if sp in ("NFL", "NCAAF") else 30
    cut = (date.fromisoformat("2026-11-17") - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sp) if cut <= d < "2026-11-17"]
    g = DR.grade_dates(sp, ds)
    rows = [r for rs in g.values() for r in rs if r.get("result") in ("hit", "miss")
            and PE.norm_use(r.get("use_tag")) in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)]
    for side in ("Over", "Under"):
        for floor in (0.0, 0.55, 0.58, 0.60, 0.62, 0.65):
            s = [r for r in rows if r.get("side") == side and float(r.get("chance") or 0) >= floor]
            pr = [r for r in s if (r.get("over_price") if side == "Over" else r.get("under_price")) is not None]
            u = sum((dec(r["over_price"] if side == "Over" else r["under_price"]) - 1) if r["result"] == "hit" else -1 for r in pr)
            if s:
                print(f"B {sp} {side:5} chance>={floor:.2f} n {len(s):4} hit {sum(r['result']=='hit' for r in s)/len(s):.1%} "
                      f"said {sum(float(r.get('chance') or 0) for r in s)/len(s):.1%} profit/$1 {u/max(len(pr),1):+.1%} (priced {len(pr)})")
