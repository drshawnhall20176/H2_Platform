import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB
want = ("Marquette", "Ball State", "Florida St", "Texas A&M Aggies", "Minnesota Golden")
for r in MS.load_game_picks("NCAAMB", ungraded=True):
    if TB._et_date(r.get("kickoff")) == "2026-11-06" and any(w in r["home"] for w in want):
        print("GID", r["game_id"], "|", r["away"], "@", r["home"], "|", r.get("line_total"), r.get("model_total"))
