"""Nov 19: why yesterday's NBA props and long shots don't show on Today's best looking back."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, long_shots_scan as LSS, model_store as MS
d = "2026-11-18"
saved = TB.load_props("NBA", d)
print("PP saved", None if not saved else (saved.get("at"), len(saved.get("rows") or [])))
best = TB.collect(d, ["NBA"], past=True)
rows = best.get("rows") or []
print("PP collect rows", len(rows), "props", best.get("props"))
from collections import Counter
print("PP kinds", Counter(r.get("kind") for r in rows), "results", Counter(r.get("result") for r in rows if r.get("kind") == "Prop"))
for r in [r for r in rows if r.get("kind") == "Prop"][:5]:
    print("PP row", {k: r.get(k) for k in ("sport", "pick", "use", "lock", "money", "result", "time")})
ls = LSS.load("NBA", d)
print("PP ls", None if not ls else (ls.get("at"), len(ls.get("rows") or []), [r.get("pick") for r in ls.get("top") or []]))
if ls:
    g = LSS.grade_saved(ls.get("top"), "NBA", d)
    print("PP ls graded", [(r.get("pick"), r.get("Actual"), r.get("Hit")) for r in g])
