import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
import pick_records as PR
for lg in ("NCAAF", "NCAAMB", "NBA", "NHL"):
    recs = MS.load_game_picks(lg)
    print("LR", lg, "30d", PR.lean_records(lg, recs=recs), "| season", PR.lean_records(lg, days=400, recs=recs))
    if lg == "NCAAF":
        agree = Counter()
        for r in recs:
            g = PR.grade_lean(r)["Spread"]
            if r.get("result") in ("win", "loss") and g in ("win", "loss"):
                agree[(r["result"], g)] += 1
        print("LR NCAAF stored result vs grade_lean spread", dict(agree))
        r0 = next(r for r in recs if r.get("result") in ("win", "loss"))
        print("LR sample", {k: r0.get(k) for k in ("home", "away", "line", "model_margin", "pick", "pick_label", "edge", "final_home", "final_away", "result", "line_total", "model_total")})
for sp in ("NBA", "NHL", "NFL", "NCAAF"):
    print("LR TAGS", sp, PR.tag_records(sp))
