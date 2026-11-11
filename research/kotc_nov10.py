"""Nov 11: King of the Court Nov 10 -- Giannis (owner's pick) vs Franz Wagner (winner). Saved pre-game reads + results."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS     # noqa: E402
import postgame as PG        # noqa: E402

day = "2026-11-10"
snaps = MS.load_snapshots("NBA", [day])
res = PG.fetch_results("NBA", day, sorted({(s["team"], s["opp"]) for s in snaps}))
g = PG.grade(snaps, res)
best = {}
for s in g:
    if s.get("market") in ("Points", "Rebounds", "Assists", "PRA"):
        k = (s["player"], s["market"])
        if k not in best or str(s.get("ts")) > str(best[k].get("ts")):
            best[k] = s
pra = sorted([s for (p, m), s in best.items() if m == "PRA"], key=lambda s: -(s.get("projection") or 0))
print("KC top PRA projections:")
for s in pra[:15]:
    print(f"KC  {s['player']:<26} {s['game']:<40} proj {s['projection']:.1f} line {s['line']} actual {s.get('actual')} "
          f"result {s['result']} min {s.get('proj_opp')} flags {(s.get('flags') or [])[:3]}")
for who in ("Giannis Antetokounmpo", "Franz Wagner"):
    for m in ("Points", "Rebounds", "Assists", "PRA"):
        s = best.get((who, m))
        if s:
            print(f"KC {who} {m}: proj {s['projection']:.1f} line {s['line']} actual {s.get('actual')} {s['result']} "
                  f"ts {s.get('ts')} flags {s.get('flags')}")
print("KC history of the PRA read (every save):")
for s in sorted([s for s in snaps if s.get("market") == "PRA" and s["player"] in ("Giannis Antetokounmpo", "Franz Wagner")],
                key=lambda s: str(s.get("ts"))):
    print(f"KC   {s.get('ts')} {s['player']:<22} proj {s['projection']:.1f} line {s['line']}")
