import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import football_weather as FW
for sp, d in (("NFL", "2026-11-08"), ("NCAAF", "2026-11-14")):
    sl = FW.slate(sp, d)
    print("WL", sp, d, len(sl), "games")
    for g in sl[:16]:
        print("WL", sorted(g["away"])[:1], "@", sorted(g["home"])[:1], "|", FW.label(g))
