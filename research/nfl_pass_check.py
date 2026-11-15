"""Would loosening NFL's Pass rule have made money? Graded NFL reads (all saved boards), by the model's edge at the
posted price, by use tag, by market: hit rate and profit at that price."""
import os, sys
from collections import defaultdict
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE
ds = [d for d in MS.snapshot_dates("NFL") if d < "2026-11-15"]
rows = [r for v in D.grade_dates("NFL", ds).values() for r in v if r.get("result") in ("hit", "miss")]
seen = {}
for r in rows:
    k = (r["slate_date"], r.get("player"), r.get("market"), r.get("line"), r.get("side"))
    if k not in seen or str(r.get("ts")) > str(seen[k].get("ts")): seen[k] = r
rows = list(seen.values())
print("graded NFL reads", len(rows), "slates", sorted({r['slate_date'] for r in rows}))
def price(r): return r.get("price") if r.get("price") is not None else (r.get("over_price") if r.get("side") == "Over" else r.get("under_price"))
def tally(name, rs):
    rs = [r for r in rs if price(r) is not None]
    if not rs: return
    w = sum(r["result"] == "hit" for r in rs)
    prof = sum((PE.decimal(price(r)) - 1) if r["result"] == "hit" else -1 for r in rs)
    print(f"  {name:42} n={len(rs):5d} hit {w/len(rs):6.1%} ROI {prof/len(rs):+6.1%}")
print("BY USE TAG"); [tally(t, [r for r in rows if r.get("use_tag") == t]) for t in sorted({r.get("use_tag") for r in rows if r.get("use_tag")})]
print("BY MODEL EDGE AT THE POSTED PRICE (chance x decimal - 1)")
for lo, hi in ((-1, -0.05), (-0.05, 0), (0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 9)):
    tally(f"edge {lo:+.2f} to {hi:+.2f}", [r for r in rows if price(r) is not None and r.get("chance") is not None and lo <= r["chance"] * PE.decimal(price(r)) - 1 < hi])
print("BY CHANCE")
for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 1.0)):
    tally(f"chance {lo:.2f}-{hi:.2f}", [r for r in rows if r.get("chance") is not None and lo <= r["chance"] < hi])
print("BY MARKET (positive edge only)")
by = defaultdict(list)
for r in rows:
    if price(r) is not None and r.get("chance") is not None and r["chance"] * PE.decimal(price(r)) - 1 > 0: by[r["market"]].append(r)
for m, rs in sorted(by.items(), key=lambda kv: -len(kv[1])): tally(m, rs)
print("BY GAP (positive edge)")
for g in sorted({r.get("gap") for r in rows if r.get("gap")}):
    tally(g, [r for r in by_ for by_ in [rows] for r in by_ if r.get("gap") == g and price(r) is not None and r.get("chance") is not None and r["chance"] * PE.decimal(price(r)) - 1 > 0])
