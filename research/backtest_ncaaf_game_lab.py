"""research/backtest_ncaaf_game_lab.py — NCAAF Game Lab vs the closing line (2025 + 2026 FBS, CFBD lines).

Same test as backtest_game_lab.py (NFL): Game Lab's projection from games BEFORE each one (last-4 scoring x the
opponent's season points allowed / league average, no home field) against CFBD's consensus closing spread / total /
moneyline. Needs CFBD_API_KEY (the research workflow passes it)."""
import math
import os
import sys
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ncaaf_data as ND  # noqa: E402

SD_MARGIN = 16.0


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


key = os.environ.get("CFBD_API_KEY")
sched = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ncaaf_schedule.csv"))
sched = sched[sched["completed"] == True]  # noqa: E712
lines = {}
for year in sorted(sched["season"].unique()):
    for g in ND._get("/lines", {"year": int(year)}, key):
        sp = [num(l.get("spread")) for l in g.get("lines") or []]
        ou = [num(l.get("overUnder")) for l in g.get("lines") or []]
        hm = [num(l.get("homeMoneyline")) for l in g.get("lines") or []]
        am = [num(l.get("awayMoneyline")) for l in g.get("lines") or []]
        sp, ou = [x for x in sp if x is not None], [x for x in ou if x is not None]
        hm, am = [x for x in hm if x is not None], [x for x in am if x is not None]
        if sp:
            lines[int(g["id"])] = (-sum(sp) / len(sp), sum(ou) / len(ou) if ou else None,
                                   (sum(hm) / len(hm), sum(am) / len(am)) if hm and am else None)
print(f"lines for {len(lines)} games")


def no_vig(h, a):
    imp = lambda x: 100 / (x + 100) if x > 0 else -x / (-x + 100)
    p, q = imp(h), imp(a)
    return p / (p + q)


import numpy as np


def ratings(prior, lam):
    """Opponent-adjusted offense / defense ratings (ridge least squares on points scored), plus home field.
    points(team t vs opp o, home flag) = mu + off[t] - def[o] + hfa * home."""
    teams = sorted(set(prior["home_team"]) | set(prior["away_team"]))
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    rows, y = [], []
    for r in prior.itertuples():
        for t, o, pts, home in ((r.home_team, r.away_team, r.home_points, 0 if r.neutral_site else 1),
                                (r.away_team, r.home_team, r.away_points, 0 if r.neutral_site else -1)):
            x = np.zeros(2 * n + 1)
            x[ix[t]] = 1
            x[n + ix[o]] = -1
            x[2 * n] = home * 0.5
            rows.append(x)
            y.append(pts)
    X, y = np.array(rows), np.array(y, dtype=float)
    mu = y.mean()
    reg = np.eye(2 * n + 1) * lam
    reg[2 * n, 2 * n] = 0.0
    beta = np.linalg.solve(X.T @ X + reg, X.T @ (y - mu))
    return mu, {t: beta[ix[t]] for t in teams}, {t: beta[n + ix[t]] for t in teams}, beta[2 * n]


