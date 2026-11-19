"""Nov 19: why NCAAMB props on yesterday's Today's best mostly show no result."""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, postgame as PG, todays_best as TB
d = "2026-11-18"
snaps = MS.load_snapshots("NCAAMB", [d])
print("NG snaps", len(snaps), Counter(s.get("game") for s in snaps).most_common(8))
print("NG sample", [(s["player"], s["team"], s["opp"], s["market"]) for s in snaps[:5]])
saved = TB.load_props("NCAAMB", d)
rows = (saved or {}).get("rows") or []
print("NG saved rows", len(rows), Counter(r.get("game") for r in rows).most_common(8))
snap_players = {(s["player"], s["market"]) for s in snaps}
print("NG saved rows with a snapshot", sum((r.get("player"), r.get("market")) in snap_players for r in rows))
games = sorted({(s["team"], s["opp"]) for s in snaps})
res = PG.fetch_results("NCAAMB", d, games)
print("NG games", len(games), "boxes found", len(res), "final", sum(1 for b in res.values() if b.get("final")))
print("NG missing", [g for g in games if g not in res][:10])
g = PG.grade(snaps, res)
print("NG grade", Counter(r["result"] for r in g))
pr = TB.prop_results("NCAAMB", d)
print("NG prop_results", len(pr))
for r in rows[:12]:
    k = (TB.PE.norm_name(r.get("player") or ""), r.get("market"), r.get("side"), float(r["line"]) if r.get("line") is not None else None)
    print("NG row", r.get("pick"), "|", r.get("game"), "| result", pr.get(k))
