import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections, daily_review as DR, model_store as MS, props_money as PM
cf_all = PM.coefs()
print("fits per sport:", {k: sorted(v.keys())[:12] for k, v in cf_all.items()})
for sp in ("NBA","NHL","NFL","NCAAF","NCAAMB"):
    days = [d for d in MS.snapshot_dates(sp) if "2026-11-15" <= d < "2026-11-22"]
    g = DR.grade_dates(sp, days)
    rows = [r for rs in g.values() for r in rs if r.get("result") in ("hit","miss") and r.get("chance") is not None]
    by = collections.defaultdict(lambda: [0,0.0,0])
    for r in rows:
        side = r.get("side"); pm = r.get("p_market")
        pm_side = None if pm is None else (float(pm) if side == "Over" else 1-float(pm))
        try: e = PM.earned(sp, r.get("market"), side, float(r["chance"]), pm_side)
        except Exception: e = None
        if e is None: continue
        k = (side, "priced" if pm_side is not None else "pickem")
        by[k][0]+=1; by[k][1]+=e; by[k][2]+= r["result"]=="hit"
    print(sp, {f"{s}/{t}": f"earned {v[1]/v[0]:.1%} hit {v[2]/v[0]:.1%} n={v[0]}" for (s,t),v in by.items() if v[0]>=30})
