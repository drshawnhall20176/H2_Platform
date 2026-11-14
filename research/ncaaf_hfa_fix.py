"""Live v2 picks went 8-20 with 90 of 92 picks on the home team (hfa 7.6 pts; real CFB home field is ~2-3).
Suspect: FBS-vs-FCS home blowouts inflate hfa because FCS teams (few games) are shrunk toward average.
Walk-forward 2025 + 2026 with CFBD closing lines: current fit vs FBS-only fit (both teams 5+ games) vs fixed hfa."""
import os, sys, math
from collections import Counter, defaultdict
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ncaaf_data as ND

def num(x):
    try:
        v = float(x); return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None

key = os.environ.get("CFBD_API_KEY")
sched = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ncaaf_schedule.csv"))
sched = sched[sched["completed"] == True]  # noqa: E712
lines = {}
for year in sorted(sched["season"].unique()):
    for g in ND._get("/lines", {"year": int(year)}, key) or []:
        sp = [num(l.get("spread")) for l in g.get("lines") or []]
        sp = [x for x in sp if x is not None]
        if sp:
            lines[int(g["id"])] = -sum(sp) / len(sp)
print("lines", len(lines))

def fit(prior, lam=2.0, hfa_fixed=None):
    teams = sorted(set(prior["home_team"]) | set(prior["away_team"]))
    ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    X, y = [], []
    for r in prior.itertuples():
        h = 0 if r.neutral_site else 1
        for t, o, pts, hm in ((r.home_team, r.away_team, r.home_points, h), (r.away_team, r.home_team, r.away_points, -h)):
            x = np.zeros(2 * n + 1); x[ix[t]] = 1; x[n + ix[o]] = -1; x[2 * n] = 0.5 * hm
            X.append(x); y.append(pts)
    X, y = np.array(X), np.array(y, float)
    mu = y.mean()
    if hfa_fixed is not None:
        y = y - X[:, 2 * n] * hfa_fixed
        X = X[:, :2 * n]
        reg = np.eye(2 * n) * lam
        b = np.linalg.solve(X.T @ X + reg, X.T @ (y - mu))
        return mu, {t: b[ix[t]] for t in teams}, {t: b[n + ix[t]] for t in teams}, hfa_fixed
    reg = np.eye(2 * n + 1) * lam; reg[2 * n, 2 * n] = 0
    b = np.linalg.solve(X.T @ X + reg, X.T @ (y - mu))
    return mu, {t: b[ix[t]] for t in teams}, {t: b[n + ix[t]] for t in teams}, b[2 * n]

def fbs_only(prior, k=5):
    c = Counter(list(prior["home_team"]) + list(prior["away_team"]))
    big = {t for t, v in c.items() if v >= k}
    return prior[prior["home_team"].isin(big) & prior["away_team"].isin(big)]

variants = {"current": lambda p: fit(p), "FBS-only fit": lambda p: fit(fbs_only(p)),
            "FBS-only, hfa 2.5": lambda p: fit(fbs_only(p), hfa_fixed=2.5), "all games, hfa 2.5": lambda p: fit(p, hfa_fixed=2.5)}
res = defaultdict(list); hfas = defaultdict(list)
for season, gs in sched.groupby("season"):
    for wk in sorted(gs["week"].unique()):
        if wk < 5: continue
        prior = gs[gs["week"] < wk]
        if len(prior) < 50: continue
        cur = gs[gs["week"] == wk]
        for name, f in variants.items():
            mu, off, de, hf = f(prior); hfas[(season, name)].append(hf)
            for r in cur.itertuples():
                if int(r.id) not in lines or r.home_team not in off or r.away_team not in off: continue
                hh = 0 if r.neutral_site else 0.5 * hf
                mm = (mu + off[r.home_team] - de[r.away_team] + hh) - (mu + off[r.away_team] - de[r.home_team] - hh)
                lm = lines[int(r.id)]; e = mm - lm; m = r.home_points - r.away_points
                if m == lm: continue
                res[name].append((season, e, (m > lm) == (e > 0)))
for name, rows in res.items():
    for lo in (4, 7):
        for season in (None, 2025, 2026):
            g = [(e, w) for s, e, w in rows if abs(e) >= lo and (season is None or s == season)]
            if not g: continue
            home = sum(1 for e, _ in g if e > 0) / len(g)
            print(f"{name:22} gap {lo}+ {season or 'both':>5}: {sum(w for _, w in g)}-{sum(1 for _, w in g if not w)} "
                  f"({sum(w for _, w in g)/len(g):.1%}) n={len(g)} home picks {home:.0%}")
for k, v in sorted(hfas.items()):
    print("hfa", k, f"{np.mean(v):.2f}")
