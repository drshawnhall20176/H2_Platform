import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sports
eng = sports.get("NCAAF").engine
res = eng.get_player_results("2026-11-21")
k = next(iter(res)); print("result sample", k, res[k])
sch = eng.get_schedule(2026)
g = [x for x in sch if "Miami" in str(x.get("home_team") or x.get("home_name")) or "Stanford" in str(x.get("away_team") or x.get("away_name"))]
for x in g[-3:]: print("sched", x)
