"""Nov 18: same-player legs where one market contains the other (Points & PRA, NHL Points & Goals) vs unrelated pairs."""
import math, os, sys
from collections import defaultdict
from datetime import date
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE
def tet(a, b, c, d):
    if min(a, b, c, d) <= 0: return None
    return math.cos(math.pi / (1 + math.sqrt(a * d / (b * c))))
NEST = {"NBA": {"PRA": {"Points", "Rebounds", "Assists", "PR", "PA", "RA"}, "PR": {"Points", "Rebounds"}, "PA": {"Points", "Assists"}, "RA": {"Rebounds", "Assists"}},
        "NHL": {"Points": {"Goals", "Assists"}}, "NFL": {"Rush + Rec Yards": {"Rush Yards", "Receiving Yards"}}}
for sp in ("NBA", "NHL", "NFL", "NCAAF"):
    ds = [d for d in MS.snapshot_dates(sp) if d < date.today().isoformat()]
    rows = [r for recs in D.grade_dates(sp, ds).values() for r in recs if r.get("actual") is not None and r.get("line") is not None]
    seen = {}
    for r in rows: seen[(r["slate_date"], r["game"], r.get("player"), r.get("market"))] = r
    byp = defaultdict(list)
    for r in seen.values(): byp[(r["slate_date"], r.get("player"))].append(r)
    cells = defaultdict(lambda: [0, 0, 0, 0])
    for grp in byp.values():
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                ma, mb = a["market"], b["market"]
                nest = mb in NEST.get(sp, {}).get(ma, set()) or ma in NEST.get(sp, {}).get(mb, set())
                kind = "nested" if nest else ("both combos" if ma in NEST.get(sp, {}) and mb in NEST.get(sp, {}) else "unrelated")
                oa = a["actual"] > PE.threshold(float(a["line"])); ob = b["actual"] > PE.threshold(float(b["line"]))
                for k in (kind, f"{kind}: {min(ma, mb)} & {max(ma, mb)}"):
                    c = cells[k]; c[0 if oa and ob else 1 if oa else 2 if ob else 3] += 1
    for k, c in sorted(cells.items()):
        n = sum(c)
        if n >= 150 and (":" not in k or n >= 300):
            print(f"RN {sp} {k:40} pairs {n:6d} rho {tet(*c) if tet(*c) is not None else float('nan'):+.3f}")
