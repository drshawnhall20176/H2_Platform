"""Nov 6: NBA -- how often did players go Over the BOOK's line, and were the books' Over prices honest?"""
import os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D, model_store as MS


def dec(a):
    a = float(a); return 1 + (a / 100 if a > 0 else 100 / -a)


graded = D.grade_dates("NBA", MS.snapshot_dates("NBA"))
rows, seen = [], set()
for d, recs in graded.items():
    for r in recs:
        if r.get("actual") is None or r.get("line") is None:
            continue
        k = (d, r.get("player"), r.get("market"), r.get("line"))
        if k in seen:
            continue
        seen.add(k); rows.append(dict(r, date=d))
print("keys:", sorted(rows[0].keys()) if rows else None)
dec_rows = [r for r in rows if float(r["actual"]) != float(r["line"])]
over = sum(1 for r in dec_rows if r["actual"] > r["line"])
print(f"ALL n={len(dec_rows)} slates={len(graded)} went OVER the book line {over / len(dec_rows):.1%}")
by = defaultdict(list)
for r in dec_rows:
    by[r.get("market")].append(r)
for m, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
    o = sum(1 for r in g if r["actual"] > r["line"]) / len(g)
    print(f"   {m:22s} n={len(g):5d} over {o:.1%}")
# book honesty: rows with both prices
both = [r for r in dec_rows if r.get("over_price") and r.get("under_price")]
if both:
    imp = []
    for r in both:
        po, pu = 1 / dec(r["over_price"]), 1 / dec(r["under_price"])
        imp.append(po / (po + pu))
    act = sum(1 for r in both if r["actual"] > r["line"]) / len(both)
    print(f"BOOK n={len(both)} books' fair Over chance (vig removed) {sum(imp) / len(imp):.1%} vs actual Over {act:.1%}")
    # money: bet every Over vs every Under at the posted price
    po = sum((dec(r["over_price"]) - 1) if r["actual"] > r["line"] else -1 for r in both) / len(both)
    pu = sum((dec(r["under_price"]) - 1) if r["actual"] < r["line"] else -1 for r in both) / len(both)
    print(f"MONEY blind Overs {po:+.1%} per $1 | blind Unders {pu:+.1%} per $1")
    for lo, hi in [(0, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 1)]:
        g = [(r, i) for r, i in zip(both, imp) if lo <= i < hi]
        if g:
            print(f"   books said Over {lo:.0%}-{hi:.0%}: n={len(g)} hit {sum(1 for r, _ in g if r['actual'] > r['line']) / len(g):.1%}")
else:
    pm = [r for r in dec_rows if r.get("p_market") is not None]
    print("no two-sided prices; p_market rows:", len(pm))
by_d = defaultdict(list)
for r in dec_rows:
    by_d[r["date"]].append(r)
for d, g in sorted(by_d.items()):
    print(f"   {d}: n={len(g)} over {sum(1 for r in g if r['actual'] > r['line']) / len(g):.1%}")
