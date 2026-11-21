"""Nov 21: do 'earned' chances fix the shown picks' overconfidence? Walk-forward, every graded prop read, 60 days.
A (priced reads): logit P(over) = a + b logit(books) + c (logit(model) - logit(books)) per sport x market.
B (every read, incl. pick'em): logit P(over) = a + b logit(model) per sport x market.
Shown = a playable tag, 🔒 or 💰 on the model's side. Bands by RAW chance of the shown side."""
import math, sys
from datetime import date, timedelta
sys.path.insert(0, ".")
import numpy as np
import daily_review as DR, model_store as MS, props_engine as PE, todays_best as TB

def lg_(p):
    p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p / (1 - p))
def sig(x): return 1 / (1 + math.exp(-x))
def fit(X, y, prior, lam=3.0):
    X = np.column_stack([np.ones(len(X)), np.array(X)]); w = np.array([0.0] + list(prior))
    pr = np.array([0.0] + list(prior))
    for _ in range(60):
        p = 1 / (1 + np.exp(-X @ w)); R = np.diag(np.r_[0, np.ones(X.shape[1]-1)])
        g = X.T @ (p - y) + lam * R @ (w - pr)
        Hm = X.T @ (X * (p * (1 - p))[:, None]) + lam * R
        st = np.linalg.solve(Hm, g); w -= st
        if np.abs(st).max() < 1e-7: break
    return w
SINCE = (date.today() - timedelta(days=60)).isoformat()
first = True
ALL = []
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if d >= SINCE])
    rows = []
    for rs in g.values():
        for r in rs:
            if first:
                print("ES keys", sorted(r.keys())); first = False
            if r.get("actual") is None or r.get("p_model") is None or r.get("line") is None: continue
            thr = PE.threshold(float(r["line"]))
            if r["actual"] == thr: continue
            tag = PE.norm_use(r.get("bet_use_tag") or r.get("use_tag"))
            pmod = float(r["p_model"])
            side_over = pmod >= 0.5
            priced = (r.get("book") or "") not in PE.PICKEM_BOOKS and r.get("p_market") is not None
            lock = PE.is_lock(r.get("chance"), r.get("cushion"), r.get("gap"), r.get("book"), ev=r.get("ev"))
            shown = tag in TB.PLAYABLE or lock or PE.snapshot_is_money(sp, r)
            rows.append(dict(d=str(r["slate_date"]), m=r.get("market"), pm=float(r["p_market"]) if priced else None,
                             pmod=pmod, y=float(r["actual"] > thr), over=side_over, shown=shown,
                             pk=not priced))
    days = sorted({r["d"] for r in rows})
    for d in days:
        tr = [r for r in rows if r["d"] < d]
        if len(tr) < 300: continue
        today = [r for r in rows if r["d"] == d]
        WA, WB = {}, {}
        for m in {r["m"] for r in today}:
            tb = [r for r in tr if r["m"] == m]; tb = tb if len(tb) >= 300 else tr
            WB[m] = fit([[lg_(r["pmod"])] for r in tb], np.array([r["y"] for r in tb]), [1.0])
            ta = [r for r in tb if r["pm"] is not None]
            if len(ta) < 300: ta = [r for r in tr if r["pm"] is not None]
            WA[m] = fit([[lg_(r["pm"]), lg_(r["pmod"]) - lg_(r["pm"])] for r in ta], np.array([r["y"] for r in ta]), [1.0, 0.0]) if len(ta) >= 300 else None
        for r in today:
            pb = sig(WB[r["m"]][0] + WB[r["m"]][1] * lg_(r["pmod"]))
            w = WA[r["m"]]
            pa = sig(w[0] + w[1] * lg_(r["pm"]) + w[2] * (lg_(r["pmod"]) - lg_(r["pm"]))) if (w is not None and r["pm"] is not None) else None
            s = (lambda p: p if r["over"] else 1 - p)
            ALL.append(dict(sp=sp, d=d, raw=s(r["pmod"]), a=s(pa) if pa is not None else None, b=s(pb),
                            book=s(r["pm"]) if r["pm"] is not None else None,
                            hit=(r["y"] == 1) == r["over"], shown=r["shown"], pk=r["pk"]))

def show(name, xs):
    if not xs: print(f"ES {name}: n=0"); return
    n = len(xs); h = sum(x["hit"] for x in xs) / n
    f = lambda k: (sum(x[k] for x in xs if x[k] is not None) / max(1, sum(x[k] is not None for x in xs)))
    print(f"ES {name}: n={n} hit={h:.1%} raw={f('raw'):.1%} earnedA={f('a'):.1%} (priced {sum(x['a'] is not None for x in xs)}) "
          f"earnedB={f('b'):.1%} books={f('book'):.1%}")
for sp in ("ALL", "NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    xs = [x for x in ALL if sp == "ALL" or x["sp"] == sp]
    for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
        show(f"{sp} shown raw {lo:.1f}-{hi:.1f}", [x for x in xs if x["shown"] and lo <= x["raw"] < hi])
    show(f"{sp} shown pickem 0.6+", [x for x in xs if x["shown"] and x["pk"] and x["raw"] >= .6])
    show(f"{sp} shown priced 0.6+", [x for x in xs if x["shown"] and not x["pk"] and x["raw"] >= .6])
# Nov 21: a second stage on SHOWN picks -- logit P(hit) = a + b logit(earned), fit on earlier days only
for x in ALL:
    x["e"] = x["a"] if x["a"] is not None else x["b"]
SH = [x for x in ALL if x["shown"]]
for x in SH:
    x["post"] = None
for d in sorted({x["d"] for x in SH}):
    tr = [x for x in SH if x["d"] < d]
    if len(tr) < 400: continue
    for grp in (True, False):
        t = [x for x in tr if x["pk"] == grp] 
        if len(t) < 200: t = tr
        w = fit([[lg_(x["e"])] for x in t], np.array([float(x["hit"]) for x in t]), [1.0])
        for x in SH:
            if x["d"] == d and x["pk"] == grp:
                x["post"] = sig(w[0] + w[1] * lg_(x["e"]))
V = [x for x in SH if x["post"] is not None]
def show2(name, xs):
    if not xs: print(f"ES {name}: n=0"); return
    n = len(xs); h = sum(x["hit"] for x in xs) / n
    print(f"ES {name}: n={n} hit={h:.1%} raw={sum(x['raw'] for x in xs)/n:.1%} earned={sum(x['e'] for x in xs)/n:.1%} post={sum(x['post'] for x in xs)/n:.1%}")
for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
    show2(f"POST by raw {lo:.1f}-{hi:.1f}", [x for x in V if lo <= x["raw"] < hi])
for lo, hi in ((.4, .5), (.5, .55), (.55, .6), (.6, .65), (.65, 1.01)):
    show2(f"POST by earned {lo:.2f}-{hi:.2f}", [x for x in V if lo <= x["e"] < hi])
for lo, hi in ((.4, .5), (.5, .55), (.55, .6), (.6, .65), (.65, 1.01)):
    show2(f"POST by post {lo:.2f}-{hi:.2f}", [x for x in V if lo <= x["post"] < hi])
import math as _m
def brier(k): return sum((x[k] - x["hit"]) ** 2 for x in V) / len(V)
def ll(k): return -sum(_m.log(x[k] if x["hit"] else 1 - x[k]) for x in V) / len(V)
print(f"ES POST n={len(V)} brier earned={brier('e'):.4f} post={brier('post'):.4f} logloss earned={ll('e'):.4f} post={ll('post'):.4f}")
print("ES done")
