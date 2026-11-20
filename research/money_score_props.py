"""Nov 20: the same money score for props -- walk-forward logistic on the books' no-vig chance and the model's
disagreement, per sport x market (fallback sport), refit daily; EV at the price carried."""
import math, sys
from collections import defaultdict
from datetime import date, timedelta
sys.path.insert(0, ".")
import numpy as np
import daily_review as DR, model_store as MS, props_engine as PE

def lg_(p):
    p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))
def sig(x): return 1 / (1 + math.exp(-x))
def fit(X, y, lam=3.0):
    X = np.column_stack([np.ones(len(X)), np.array(X)]); w = np.zeros(X.shape[1]); w[1] = 1.0
    for _ in range(60):
        p = 1 / (1 + np.exp(-X @ w)); R = np.diag(np.r_[0, np.ones(X.shape[1]-1)])
        prior = np.r_[0, 1.0, 0.0]
        g = X.T @ (p - y) + lam * R @ (w - prior)
        Hm = X.T @ (X * (p * (1 - p))[:, None]) + lam * R
        st = np.linalg.solve(Hm, g); w -= st
        if np.abs(st).max() < 1e-7: break
    return w
SINCE = (date.today() - timedelta(days=60)).isoformat()
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if d >= SINCE])
    rows = []
    for rs in g.values():
        for r in rs:
            if r.get("actual") is None or r.get("p_model") is None or r.get("p_market") is None: continue
            if (r.get("book") or "") in PE.PICKEM_BOOKS: continue
            op, up = r.get("over_price"), r.get("under_price")
            if op is None or up is None: continue
            thr = PE.threshold(float(r["line"]))
            if r["actual"] == thr: continue
            rows.append(dict(d=str(r["slate_date"]), m=r.get("market"), pm=float(r["p_market"]), pmod=float(r["p_model"]),
                             y=float(r["actual"] > thr), op=op, up=up))
    days = sorted({r["d"] for r in rows}); res = []
    for d in days:
        tr = [r for r in rows if r["d"] < d]
        if len(tr) < 300: continue
        W = {}
        for m in {r["m"] for r in rows if r["d"] == d}:
            t = [r for r in tr if r["m"] == m]
            t = t if len(t) >= 300 else tr
            W[m] = fit([[lg_(r["pm"]), lg_(r["pmod"]) - lg_(r["pm"])] for r in t], np.array([r["y"] for r in t]))
        for r in (r for r in rows if r["d"] == d):
            w = W[r["m"]]; ph = sig(w[0] + w[1] * lg_(r["pm"]) + w[2] * (lg_(r["pmod"]) - lg_(r["pm"])))
            best = None
            for pr, ps, hit in ((r["op"], ph, r["y"] == 1), (r["up"], 1 - ph, r["y"] == 0)):
                dd = PE.decimal(pr)
                if dd and (best is None or ps * dd - 1 > best[0]): best = (ps * dd - 1, dd, hit, ps)
            if best: res.append((best[0], best[1], best[2], d, best[3]))
    def show(xs):
        if not xs: return "n=0"
        n = len(xs); roi = sum((x[1]-1) if x[2] else -1 for x in xs)/n; s = sorted(xs, key=lambda x: x[3]); h = n//2
        f = lambda z: sum((x[1]-1) if x[2] else -1 for x in z)/len(z) if z else 0
        return f"n={n} days={len({x[3] for x in xs})} hit={sum(x[2] for x in xs)/n:.1%} roi={roi:+.1%} halves={f(s[:h]):+.1%}/{f(s[h:]):+.1%}"
    for lo, hi in ((-9, 0), (0, .02), (.02, .04), (.04, .07), (.07, .12), (.12, 9)):
        print(f"MSP {sp} ev {lo:+.2f}..{hi:+.2f} " + show([x for x in res if lo <= x[0] < hi]))
    print(f"MSP {sp} RULE 4-12% p>=.40 " + show([x for x in res if .04 <= x[0] < .12 and x[4] >= .40]))
