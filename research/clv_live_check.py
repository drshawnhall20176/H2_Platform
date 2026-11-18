import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for sp in ("NBA", "NHL", "NCAAMB"):
    rs = MS.load_snapshots(sp, ["2026-11-18"])
    n = len(rs)
    print("CL", sp, "rows", n, "first_ts", sum(1 for r in rs if r.get("first_ts")), "bet_ts", sum(1 for r in rs if r.get("bet_ts")),
          "tags", dict(Counter(r.get("use_tag") for r in rs).most_common(5)), "markets", len({r.get("market") for r in rs}))
    st = [r for r in rs if r.get("market") in ("Steals", "Blocks", "Blocks+Steals")]
    if sp == "NBA": print("CL NBA steals/blocks rows", len(st))
