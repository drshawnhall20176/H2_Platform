import sys, os, math; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I, model_store as MS, game_picks as GP
from datetime import date, timedelta
res = [g for g in MS.load_results("NHL", since="2025-09-01") if g.get("home_points") is not None]
res.sort(key=lambda g: g["date"])
print("results", len(res), res[0]["date"], res[-1]["date"])
lam = I.LEAGUES["NHL"]["lam"]; sd = I.LEAGUES["NHL"]["sd"]
recs = {(str(r.get("kickoff"))[:10], r.get("home")): r for r in MS.load_game_picks("NHL")}
variants = {"current 0.25/200": (0.25, 200.0), "0.25/2000": (0.25, 2000.0), "0.25/20000": (0.25, 20000.0),
            "0.15/20000": (0.15, 20000.0), "0.35/20000": (0.35, 20000.0)}
for name, pr in variants.items():
    errs, ll, ae, hf, ml = [], 0.0, 0.0, [], [0, 0.0]
    d = date(2026, 10, 25)
    while d <= date(2026, 11, 22):
        ds = d.isoformat()
        today = [g for g in res if g["date"][:10] == ds]
        if today:
            train = [g for g in res if g["date"][:10] < ds]
            r = I.ratings_weighted(train, I.decay_weights(train, ds, "NHL"), lam, pr)
            hf.append(r["hfa"])
            for g in today:
                h, a = g["home_team"], g["away_team"]
                if h not in r["off"] or a not in r["off"]: continue
                m, t = GP.project(r, h, a, str(g.get("neutral_site")).lower() in ("true", "1"))
                act = float(g["home_points"]) - float(g["away_points"])
                errs.append(m - act); ae += abs(m - act)
                p = min(max(I.win_prob(m, league="NHL"), 1e-4), 1 - 1e-4)
                ll += -math.log(p if act > 0 else 1 - p)
        d += timedelta(days=1)
    n = len(errs); mu = sum(errs) / n; se = (sum((e - mu) ** 2 for e in errs) / (n - 1)) ** 0.5 / n ** 0.5
    print(f"{name:18s} n {n} bias {mu:+.2f}±{se:.2f} MAE {ae/n:.3f} logloss {ll/n:.4f} fitted hfa avg {sum(hf)/len(hf):.2f} last {hf[-1]:.2f}")
