"""Nov 18: is the normal curve the right SHAPE for points / yards props? Same mean (projection), same spread
(fitted per market on the other half of the dates), normal vs gamma (right-skewed). Scored on graded reads."""
import math, os, sys, random
from collections import defaultdict
from datetime import date
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE
def _gammainc(a, x):
    """regularized lower incomplete gamma P(a, x) (Numerical Recipes series / continued fraction)."""
    if x <= 0: return 0.0
    gln = math.lgamma(a)
    if x < a + 1:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1; d *= x / ap; s += d
            if abs(d) < abs(s) * 1e-12: break
        return s * math.exp(-x + a * math.log(x) - gln)
    b = x + 1 - a; c = 1e300; d = 1 / b; h = d
    for i in range(1, 500):
        an = -i * (i - a); b += 2; d = an * d + b; d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c; c = 1e-300 if abs(c) < 1e-300 else c; d = 1 / d; de = d * c; h *= de
        if abs(de - 1) < 1e-12: break
    return 1 - math.exp(-x + a * math.log(x) - gln) * h
class stats:
    class norm:
        @staticmethod
        def cdf(x, mu, sd): return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))
    class gamma:
        @staticmethod
        def cdf(x, k, scale): return _gammainc(k, x / scale)
TODAY = date.today().isoformat()
MK = {"NBA": ["Points", "PRA", "PR", "PA", "RA"], "NFL": ["Receiving Yards", "Rush Yards", "Pass Yards", "Receptions"],
      "NCAAF": ["Receiving Yards", "Rush Yards", "Pass Yards", "Receptions"]}
for sp, mks in MK.items():
    ds = [d for d in MS.snapshot_dates(sp) if d < TODAY]
    rows = [r for recs in D.grade_dates(sp, ds).values() for r in recs
            if r.get("actual") is not None and r.get("line") is not None and r.get("market") in mks
            and float(r.get("projection") or 0) > 2]
    seen = {}
    for r in rows: seen[(r["slate_date"], r["game"], r.get("player"), r["market"], r["line"])] = r
    rows = list(seen.values())
    dates = sorted({r["slate_date"] for r in rows})
    half = set(dates[::2])
    for mk in mks + ["ALL"]:
        rs = [r for r in rows if mk == "ALL" or r["market"] == mk]
        if len(rs) < 150: continue
        res = {"normal": [0.0, 0, 0.0, 0], "gamma": [0.0, 0, 0.0, 0]}
        rel = {"normal": defaultdict(lambda: [0, 0, 0.0]), "gamma": defaultdict(lambda: [0, 0, 0.0])}
        for test in (True, False):
            fit = [r for r in rs if (r["slate_date"] in half) != test]
            cvm = {}
            for m in {r["market"] for r in fit}:
                xs = [float(r["actual"]) / float(r["projection"]) for r in fit if r["market"] == m]
                mu = sum(xs) / len(xs); cvm[m] = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))
            for r in rs:
                if (r["slate_date"] in half) != test or r["market"] not in cvm: continue
                mu = float(r["projection"]); sd = max(cvm[r["market"]] * mu, 1.0)
                thr = PE.threshold(float(r["line"]))
                y = r["actual"] > thr
                pn = 1 - stats.norm.cdf(thr, mu, sd)
                k = (mu / sd) ** 2; pg = 1 - stats.gamma.cdf(thr, k, scale=sd ** 2 / mu)
                for name, p in (("normal", pn), ("gamma", pg)):
                    p = min(max(p, 0.01), 0.99)
                    a = res[name]; a[0] += -(math.log(p) if y else math.log(1 - p)); a[1] += 1
                    side = "Over" if p >= 0.5 else "Under"
                    a[2] += (y if side == "Over" else not y); a[3] += 1
                    b = rel[name][min(int(p * 10), 9)]; b[0] += 1; b[1] += y; b[2] += p
        out = []
        for name in ("normal", "gamma"):
            ll, n, right, m = res[name]
            bands = " ".join(f"{i/10:.1f}:{v[2]/v[0]:.0%}->{v[1]/v[0]:.0%}(n{v[0]})" for i, v in sorted(rel[name].items()) if v[0] >= 30)
            out.append(f"{name}: logloss {ll/n:.4f} side right {right/m:.1%} | {bands}")
        print(f"SK {sp} {mk:16} n{len(rs)} | " + " || ".join(out))
        overs = [r for r in rs if r["actual"] > PE.threshold(float(r["line"]))]
        print(f"SK {sp} {mk:16} median actual/proj {sorted(float(r['actual'])/float(r['projection']) for r in rs)[len(rs)//2]:.2f}  went over the line {len(overs)/len(rs):.1%}")