res = defaultdict(list)
for season, gs in sched.groupby("season"):
    gs = gs.sort_values("week")
    cache = {}
    for wk in sorted(gs["week"].unique()):
        pr = gs[gs["week"] < wk]
        if len(pr) > 50:
            for lam in (2.0, 5.0):
                cache[(wk, lam)] = ratings(pr, lam)
    gs = gs.sort_values("week")
    for row in gs.itertuples(index=False):
        if row.week < 5 or int(row.id) not in lines:
            continue
        prior = gs[gs["week"] < row.week]
        lg = (prior["home_points"].sum() + prior["away_points"].sum()) / (2 * len(prior))

        def scored(t, n=None):
            pts = [(r.week, r.home_points if r.home_team == t else r.away_points) for r in prior.itertuples()
                   if t in (r.home_team, r.away_team)]
            pts = [p for _, p in sorted(pts)]
            pts = pts[-n:] if n else pts
            return sum(pts) / len(pts) if pts else None

        def allowed(t):
            pts = [r.away_points if r.home_team == t else r.home_points for r in prior.itertuples()
                   if t in (r.home_team, r.away_team)]
            return sum(pts) / len(pts) if pts else None
        h, a = row.home_team, row.away_team
        hs4, as4, hss, ass, ha, aa = scored(h, 4), scored(a, 4), scored(h), scored(a), allowed(h), allowed(a)
        if None in (hs4, as4, ha, aa):
            continue
        lm, lt, ml = lines[int(row.id)]
        m, t = row.home_points - row.away_points, row.home_points + row.away_points
        pk = no_vig(*ml) if ml else None
        hfa = 0 if row.neutral_site else 1.25
        for lam in (2.0, 5.0):
            if (row.week, lam) in cache:
                mu, off, de, hf = cache[(row.week, lam)]
                if h in off and a in off:
                    hh = 0 if row.neutral_site else hf * 0.5
                    hp_, ap_ = mu + off[h] - de[a] + hh, mu + off[a] - de[h] - hh
                    res[f"ratings ridge {lam:g}"].append((hp_ - ap_, hp_ + ap_, m, t, lm, lt, pk))
                    res[f"ratings ridge {lam:g} x0.5 + market"].append((0.5 * (hp_ - ap_) + 0.5 * lm,
                                                                         None if lt is None else 0.5 * (hp_ + ap_) + 0.5 * lt,
                                                                         m, t, lm, lt, pk))
        for name, (hp, ap) in {"Game Lab (current)": (hs4 * aa / lg, as4 * ha / lg),
                               "+ home field 2.5": (hs4 * aa / lg + hfa, as4 * ha / lg - hfa),
                               "season avgs + HFA": (hss * aa / lg + hfa, ass * ha / lg - hfa)}.items():
            res[name].append((hp - ap, hp + ap, m, t, lm, lt, pk))
            res[name + " x0.5 + market"].append((0.5 * (hp - ap) + 0.5 * lm, None if lt is None else 0.5 * (hp + ap) + 0.5 * lt,
                                                 m, t, lm, lt, pk))
L = res["Game Lab (current)"]
print(f"games: {len(L)}")
print(f"closing line   margin MAE {sum(abs(m - lm) for _, _, m, _, lm, _, _ in L) / len(L):.2f}   total MAE "
      f"{sum(abs(t - lt) for _, _, _, t, _, lt, _ in L if lt) / max(1, sum(1 for x in L if x[5])):.2f}")
for name, rs in res.items():
    mae_m = sum(abs(m - pm) for pm, _, m, _, _, _, _ in rs) / len(rs)
    tt = [(pt, t) for _, pt, _, t, _, lt, _ in rs if pt is not None and lt]
    out = [f"{name:32s} margin MAE {mae_m:.2f}  total MAE {sum(abs(t - pt) for pt, t in tt) / len(tt):.2f}"]
    for thr in (2, 4, 7):
        ats = [(1 if (m - lm) * (pm - lm) > 0 else 0) for pm, _, m, _, lm, _, _ in rs if abs(pm - lm) >= thr and m != lm]
        ou = [(1 if (t - lt) * (pt - lt) > 0 else 0) for _, pt, _, t, _, lt, _ in rs
              if pt is not None and lt and abs(pt - lt) >= thr and t != lt]
        out.append(f"| {thr}+: ATS {sum(ats) / max(len(ats), 1):.1%} (n{len(ats)}) O/U {sum(ou) / max(len(ou), 1):.1%} (n{len(ou)})")
    ll = [(-math.log(max(phi(pm / SD_MARGIN), 1e-6)) if m > 0 else -math.log(max(1 - phi(pm / SD_MARGIN), 1e-6)))
          for pm, _, m, _, _, _, pk in rs if m != 0 and pk is not None]
    out.append(f"| ML logloss {sum(ll) / max(len(ll), 1):.4f}")
    print("  ".join(out))
mk = [(-math.log(max(pk, 1e-6)) if m > 0 else -math.log(max(1 - pk, 1e-6))) for _, _, m, _, _, _, pk in L if m != 0 and pk is not None]
print(f"closing moneyline logloss {sum(mk) / max(len(mk), 1):.4f} (n{len(mk)})")
ov = [(1 if t > lt else 0) for _, pt, _, t, _, lt, _ in L if lt and pt - lt >= 2 and t != lt]
un = [(1 if t < lt else 0) for _, pt, _, t, _, lt, _ in L if lt and lt - pt >= 2 and t != lt]
print(f"model Over picks {sum(ov) / max(len(ov), 1):.1%} (n{len(ov)})  Under picks {sum(un) / max(len(un), 1):.1%} (n{len(un)})")
