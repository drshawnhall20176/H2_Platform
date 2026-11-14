import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, game_picks as GP
recs = MS.load_game_picks("NCAAF")
sides = collections.Counter((p.get("pick"), p.get("neutral")) for p in recs if p.get("pick"))
print("pick sides", sides)
edges = [p["model_margin"] - (p.get("close_line") if p.get("close_line") is not None else p["line"]) for p in recs]
print("mean model-minus-line", sum(edges)/len(edges), "n", len(edges))
sch = GP.load_schedule()
done = [g for g in sch if GP._truthy(g.get("completed")) and int(g.get("season") or 0) == 2026]
print("schedule rows", len(sch), "2026 completed", len(done), "latest", max(str(g.get("start_date")) for g in done) if done else None)
r = GP.ratings(done)
print("hfa", r["hfa"], "mu", r["mu"])
# home margin actual in completed games (non-neutral)
hm = [g["home_points"] - g["away_points"] for g in done if not GP._truthy(g.get("neutral_site"))]
print("actual mean home margin", sum(hm)/len(hm), len(hm))
# FBS vs FCS: teams with few games
cnt = collections.Counter([g["home_team"] for g in done] + [g["away_team"] for g in done])
print("teams", len(cnt), "teams<4 games", sum(1 for v in cnt.values() if v < 4))
# realized: model margin minus actual margin, residual by home
res = []
for p in recs:
    if p.get("final_home") is None: continue
    res.append((p["model_margin"] - (p["final_home"] - p["final_away"]), (p.get("close_line") or p["line"]) - (p["final_home"] - p["final_away"])))
print("graded", len(res), "model bias", sum(a for a,_ in res)/len(res), "line bias", sum(b for _,b in res)/len(res))
print("model MAE", sum(abs(a) for a,_ in res)/len(res), "line MAE", sum(abs(b) for _,b in res)/len(res))
print("cols", list(sch[0].keys()) if sch else None)
