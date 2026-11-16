"""Two-week watch on PR #21: Anytime TD 'Yes' reads under 50% that clear their price by +3% (new 200-touch model)."""
import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG

def dec(p):
    p = float(p); return 1 + (p / 100 if p > 0 else 100 / -p)

allq = []
for d in ("2026-11-08", "2026-11-09", "2026-11-15", "2026-11-16"):
    snaps = [s for s in MS.load_snapshots("NFL", [d]) if str(s.get("market")).lower() == "anytime td"]
    latest = {}
    for s in snaps:
        if str(s.get("ts")) > str(latest.get(s.get("player"), {}).get("ts")):
            latest[s.get("player")] = s
    q = []
    for s in latest.values():
        if s.get("side") not in ("Over", "Yes") or s.get("chance") is None or s.get("over_price") is None:
            continue
        ch, px = float(s["chance"]), float(s["over_price"])
        if ch < 0.5 and ch * dec(px) - 1 >= 0.03:
            q.append(s)
    graded = []
    if q:
        try:
            res = PG.fetch_results("NFL", d, sorted({(s["team"], s["opp"]) for s in q}))
            graded = PG.grade(q, res)
        except Exception as e:
            print(d, "grade error", e)
    print(f"\n== {d}: {len(latest)} TD reads, {len(q)} qualifying Yes<50% & EV>=+3%, graded {len(graded)}")
    for r in sorted(graded, key=lambda r: -float(r["chance"])):
        print(f"  {r['player']:24} {r.get('team')} ch {float(r['chance']):.0%} px {r.get('over_price')} "
              f"EV {float(r['chance'])*dec(r['over_price'])-1:+.2f} actual {r.get('actual')} {r.get('result')} | {r.get('use_tag')} | {str(r.get('flags') or '')[:50]}")
    allq += graded

g = [r for r in allq if r.get("result") in ("win", "loss", "hit", "miss", True, False, 1, 0)]
def won(r): return r.get("result") in ("win", "hit", True, 1)
n, h = len(g), sum(1 for r in g if won(r))
units = sum((dec(r["over_price"]) - 1) if won(r) else -1 for r in g)
exp = sum(float(r["chance"]) for r in g)
print(f"\nTOTAL graded {n}: hits {h}, units {units:+.2f} (1u flat), expected hits {exp:.1f}, "
      f"avg chance {exp/max(n,1):.0%}, hit rate {h/max(n,1):.0%}")
print("results seen:", sorted({str(r.get('result')) for r in allq}))
