"""Nov 6: NBA -- when the model disagreed with the book, who was right, and did following the model pay?"""
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
        if r.get("actual") is None or r.get("line") is None or r.get("projection") is None:
            continue
        if float(r["actual"]) == float(r["line"]) or float(r["projection"]) == float(r["line"]):
            continue
        k = (d, r.get("player"), r.get("market"), r.get("line"))
        if k in seen:
            continue
        seen.add(k); rows.append(dict(r, date=d))
for r in rows:
    r["m_over"] = r["projection"] > r["line"]
    r["a_over"] = r["actual"] > r["line"]
    r["gapp"] = abs(r["projection"] - r["line"]) / max(0.5, r["line"])
    if r.get("over_price") and r.get("under_price"):
        po, pu = 1 / dec(r["over_price"]), 1 / dec(r["under_price"])
        r["b_over_p"] = po / (po + pu)
        r["b_over"] = r["b_over_p"] > 0.5
    r["model_side_price"] = (r.get("over_price") if r["m_over"] else r.get("under_price"))


def pay(g, side_over_key):
    pr = [r for r in g if (r.get("over_price") if r[side_over_key] else r.get("under_price"))]
    if not pr:
        return None, 0
    tot = 0
    for r in pr:
        price = r["over_price"] if r[side_over_key] else r["under_price"]
        tot += (dec(price) - 1) if r[side_over_key] == r["a_over"] else -1
    return tot / len(pr), len(pr)


print(f"## NBA: {len(rows)} graded props over {len(graded)} slates")
right = sum(1 for r in rows if r["m_over"] == r["a_over"]) / len(rows)
print(f"Model's side (projection vs line) right {right:.1%} overall; model said Over on {sum(r['m_over'] for r in rows) / len(rows):.0%}")
print("\n## 1. Sides: books' prices favor one side, model's projection the other")
two = [r for r in rows if "b_over" in r]
agree = [r for r in two if r["m_over"] == r["b_over"]]
dis = [r for r in two if r["m_over"] != r["b_over"]]
for lab, g in (("agree", agree), ("DISAGREE", dis)):
    if not g:
        continue
    m = sum(1 for r in g if r["m_over"] == r["a_over"]) / len(g)
    p, n = pay(g, "m_over")
    print(f"{lab:9s} n={len(g):4d} ({len(g) / len(two):.0%})  model right {m:.1%}  book right {1 - m:.1%}  "
          f"following the model {p:+.1%}/$1 (n={n})")
if dis:
    for side in (True, False):
        g = [r for r in dis if r["m_over"] == side]
        if g:
            m = sum(1 for r in g if r["m_over"] == r["a_over"]) / len(g)
            p, n = pay(g, "m_over")
            print(f"   model Over/book Under" if side else "   model Under/book Over", f"n={len(g)} model right {m:.1%} pay {p:+.1%}")
print("\n## 2. Gap: |projection - line| / line")
for lo, hi in [(0, .05), (.05, .10), (.10, .15), (.15, .25), (.25, .40), (.40, 9)]:
    g = [r for r in rows if lo <= r["gapp"] < hi]
    if not g:
        continue
    m = sum(1 for r in g if r["m_over"] == r["a_over"]) / len(g)
    p, n = pay(g, "m_over")
    uo = sum(1 for r in g if r["m_over"]) / len(g)
    ps = "—" if p is None else f"{p:+.1%}"
    print(f"gap {lo:4.0%}-{hi:4.0%}: n={len(g):4d} model right {m:.1%}  (model said Over {uo:.0%})  following it {ps}/$1 (n={n})")
    for side in (True, False):
        gs = [r for r in g if r["m_over"] == side]
        if len(gs) >= 20:
            ms = sum(1 for r in gs if r["m_over"] == r["a_over"]) / len(gs)
            ps2, n2 = pay(gs, "m_over")
            print(f"        {'Over ' if side else 'Under'} n={len(gs):4d} right {ms:.1%} pay {'—' if ps2 is None else f'{ps2:+.1%}'} (n={n2})")
print("\n## 3. By market, gap 15%+")
by = defaultdict(list)
for r in rows:
    if r["gapp"] >= .15:
        by[r["market"]].append(r)
for mk, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
    m = sum(1 for r in g if r["m_over"] == r["a_over"]) / len(g)
    p, n = pay(g, "m_over")
    print(f"   {mk:14s} n={len(g):4d} model right {m:.1%} pay {'—' if p is None else f'{p:+.1%}'} (n={n})")
