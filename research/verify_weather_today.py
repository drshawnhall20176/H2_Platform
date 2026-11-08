import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import football_weather as FW, best_bets_data as BBD
for g in FW.slate("NFL", "2026-11-08"):
    print("VW", sorted(g["away"])[:1], "@", sorted(g["home"])[:1], "| indoor", g["indoor"], "| wind", None if g["wind"] is None else round(g["wind"], 1), "| temp", None if g["temp"] is None else round(g["temp"]))
plays, meta, _ = BBD.load_generic_best_bets_board("NFL", "2026-11-08", BBD.O.DEFAULT_BOOK)
fl = Counter()
for p in plays:
    for f in p.get("Flags") or []:
        if "Weather" in str(f) or "snap share" in str(f):
            fl[str(f).split(":")[0]] += 1
            if fl[str(f).split(":")[0]] <= 3:
                print("VW FLAG", p.get("Game"), p.get("Player"), p.get("Market"), p.get("Side"), p.get("Line"), "|", f)
print("VW counts", dict(fl))
