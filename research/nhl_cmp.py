import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I, model_store as MS, game_picks as GP
res = [g for g in MS.load_results("NHL", since="2025-09-01") if g.get("home_points") is not None]
recs = [r for r in MS.load_game_picks("NHL") if str(r.get("kickoff"))[:10] >= "2026-11-08" and r.get("final_home") is not None and r.get("model_margin") is not None]
lam = I.LEAGUES["NHL"]["lam"]; cache = {}
rows = []
for r in recs:
    ds = str(r["kickoff"])[:10]
    if ds not in cache:
        tr = [g for g in res if g["date"][:10] < ds]
        cache[ds] = I.ratings_weighted(tr, I.decay_weights(tr, ds, "NHL"), lam, I.HFA_PRIOR["NHL"])
    rr = cache[ds]
    h = I.find_team(rr["off"], r["home"], True); a = I.find_team(rr["off"], r["away"], True)
    wf = GP.project(rr, h, a, False)[0] if h and a else None
    act = float(r["final_home"]) - float(r["final_away"])
    rows.append((ds, r["home"], r["away"], float(r["model_margin"]), wf, act, r.get("home_spread"), r.get("kickoff")))
n = len(rows)
print("n", n, "stored bias %+.2f" % (sum(x[3]-x[5] for x in rows)/n),
      "wf bias %+.2f" % (sum((x[4] if x[4] is not None else x[3])-x[5] for x in rows)/n),
      "mean stored margin %+.2f wf %+.2f actual %+.2f" % (sum(x[3] for x in rows)/n, sum((x[4] or 0) for x in rows)/n, sum(x[5] for x in rows)/n))
dup = {}
for x in rows: dup.setdefault((x[0], x[1]), []).append(x)
print("distinct games", len(dup), "dupes", sum(len(v) > 1 for v in dup.values()))
for x in sorted(rows, key=lambda x: -abs(x[3]-(x[4] or x[3])))[:8]: print(x)
