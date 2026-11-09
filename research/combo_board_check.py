import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, coach as CO
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", "2026-11-09", BBD.O.DEFAULT_BOOK)
c = Counter((p.get("Market"), p.get("Use") or "untagged") for p in plays)
for k, v in sorted(c.items(), key=str): print("CB", k, v)
for mk in ("Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast"):
    ps = [p for p in plays if p.get("Market") == mk and p.get("ModelProb") is not None]
    if ps:
        mp = [float(p["ModelProb"]) for p in ps]
        print("CB", mk, "n", len(ps), "avg chance", round(sum(mp) / len(mp), 3), "max", round(max(mp), 3),
              "sample", [(p["Player"], p["Side"], p["Line"], p.get("RealPrice"), round(float(p["ModelProb"]), 3), p.get("Use")) for p in sorted(ps, key=lambda p: -float(p["ModelProb"]))[:3]])
