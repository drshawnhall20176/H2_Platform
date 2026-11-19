import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import long_shots_scan as LSS
for sp in ("NBA", "NFL"):
    for d in ("2026-11-18", "2026-11-16"):
        r = LSS.rebuild_past(sp, d)
        print("LR", sp, d, "games", r["games"], "rows", len(r["rows"]), "hits", sum(x.get("Hit") == "✅" for x in r["rows"]))
        for t in r["top"]:
            print("LR   top", t["pick"], t.get("Price"), f"{t['Honest chance']:.0%}", t.get("Actual"), t.get("Hit"), t.get("time"))
