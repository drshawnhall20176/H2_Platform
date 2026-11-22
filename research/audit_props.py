import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections, math, daily_review as DR, model_store as MS
from datetime import date, timedelta
since = (date(2026,11,22) - timedelta(days=30)).isoformat()
for sp in ("NBA","NHL","NFL","NCAAF","NCAAMB"):
    days = [d for d in MS.snapshot_dates(sp) if since <= d < "2026-11-22"]
    try: g = DR.grade_dates(sp, days)
    except Exception as e: print(sp, "grade failed", e); continue
    rows = [r for rs in g.values() for r in rs if r.get("result") in ("hit","miss") and r.get("chance") is not None]
    if not rows: print(sp, "no graded reads"); continue
    def line(rs):
        n=len(rs); said=sum(float(r["chance"]) for r in rs)/n; hit=sum(r["result"]=="hit" for r in rs)/n
        se=(hit*(1-hit)/n)**.5; return n, said, hit, se
    n,s,h,se=line(rows); print(f"{sp}: {n} graded reads, model said {s:.1%} hit {h:.1%} (gap {h-s:+.1%} ±{se:.1%}) over {len(days)} days")
    by=collections.defaultdict(list)
    for r in rows: by[(r.get("market"), r.get("side"))].append(r)
    flagged=[]
    for k, rs in by.items():
        if len(rs) < 150: continue
        n,s,h,se=line(rs)
        if abs(h-s) > 2.5*se and abs(h-s) >= 0.04: flagged.append((h-s, k, n, s, h, se))
    sides=collections.defaultdict(list)
    for r in rows: sides[r.get("side")].append(r)
    print("   by side:", {k: f"said {line(v)[1]:.1%} hit {line(v)[2]:.1%} n={len(v)}" for k,v in sides.items() if len(v)>=50})
    for d,k,n,s,h,se in sorted(flagged)[:6] + sorted(flagged)[-6:]:
        print(f"   MISJUDGED {k}: n={n} said {s:.1%} hit {h:.1%} ({d:+.1%} ±{se:.1%})")
    # shown picks: what members actually saw (strongest + money), earned chance vs hit
import pick_ledger as PL
for kind, sps in (("strong",("ALL",)),("money",("NBA","NHL","NFL","NCAAF","NCAAMB"))):
    rs=[]
    for sp in sps:
        for d in ("2026-11-20","2026-11-21"):
            rs += [r for r in PL.rows(kind, sp, d) if r.get("result") in ("win","loss") and (r.get("earned") or r.get("chance")) is not None]
    if rs:
        said=sum(float(r.get("earned") or r.get("chance")) for r in rs)/len(rs); hit=sum(r["result"]=="win" for r in rs)/len(rs)
        print(f"SHOWN {kind}: n={len(rs)} said {said:.1%} hit {hit:.1%}")
