import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
picks = MS.load_game_picks("NFL")
print("stored", len(picks), "graded", sum(p.get("final_home") is not None for p in picks))
for p in picks[:6]: print("  PICK", p.get("kickoff"), p.get("away"), "@", p.get("home"), p.get("final_home"))
res = MS.load_results("NFL", since="2026-10-15")
print("results since Oct 15:", len(res), "latest", max((r["date"] for r in res), default=None))
for r in sorted(res, key=lambda r: r["date"])[-4:]: print("  RES", r["date"], r["away_team"], "@", r["home_team"], r["home_points"], r["away_points"])
