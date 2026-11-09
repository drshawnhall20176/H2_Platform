import os, sys
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grading_history as GH, betlog as B
rows = GH.fetch_graded_plays("NBA")
print("CH rows", len(rows), "keys", sorted(rows[0].keys()) if rows else None)
print("CH dates", sorted({r.get("slate_date") for r in rows})[:3], "...", sorted({r.get("slate_date") for r in rows})[-3:], len({r.get("slate_date") for r in rows}))
by = defaultdict(list)
for r in rows:
    by[r.get("market")].append(r)
for mk, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
    g = [r for r in rs if r.get("hit") in (True, False, 1, 0)]
    if not g: 
        print("CH", mk, len(rs), "ungraded"); continue
    hit = sum(1 for r in g if r["hit"] in (True, 1)) / len(g)
    mp = [float(r["model_prob"]) for r in g if r.get("model_prob") is not None]
    print("CH", f"{mk:16s} n={len(g):5d} hit {hit:.1%} avg model {sum(mp)/len(mp) if mp else float('nan'):.1%} sides {dict(Counter(r.get('side') for r in g))}")
    cal = defaultdict(lambda: [0, 0])
    for r in g:
        p = r.get("model_prob")
        if p is None: continue
        b = min(9, int(float(p) * 10))
        cal[b][0] += 1; cal[b][1] += r["hit"] in (True, 1)
    print("CH   cal", " ".join(f"{b*10}-{b*10+10}%:{h}/{n}={h/n:.0%}" for b, (n, h) in sorted(cal.items()) if n >= 10))
# owner's own combo bets
combos = ("Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast", "Blocks+Steals", "Steals", "Blocks")
mine = [b for b in B.list_bets() if b.get("is_real_bet") and b.get("sport") == "NBA" and b.get("market") in combos and B._result(b) in ("win", "loss")]
w = sum(B._result(b) == "win" for b in mine)
print("CH MINE combos", f"{w}-{len(mine)-w}", "singles P/L", round(sum(B.bet_pnl(b) or 0 for b in mine if not B._ticket(b)), 2),
      "by market", dict(Counter((b["market"], B._result(b)) for b in mine)))
