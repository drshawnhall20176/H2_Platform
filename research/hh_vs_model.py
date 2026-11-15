"""Does the NFL Hot Hand Engine point the same way as the props model? Tonight's slate: for every (player, market)
the model read against a book line, which side of the line each tool's number falls on."""
import os, sys
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, nfl_engine as E, nfl_projections as P, nfl_shared_cache as NSC
day = "2026-11-15"
rows, meta = NSC.load_nfl_slate_cached(day, stats_date_str=day) if hasattr(NSC, "load_nfl_slate_cached") else E.build_slate(day)
opps = tuple(sorted({r["Opp"] for r in rows if r.get("Opp")}))
board = P.build_hot_hand_board(rows, {a: E.get_team_allowed_stats(a, day) for a in opps})
print("hot hand rows", len(board))
MK = {"Rush Yards": "Rush Yards", "Receptions": "Receptions", "Receiving Yards": "Receiving Yards", "Pass Yards": "Pass Yards"}
snaps = MS.load_snapshots("NFL", [day])
latest = {}
for s in snaps:
    k = (s.get("player"), s.get("market"))
    if s.get("line") is None or s.get("projection") is None: continue
    if k not in latest or str(s.get("ts")) > str(latest[k].get("ts")): latest[k] = s
agree = Counter(); rows_out = []
for h in board:
    s = latest.get((h["Player"], MK.get(h["Market"])))
    if not s: continue
    L = float(s["line"]); hh = float(h["Hot Hand Score"]); mo = float(s["projection"])
    a = "Over" if hh > L else "Under"; b = "Over" if mo > L else "Under"
    agree[a == b] += 1
    rows_out.append((h["Player"], h["Team"], h["Market"], L, h["Recent Avg"], h["Matchup Factor"], hh, mo, a, b, s.get("side"), s.get("use_tag"), s.get("game")))
n = sum(agree.values())
print(f"same side of the line: {agree[True]}/{n} ({agree[True]/max(n,1):.0%})")
import numpy as np
x = np.array([r[6] for r in rows_out]); y = np.array([r[7] for r in rows_out])
print("correlation of the two numbers", round(float(np.corrcoef(x, y)[0, 1]), 3), "| mean ratio model/hothand", round(float(np.mean(y / np.maximum(x, 0.1))), 3))
by = Counter((r[2], r[8] == r[9]) for r in rows_out)
for mk in MK: print(f"  {mk:16} agree {by[(mk, True)]} disagree {by[(mk, False)]}")
print("\nPIT @ CIN rows")
for r in rows_out:
    if "CIN" in str(r[12]) and "PIT" in str(r[12]):
        print(f"G {r[0]:18} {r[1]} {r[2]:15} line {r[3]:6} | recent {r[4]:6} x {r[5]} = HH {r[6]:6.1f} -> {r[8]:5} | model {r[7]:6.1f} -> {r[9]:5} | model read {r[10]} {r[11]}")
print("\nbiggest disagreements (slate)")
for r in sorted(rows_out, key=lambda r: -abs(r[6] - r[7]) / max(r[3], 1))[:12]:
    print(f"D {r[0]:18} {r[2]:15} line {r[3]} HH {r[6]:.1f} model {r[7]:.1f} {r[12]}")
