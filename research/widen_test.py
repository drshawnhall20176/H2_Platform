"""Nov 18: widen the model's own outcome range instead of leaning on the books?
For every graded read with the model's own chance (p_model, P over) and the books' no-vig chance (p_market):
  market only        p = m
  current shape      p = m + w (p_model - m)                     (what blend x trust does: one weight on the model)
  widened            p = m + w (widen(p_model, k) - m)           widen = probit temperature: z -> z / k  (k > 1 = wider)
  widened alone      p = widen(p_model, k)                       (no market at all)
Fitted on alternate dates, scored on the others (both ways). Log loss on Over/Under outcomes; lower is better."""
import math, os, sys
from collections import defaultdict
from datetime import date
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE
def ndtri(p):
    # inverse normal CDF (Acklam)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > 1 - pl:
        q = math.sqrt(-2 * math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5; r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
def ncdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def widen(p, k): return ncdf(ndtri(min(max(p, 0.005), 0.995)) / k)
def ll(rows, f):
    s = 0.0
    for r in rows:
        p = min(max(f(r), 0.01), 0.99); s -= math.log(p) if r["y"] else math.log(1 - p)
    return s / len(rows)
KS = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0, 2.3, 2.6, 3.0]
WS = [i / 20 for i in range(0, 21)]
def fit(rows, widened, alone=False):
    best = None
    for k in (KS if widened else [1.0]):
        for w in ([1.0] if alone else WS):
            f = (lambda r, k=k: widen(r["pm"], k)) if alone else (lambda r, k=k, w=w: r["m"] + w * (widen(r["pm"], k) - r["m"]))
            v = ll(rows, f)
            if best is None or v < best[0]: best = (v, k, w)
    return best
FAM = {"NBA": {"Points": "normal", "PRA": "normal", "PR": "normal", "PA": "normal", "RA": "normal",
               "Rebounds": "count", "Assists": "count", "Threes Made": "count"},
       "NHL": None, "NFL": None, "NCAAF": None}
for sp in ("NBA", "NHL", "NFL", "NCAAF"):
    ds = [d for d in MS.snapshot_dates(sp) if d < date.today().isoformat()]
    rows = []
    seen = {}
    for recs in D.grade_dates(sp, ds).values():
        for r in recs:
            if r.get("result") not in ("hit", "miss") or r.get("p_model") is None or r.get("p_market") is None \
                    or r.get("actual") is None or r.get("line") is None or r.get("market") == "Anytime TD":
                continue
            seen[(r["slate_date"], r["game"], r.get("player"), r["market"], r["line"])] = r
    for r in seen.values():
        rows.append({"d": r["slate_date"], "mk": r["market"], "pm": float(r["p_model"]), "m": float(r["p_market"]),
                     "y": r["actual"] > PE.threshold(float(r["line"]))})
    groups = {"ALL": rows}
    if FAM.get(sp):
        for fam in ("normal", "count"):
            groups[fam] = [r for r in rows if FAM[sp].get(r["mk"]) == fam]
    mk = defaultdict(list)
    for r in rows: mk[r["mk"]].append(r)
    for m, rs in mk.items():
        if len(rs) >= 700: groups[m] = rs
    for g, rs in groups.items():
        if len(rs) < 300: continue
        dates = sorted({r["d"] for r in rs}); A = set(dates[::2])
        res = defaultdict(float); fits = defaultdict(list)
        for train_is_A in (True, False):
            tr = [r for r in rs if (r["d"] in A) == train_is_A]; te = [r for r in rs if (r["d"] in A) != train_is_A]
            if len(tr) < 100 or len(te) < 100: continue
            res["market"] += ll(te, lambda r: r["m"]) * len(te)
            _, k, w = fit(tr, False); res["current"] += ll(te, lambda r: r["m"] + w * (r["pm"] - r["m"])) * len(te); fits["current"].append(w)
            _, k2, w2 = fit(tr, True); res["widened"] += ll(te, lambda r: r["m"] + w2 * (widen(r["pm"], k2) - r["m"])) * len(te); fits["widened"].append((k2, w2))
            _, k3, _ = fit(tr, True, alone=True); res["alone"] += ll(te, lambda r: widen(r["pm"], k3)) * len(te); fits["alone"].append(k3)
            res["n"] += len(te)
        n = res["n"]
        _, kf, wf = fit(rs, True)
        _, wc = fit(rs, False)[1:]
        print(f"W {sp:5} {g:12} n{len(rs):5d} held-out log loss: market {res['market']/n:.4f} | model weight only {res['current']/n:.4f} (w {fits['current']}) "
              f"| widened {res['widened']/n:.4f} (k,w {fits['widened']}) | widened model alone {res['alone']/n:.4f} (k {fits['alone']}) || all data: weight-only w={wc}, widened k={kf} w={wf}")
        # calibration of widened-alone at the all-data k
        _, ka, _ = fit(rs, True, alone=True)
        b = defaultdict(lambda: [0, 0, 0.0])
        for r in rs:
            p = widen(r["pm"], ka); x = b[min(int(p * 10), 9)]; x[0] += 1; x[1] += r["y"]; x[2] += p
        print(f"W {sp:5} {g:12} widened-alone k={ka}: " + " ".join(f"{i/10:.1f}:{v[2]/v[0]:.0%}->{v[1]/v[0]:.0%}(n{v[0]})" for i, v in sorted(b.items()) if v[0] >= 40))
