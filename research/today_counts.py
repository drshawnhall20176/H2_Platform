import os, sys
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, customer_today as CT, pick_records as PR, model_store as MS
day = "2026-11-17"
w = TB.winner_rows(day)
print("WINNER rows by sport", Counter(r["sport"] for r in w))
print("with best", Counter(r["sport"] for r in w if r.get("best")))
lp = CT.line_picks(w)
print("LINE picks", Counter(r["Sport"] for r in lp))
recs = MS.load_game_picks("NCAAMB", ungraded=True)
print("NCAAMB ungraded recs", len(recs), Counter(str(r.get("kickoff"))[:10] for r in recs).most_common(5))
b = TB.collect(day, ["NBA", "NHL", "NCAAF", "NCAAMB", "NFL"])
print("PROP rows", Counter(r["sport"] for r in b["rows"] if r.get("kind") == "Prop"))
pp = CT.prop_picks(b["rows"])
print("PROP picks", Counter(r["Sport"] for r in pp))
