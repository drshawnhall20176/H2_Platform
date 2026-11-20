"""Nov 20: a MONEY SCORE for game lines, walk-forward.

For every graded game (ML, spread, total) the score is the expected return at the best price of a chance that blends
the books' no-vig chance with the model's disagreement, weighted by how much that disagreement has been right before:
    logit p = a + b * logit(p_market) + c * (logit(p_model) - logit(p_market))
fit per (league family, market) on EARLIER days only, refit each day. Compared with the raw model's EV.
"""
import math
import sys
from collections import defaultdict
sys.path.insert(0, ".")
import numpy as np
import intl_hoops as H
import intl_picks as IP
import model_store as MS
import todays_best as TB

LEAGUES = ["NBA", "NHL", "NCAAMB", "NCAAF", "TENNIS"] + [k for k in H.LEAGUES if k not in ("NBA", "NHL", "NCAAMB")]


def dec(a):
    return IP._dec(a)


def lg_(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def devig(a, b):
    da, db = dec(a), dec(b)
    if not da or not db:
        return None
    ia, ib = 1 / da, 1 / db
    return ia / (ia + ib)


def fit(X, y, lam=1.0):
    X = np.column_stack([np.ones(len(X)), np.array(X)])
    w = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + lam * np.r_[0, w[1:] - np.r_[1.0, 0.0][:len(w) - 1]]
        Wd = p * (1 - p)
        Hm = X.T @ (X * Wd[:, None]) + lam * np.diag(np.r_[0, np.ones(X.shape[1] - 1)])
        step = np.linalg.solve(Hm, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


rows = []
for lg in LEAGUES:
    try:
        recs = MS.load_game_picks(lg, ungraded=False)
    except Exception as e:
        print("MSG fail", lg, e); continue
    fam = lg if lg in TB.MARGIN_SD else "INTL"
    for p in recs:
        fh, fa = p.get("final_home"), p.get("final_away")
        if fh is None or fa is None:
            continue
        d = TB._et_date(p.get("kickoff"))
        if not d:
            continue
        mp, mm, mt = p.get("model_p"), p.get("model_margin"), p.get("model_total")
        if mp is None and mm is not None:
            mp = phi(float(mm) / TB.MARGIN_SD.get(fam, 11.0))
        # moneyline
        pm = p.get("fair_home") or devig(p.get("best_home"), p.get("best_away"))
        if mp is not None and pm and fh != fa:
            rows.append(dict(lg=lg, fam=fam, mkt="ML", d=d, pm=pm, pmod=float(mp), y=float(fh > fa),
                             ph=p.get("best_home"), pa=p.get("best_away"), push=False))
        # spread
        hs = p.get("home_spread")
        if hs is None and p.get("line") is not None and lg == "NCAAF":
            hs = -float(p["line"])
        if hs is not None and mm is not None and lg != "TENNIS":
            sh, sa = p.get("spread_price"), IP.spread_price_for(p, "away")
            pms = devig(sh, sa) if sh is not None else 0.5
            v = (fh - fa) + float(hs)
            if v != 0:
                rows.append(dict(lg=lg, fam=fam, mkt="SP", d=d, pm=pms or 0.5,
                                 pmod=phi((float(mm) + float(hs)) / TB.MARGIN_SD.get(fam, 11.0)), y=float(v > 0),
                                 ph=sh or -110, pa=sa or -110, push=False))
        lt = p.get("line_total")
        if lt is not None and mt is not None and lg != "TENNIS":
            v = fh + fa - float(lt)
            if v != 0:
                po = devig(p.get("over_price"), p.get("under_price")) or 0.5
                rows.append(dict(lg=lg, fam=fam, mkt="TOT", d=d, pm=po,
                                 pmod=phi((float(mt) - float(lt)) / TB.TOTAL_SD.get(fam, 16.0)), y=float(v > 0),
                                 ph=p.get("over_price") or -110, pa=p.get("under_price") or -110, push=False))
print("MSG rows", len(rows), "days", len({r["d"] for r in rows}))
days = sorted({r["d"] for r in rows})
out = defaultdict(list)          # (method) -> [(lg, mkt, ev, dec, hit, d)]
coefs = {}
MIN_TRAIN = 80
for i, d in enumerate(days):
    test = [r for r in rows if r["d"] == d]
    train = [r for r in rows if r["d"] < d]
    for key in {(r["fam"], r["mkt"]) for r in test}:
        tr = [r for r in train if (r["fam"], r["mkt"]) == key]
        w = None
        if len(tr) >= MIN_TRAIN:
            X = [[lg_(r["pm"]), lg_(r["pmod"]) - lg_(r["pm"])] for r in tr]
            w = fit(X, np.array([r["y"] for r in tr]))
            coefs[key] = (w, len(tr))
        for r in (r for r in test if (r["fam"], r["mkt"]) == key):
            for meth in ("raw", "score"):
                if meth == "raw":
                    ph = r["pmod"]
                else:
                    if w is None:
                        continue
                    ph = sig(w[0] + w[1] * lg_(r["pm"]) + w[2] * (lg_(r["pmod"]) - lg_(r["pm"])))
                best = None
                for side, pr, ps, hit in (("h", r["ph"], ph, r["y"] == 1), ("a", r["pa"], 1 - ph, r["y"] == 0)):
                    dd = dec(pr)
                    if dd and (best is None or ps * dd - 1 > best[0]):
                        best = (ps * dd - 1, dd, hit, ps)
                if best:
                    out[meth].append((r["lg"], r["mkt"], best[0], best[1], best[2], d, best[3]))


def show(tag, xs):
    if not xs:
        return f"{tag}: n=0"
    n = len(xs); h = sum(x[4] for x in xs)
    roi = sum((x[3] - 1) if x[4] else -1 for x in xs) / n
    need = sum(1 / x[3] for x in xs) / n
    days_ = len({x[5] for x in xs})
    srt = sorted(xs, key=lambda x: x[5]); half = n // 2
    hh = (lambda s: sum((x[3] - 1) if x[4] else -1 for x in s) / len(s) if s else 0)
    return (f"{tag}: n={n} days={days_} hit={h/n:.1%} needed={need:.1%} roi={roi:+.1%}"
            + (f" halves={hh(srt[:half]):+.1%}/{hh(srt[half:]):+.1%}" if half else ""))


RULES = {"ML+SP 4-12%": lambda x: x[1] in ("ML", "SP") and 0.04 <= x[2] < 0.12,
         "ML+SP 3-12%": lambda x: x[1] in ("ML", "SP") and 0.03 <= x[2] < 0.12,
         "ML 3-12%": lambda x: x[1] == "ML" and 0.03 <= x[2] < 0.12,
         "SP 3-12%": lambda x: x[1] == "SP" and 0.03 <= x[2] < 0.12,
         "ML+SP 4-12% p>=.40": lambda x: x[1] in ("ML", "SP") and 0.04 <= x[2] < 0.12 and x[6] >= 0.40}
for tag, f in RULES.items():
    xs = [x for x in out["score"] if f(x)]
    print(f"MS2 RULE {tag} ALL " + show("", xs))
    for lg in LEAGUES:
        b = [x for x in xs if x[0] == lg]
        if b:
            print(f"MS2 RULE {tag} {lg} " + show("", b))
    per = defaultdict(int)
    for x in xs:
        per[x[5]] += 1
    if per:
        v = sorted(per.values())
        print(f"MS2 RULE {tag} per day median={v[len(v)//2]} max={v[-1]}")
