import sys
from collections import Counter
sys.path.insert(0, ".")
import daily_review as DR, model_store as MS, clv as CLV
for sp in ("NBA", "NCAAF"):
    ds = [d for d in MS.snapshot_dates(sp) if d >= "2026-11-14"]
    g = DR.grade_dates(sp, ds)
    rows = [r for rs in g.values() for r in rs]
    print("CD", sp, len(rows), sorted(rows[0].keys()) if rows else None)
    c = Counter(); fts = Counter()
    for r in rows:
        fts[(bool(r.get("first_ts")), bool(r.get("ts")), r.get("first_ts") == r.get("ts"))] += 1
        c[CLV.pick_clv(r)] += 1
    print("CD", sp, "pick_clv", dict(c), "first_ts/ts/equal", dict(fts))
    raw = MS.load_snapshots(sp, ds[-2:])
    print("CD raw keys", sorted(raw[0].keys()) if raw else None)
