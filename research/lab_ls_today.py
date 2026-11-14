import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab_long_shots as L
print("scorers:", L.run_scorers("2026-11-14", force=True))
for k, v in L.collect("2026-11-14").items():
    print(f"== {k}: {v['n']} {v['kind']}")
    for r in v["top"]:
        print(f"  {r['time']:>9} {r['league'][:22]:22} {r['game'][:44]:44} {r['pick'][:34]:34} {int(r['Price']):+d} {r['chance']:.0%} EV {r['EV per $1']:+.2f}")
import todays_best as TB
print("soccer leans:", len(TB.soccer_rows("2026-11-14")), "flags:", len(TB.soccer_flags("2026-11-14")))
w = TB.winner_rows("2026-11-14")
print("intl leans:", sum(r["sport"] == "INTL" for r in w), "tennis:", sum(r["sport"] == "TENNIS" for r in w))
