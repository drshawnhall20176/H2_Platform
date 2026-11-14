"""Nov 14 -- soccer: does a shots-based expected-goals number make the goals model's ratings predict better than goals
alone? (Goals are a noisy result of the chances a team creates and allows.) Caches each match's team shots (ESPN) to
the archive, fits xG = a*shots on target + b*other shots + c*penalties, then walk-forward by match date: ratings fit on
goals vs xG vs blends, scored on the next matches' 1X2 (log loss) and over 2.5 (Brier)."""
import math, os, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import model_store as MS, soccer_data as D, soccer_model as M

LGS = ["SOCCER_EPL", "SOCCER_LALIGA", "SOCCER_SERIEA", "SOCCER_BUNDESLIGA", "SOCCER_LIGUE1", "SOCCER_MLS",
       "SOCCER_CHAMPIONSHIP", "SOCCER_EREDIVISIE", "SOCCER_PORTUGAL"]
data = {}
for lg in LGS:
    res = [g for g in MS.load_results(lg) if g.get("home_points") is not None]
    ts = D.cache_team_stats(lg, res, limit=2000)
    data[lg] = (res, ts)
    print(f"{lg}: {len(res)} results, team shots for {sum(1 for g in res if str(g['id']) in ts)}")

X, y = [], []
for res, ts in data.values():
    for g in res:
        t = ts.get(str(g["id"]))
        if not t: continue
        for side, goals in (("home", g["home_points"]), ("away", g["away_points"])):
            s = t[side]; X.append([s["sot"] - s["pk"] * 0.8, s["shots"] - s["sot"], s["pk"]]); y.append(goals)
X, y = np.array(X, float), np.array(y, float)
coef, *_ = np.linalg.lstsq(X, y, rcond=None)
print("xG = %.3f x shots on target (non-pen) + %.3f x other shots + %.3f x penalties  (rows %d, mean goals %.2f, mean xG %.2f)"
      % (coef[0], coef[1], coef[2], len(y), y.mean(), (X @ coef).mean()))

def xg(t, side):
    s = t[side]; return max(0.0, coef[0] * (s["sot"] - s["pk"] * 0.8) + coef[1] * (s["shots"] - s["sot"]) + coef[2] * s["pk"])

VARIANTS = {"goals only": 0.0, "25% xG": 0.25, "50% xG": 0.5, "75% xG": 0.75, "xG only": 1.0}
score = {v: {"ll": 0.0, "b25": 0.0, "n": 0} for v in VARIANTS}
by_lg = defaultdict(lambda: {v: [0.0, 0] for v in VARIANTS})
for lg, (res, ts) in data.items():
    ms = []
    for g in res:
        try:
            d = datetime.fromisoformat(str(g.get("kickoff") or g["date"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        t = ts.get(str(g["id"]))
        ms.append({"home": g["home_team"], "away": g["away_team"], "g": (g["home_points"], g["away_points"]),
                   "x": (xg(t, "home"), xg(t, "away")) if t else None, "date": d, "neutral": g.get("neutral", False)})
    ms.sort(key=lambda m: m["date"])
    if not ms: continue
    start = ms[0]["date"] + timedelta(days=120)
    days = sorted({m["date"].date() for m in ms if m["date"] >= start})
    for i, day in enumerate(days[::3]):                          # refit every 3rd match day (speed)
        as_of = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        nxt = [m for m in ms if as_of <= m["date"] < as_of + timedelta(days=3 if i + 1 < len(days[::3]) else 99)]
        nxt = [m for m in nxt if m["date"].date() in set(days[i * 3:(i + 1) * 3])]
        prior = [m for m in ms if m["date"] < as_of]
        for v, wx in VARIANTS.items():
            rows = []
            for m in prior:
                hg, ag = m["g"]
                if m["x"] is not None:
                    hg, ag = (1 - wx) * hg + wx * m["x"][0], (1 - wx) * ag + wx * m["x"][1]
                elif wx == 1.0:
                    continue
                rows.append({"home": m["home"], "away": m["away"], "hg": hg, "ag": ag, "date": m["date"], "neutral": m["neutral"]})
            r = M.fit(rows, as_of)
            for m in nxt:
                rt = M.rates(r, m["home"], m["away"], m["neutral"])
                if not rt: continue
                g = M.grid(*rt)
                ph, pd_, pa = M.one_x_two(g)
                hg, ag = m["g"]
                p = ph if hg > ag else (pd_ if hg == ag else pa)
                over = M.total_outcome(g, 2.5, "over")
                po = over.get("win", 0.0)
                s = score[v]; s["ll"] += -math.log(max(p, 1e-9)); s["b25"] += (po - (hg + ag > 2.5)) ** 2; s["n"] += 1
                by_lg[lg][v][0] += -math.log(max(p, 1e-9)); by_lg[lg][v][1] += 1
for v, s in score.items():
    print(f"XG {v:12} n={s['n']} 1X2 log loss {s['ll'] / s['n']:.4f}  over-2.5 Brier {s['b25'] / s['n']:.4f}")
for lg, d in by_lg.items():
    print("XG  " + lg + "  " + "  ".join(f"{v}: {d[v][0] / max(d[v][1], 1):.4f}" for v in VARIANTS) + f"  (n={d['goals only'][1]})")
