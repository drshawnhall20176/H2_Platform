import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, model_store as MS
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", "2026-11-09", BBD.O.DEFAULT_BOOK)
c = Counter((p.get("Market"), "tagged" if p.get("Use") else "untagged") for p in plays)
for k, v in sorted(c.items()): print("CS board", k, v)
print("CS sample untagged", {k: v for k, v in next(p for p in plays if not p.get("Use")).items() if not isinstance(v, (list, dict))})
snaps = MS.load_snapshots("NBA", ["2026-11-08"])
print("CS snapshot markets", Counter(s.get("market") for s in snaps).most_common())
