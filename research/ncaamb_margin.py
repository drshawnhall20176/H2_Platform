"""Nov 25 health check: 'NCAAMB game model's margins are too timid: actual margins run 1.46x the model's'.
How big is it, does the market share it, and what does it do to the close-gap (model within 2 of market) picks?
Aggregates only."""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import model_store as MS


def slope(pairs):
    n = len(pairs)
    mx = sum(a for a, _ in pairs) / n; my = sum(b for _, b in pairs) / n
    sxx = sum((a - mx) ** 2 for a, _ in pairs)
    s = sum((a - mx) * (b - my) for a, b in pairs) / sxx
    res = [b - my - s * (a - mx) for a, b in pairs]
    se = (sum(e * e for e in res) / (n - 2) / sxx) ** 0.5
    return s, se


def ols2(rows):
    import numpy as np
    X = np.array([[1, a, b] for a, b, _ in rows], float); y = np.array([c for *_, c in rows], float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    res = y - X @ b; s2 = res @ res / (len(y) - 3)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return [round(float(v), 3) for v in b], [round(float(v), 3) for v in se]


recs = [r for r in MS.load_game_picks("NCAAMB") if r.get("final_home") is not None and r.get("model_margin") is not None]
today = date.today().isoformat()
for days in (14, 28, 60):
    lo = (date.today() - timedelta(days=days)).isoformat()
    sub = [r for r in recs if str(r.get("kickoff") or "")[:10] >= lo]
    pairs = [(float(r["model_margin"]), float(r["final_home"]) - float(r["final_away"])) for r in sub]
    mk = [(-float(r["home_spread"]), float(r["final_home"]) - float(r["final_away"])) for r in sub if r.get("home_spread") is not None]
    both = [(float(r["model_margin"]), -float(r["home_spread"]), float(r["final_home"]) - float(r["final_away"]))
            for r in sub if r.get("home_spread") is not None]
    print(f"== last {days} days: {len(pairs)} games, {len(mk)} with a market spread ==")
    if len(pairs) > 30:
        s, se = slope(pairs); print(f"  actual margin vs MODEL: slope {s:.2f} ± {se:.2f}")
    if len(mk) > 30:
        s, se = slope(mk); print(f"  actual margin vs MARKET: slope {s:.2f} ± {se:.2f}")
    if len(both) > 30:
        b, se = ols2(both); print(f"  actual ~ a + b*model + c*market: b {b[1]}±{se[1]}  c {b[2]}±{se[2]}")
        # where the timidity lives: big-spread games vs close ones
        for lab, f in (("market spread <= 10", lambda x: abs(x[1]) <= 10), ("market spread > 10", lambda x: abs(x[1]) > 10)):
            p2 = [(a, c) for a, b_, c in both if f((a, b_, c))]
            if len(p2) > 30:
                s, se = slope(p2); print(f"    {lab}: n={len(p2)} slope vs model {s:.2f} ± {se:.2f}")
    # the close-gap picks (model within 2 of the market): the model's side against the spread
    by = collections.defaultdict(lambda: [0, 0])
    for r in sub:
        if r.get("home_spread") is None:
            continue
        mm, mkt = float(r["model_margin"]), -float(r["home_spread"])
        act = float(r["final_home"]) - float(r["final_away"])
        if act == mkt or mm == mkt:
            continue
        gap = abs(mm - mkt)
        model_home = mm > mkt
        cover = (act > mkt) == model_home
        dog = (model_home and mkt < 0) or (not model_home and mkt > 0)
        band = "gap<=2" if gap <= 2 else "gap 2-5" if gap <= 5 else "gap>5"
        for k in (band, f"{band} {'dog' if dog else 'fav'}"):
            b_ = by[k]; b_[0] += 1; b_[1] += cover
    print("  model's side ATS:", {k: f"{v[1]}-{v[0]-v[1]} ({v[1]/v[0]:.0%})" for k, v in sorted(by.items())})
    # what scaling the model's margins would do to its picks vs the spread
    for k in (1.0, 1.2, 1.4):
        w = l = 0
        for r in sub:
            if r.get("home_spread") is None:
                continue
            mm, mkt = k * float(r["model_margin"]), -float(r["home_spread"])
            act = float(r["final_home"]) - float(r["final_away"])
            if act == mkt or abs(mm - mkt) > 2 or mm == mkt:
                continue
            if (act > mkt) == (mm > mkt): w += 1
            else: l += 1
        print(f"  margins x{k}: close-gap picks {w}-{l}" + (f" ({w/(w+l):.0%})" if w + l else ""))
