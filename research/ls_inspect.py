import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import long_shots_scan as LSS
v = LSS.load("NBA", "2026-11-14")
for r in v["rows"][:25]:
    print("ROW", {k: r.get(k) for k in ("Player", "Bet", "Price", "Book says", "Model raw", "Honest chance", "EV per $1", "Projection", "Main line", "Flags", "game")})
