import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, props_money as PM, props_engine as PE
from collections import Counter
plays, meta, _ = BBD.build_generic_board("NCAAMB", "2026-11-23", BBD.O.DEFAULT_BOOK)
print("plays", len(plays))
print("use", Counter(p.get("Use") for p in plays))
print("pickem", sum(bool(p.get("Pickem")) for p in plays), "priced", sum(p.get("RealPrice") is not None for p in plays))
print("markets", Counter(p.get("Market") for p in plays).most_common(8))
rows = []
for p in plays:
    e = PM.play_earned("NCAAMB", p); need = PM.needed(p.get("RealPrice"), bool(p.get("Pickem")) or p.get("RealPrice") is None)
    rows.append((p.get("Player"), p.get("Market"), p.get("Side"), p.get("Line"), p.get("RealPrice"), p.get("Pickem"), round(p.get("ModelProb") or 0, 3), None if e is None else round(e, 3), None if need is None else round(need, 3), p.get("Use")))
rows.sort(key=lambda r: -((r[7] or 0) - (r[8] or 1)))
for r in rows[:15]: print(r)
import shutoff as SO
print("shutoff", {m: SO.is_off("NCAAMB", m, "lock") for m in set(p.get("Market") for p in plays)})
