import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pick_records as PR
for lg in ("NCAAF", "NCAAMB", "NBA", "NHL"):
    g = PR.lean_records(lg)
    print(lg, {k: v for k, v in g.items() if isinstance(k, str)})
    for k, (w, n) in sorted((k, v) for k, v in g.items() if isinstance(k, tuple)):
        print("   ", k[0], PR.band_label(k[1], k[0], lg), f"{w}-{n-w}", f"{w/n:.0%}" if n else "")
