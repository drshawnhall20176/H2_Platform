"""Nov 6: test two NBA rule ideas on what the platform actually recommended (playable Use tags), slate by slate.
R1: an Over read whose projection is 40%+ above the line -> Pass.
R2: weak markets off the playable board -- the weak list chosen WITHOUT the slate being tested (leave-one-slate-out)."""
import os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D, model_store as MS, props_engine as PE

PLAY = (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)


def dec(a):
    a = float(a); return 1 + (a / 100 if a > 0 else 100 / -a)


graded = D.grade_dates("NBA", MS.snapshot_dates("NBA"))
rows, seen = [], set()
for d, recs in graded.items():
    for r in recs:
        if r.get("result") not in ("hit", "miss") or r.get("use_tag") not in PLAY or r.get("price") is None:
            continue
        if r.get("projection") is None or r.get("line") is None:
            continue
        k = (d, r.get("player"), r.get("market"), r.get("side"), r.get("line"))
        if k in seen:
            continue
        seen.add(k)
        r = dict(r, date=d, y=r["result"] == "hit")
        r["gapp"] = (r["projection"] - r["line"]) / max(0.5, r["line"])
        r["pnl"] = (dec(r["price"]) - 1) if r["y"] else -1
        rows.append(r)
dates = sorted({r["date"] for r in rows})
print(f"## {len(rows)} playable NBA reads with a price, {len(dates)} slates")
tot = sum(r["pnl"] for r in rows)
print(f"all playable: hit {sum(r['y'] for r in rows) / len(rows):.1%}, {tot / len(rows):+.1%}/$1")

print("\n## R1: Over reads 40%+ above the line (would become Pass)")
r1 = [r for r in rows if r.get("side") == "Over" and r["gapp"] >= 0.40]
print(f"would remove n={len(r1)}" + (f", hit {sum(r['y'] for r in r1) / len(r1):.1%}, {sum(r['pnl'] for r in r1) / len(r1):+.1%}/$1" if r1 else ""))
for d in dates:
    g = [r for r in r1 if r["date"] == d]
    if g:
        print(f"   {d}: n={len(g)} hit {sum(r['y'] for r in g)}/{len(g)} pnl {sum(r['pnl'] for r in g):+.1f}u")
for th in (0.25, 0.30, 0.40, 0.60):
    g = [r for r in rows if r.get("side") == "Over" and r["gapp"] >= th]
    if g:
        print(f"   Over gap >= {th:.0%}: n={len(g)} hit {sum(r['y'] for r in g) / len(g):.1%} {sum(r['pnl'] for r in g) / len(g):+.1%}/$1")

print("\n## R2: markets, playable reads")
bym = defaultdict(list)
for r in rows:
    bym[r["market"]].append(r)
for m, g in sorted(bym.items(), key=lambda kv: -len(kv[1])):
    per = []
    for d in dates:
        gd = [r for r in g if r["date"] == d]
        if gd:
            per.append(f"{d[5:]}:{sum(r['pnl'] for r in gd):+.1f}u/{len(gd)}")
    print(f"   {m:12s} n={len(g):4d} hit {sum(r['y'] for r in g) / len(g):.1%} {sum(r['pnl'] for r in g) / len(g):+.1%}/$1  | {' '.join(per)}")
print("-- leave-one-slate-out: weak = markets losing 5%+ per $1 (n>=15) on the OTHER slates")
gain = 0.0
helped = hurt = 0
for d in dates:
    tr = [r for r in rows if r["date"] != d]
    te = [r for r in rows if r["date"] == d]
    weak = []
    for m in {r["market"] for r in tr}:
        g = [r for r in tr if r["market"] == m]
        if len(g) >= 15 and sum(r["pnl"] for r in g) / len(g) <= -0.05:
            weak.append(m)
    cut = [r for r in te if r["market"] in weak]
    delta = -sum(r["pnl"] for r in cut)
    gain += delta
    helped += delta > 0
    hurt += delta < 0
    print(f"   {d}: weak {sorted(weak)} -> removes {len(cut)} bets, changes that slate by {delta:+.1f}u")
print(f"R2 held-out total: {gain:+.1f}u; helped {helped} slates, hurt {hurt}")
