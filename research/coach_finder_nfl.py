import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, betlog as B, coach as CO, pick_records as PR, todays_best as TB
day = "2026-11-08"
plays, meta, _ = BBD.load_generic_best_bets_board("NFL", day, BBD.O.DEFAULT_BOOK)
c = CO.prop_candidates("NFL", plays, meta)
rows = [r for r in TB.winner_rows(day) if r.get("sport") == "NFL"]
PR.annotate_leans(rows); c += CO.lean_candidates(rows)
out = CO.finder(c, B.list_bets(), PR.tag_records("NFL"))
print("CF total", len(out), Counter(r["verdict"] for r in out), Counter(r["time"] for r in out))
for r in out:
    if not r["verdict"].startswith("🔴"):
        print("CF", r["verdict"], r["time"], r["game"], "|", r["pick"], r.get("price"), "| model", r.get("model_chance"), "real", r.get("real_chance"), "edge", r.get("edge"), "|", r["use"], "|", r["why"][:200])
why = Counter(r["why"].split(";")[0][:60] for r in out if r["verdict"].startswith("🔴"))
print("CF skip reasons", why.most_common(8))
