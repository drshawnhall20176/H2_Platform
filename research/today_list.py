import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, model_store as MS
rows = TB.winner_rows("2026-11-23", leagues=["NCAAMB"], past=True)
for r in rows:
    f = r.get("_full") or {}
    print("ROW", r.get("time"), "|", r.get("game"), "|", f.get("kickoff"), "|", f.get("final_home"), f.get("final_away"), f.get("result"))
res = [g for g in MS.load_results("NCAAMB", since="2026-11-23")]
print("RESULTS on 11/23:", len(res), [ (g["away_team"], g["home_team"], g["away_points"], g["home_points"]) for g in res][:40])
