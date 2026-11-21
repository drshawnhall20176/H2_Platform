import sys, traceback
sys.path.insert(0, ".")
import daily_review as DR, model_store as MS, clv as CLV, shutoff as SO, props_engine as PE
ds = [d for d in MS.snapshot_dates("NBA") if d >= "2026-11-10"]
rows = [r for rs in DR.grade_dates("NBA", ds).values() for r in rs]
locks = [r for r in rows if PE.is_lock(r.get("chance"), r.get("cushion"), r.get("gap"), r.get("book"), ev=r.get("ev"))]
print("CE locks", len(locks))
for r in locks[:5]:
    try:
        print("CE", r.get("side"), r.get("first_ts"), r.get("ts"), r.get("first_line"), r.get("line"), CLV.pick_clv(r))
    except Exception:
        print("CE ERR", traceback.format_exc()[-300:])
out = SO.score_props("NBA", rows)
for k, v in out.items():
    print("CE", k, v)
