"""Nov 19: 💰 money picks night by night (all band reads, and the top 8 by edge that Today's best shows)."""
import os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG, props_engine as PE
dates = MS.snapshot_dates("NBA"); snaps = MS.load_snapshots("NBA", dates)
by = defaultdict(list)
for d in sorted({s["slate_date"] for s in snaps}):
    day = [s for s in snaps if s["slate_date"] == d]
    try:
        g = PG.grade(day, PG.fetch_results("NBA", d, sorted({(s["team"], s["opp"]) for s in day})))
    except Exception:
        continue
    for r in g:
        if r.get("result") not in ("hit", "miss") or not PE.decimal(r.get("price")):
            continue
        if PE.in_money_band("NBA", r.get("ev"), r.get("book"), market=r.get("market")):
            by[d].append(r)
def stat(rs):
    h = sum(r["result"] == "hit" for r in rs)
    pr = sum((PE.decimal(r["price"]) - 1) if r["result"] == "hit" else -1 for r in rs)
    need = sum(1 / PE.decimal(r["price"]) for r in rs) / len(rs)
    return h, len(rs) - h, pr, need
tot = [0, 0, 0.0]; tot8 = [0, 0, 0.0]
for d in sorted(by):
    rs = by[d]
    h, m, pr, need = stat(rs)
    top = sorted(rs, key=lambda r: -(r.get("ev") or 0))
    seen, t8 = set(), []
    for r in top:
        if r["player"] in seen: continue
        seen.add(r["player"]); t8.append(r)
        if len(t8) == 8: break
    h8, m8, pr8, _ = stat(t8)
    for a, b in ((tot, (h, m, pr)), (tot8, (h8, m8, pr8))):
        a[0] += b[0]; a[1] += b[1]; a[2] += b[2]
    print(f"MD {d} all {h}-{m} ({h/(h+m):.0%}, needed {need:.0%}) {pr:+.1f}u | top8 {h8}-{m8} {pr8:+.1f}u")
print(f"MD total all {tot[0]}-{tot[1]} {tot[2]:+.1f}u ({tot[2]/(tot[0]+tot[1]):+.1%}) | top8 {tot8[0]}-{tot8[1]} {tot8[2]:+.1f}u ({tot8[2]/(tot8[0]+tot8[1]):+.1%})")
