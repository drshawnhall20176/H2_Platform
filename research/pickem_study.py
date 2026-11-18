"""Nov 18: pick'em-only reads (no sportsbook price: college props the books don't post) -- how honest is the model's
chance there, and what share of it should stand? p = 0.5 + w (p_model - 0.5), fit on alternate dates."""
import math, os, sys
from collections import defaultdict
from datetime import date
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE
def ll(rows, w):
    s = 0
    for r in rows:
        p = min(max(0.5 + w * (r["p"] - 0.5), 0.01), 0.99); s -= math.log(p) if r["y"] else math.log(1 - p)
    return s / len(rows)
WS = [i / 20 for i in range(21)]
for sp in ("NCAAF", "NCAAMB", "NBA", "NFL", "NHL"):
    ds = [d for d in MS.snapshot_dates(sp) if d < date.today().isoformat()]
    seen = {}
    for rs in D.grade_dates(sp, ds).values():
        for r in rs:
            if r.get("result") in ("hit", "miss") and r.get("p_model") is not None and r.get("actual") is not None:
                seen[(r["slate_date"], r["game"], r.get("player"), r["market"])] = r
    rows_all = list(seen.values())
    pk = [r for r in rows_all if r.get("p_market") is None and r.get("over_price") is None]
    print(f"PK {sp}: graded reads {len(rows_all)}, pick'em-only (no sportsbook price) {len(pk)}")
    if len(pk) < 60: continue
    rows = [{"d": r["slate_date"], "p": float(r["p_model"]), "y": r["actual"] > PE.threshold(float(r["line"])), "mk": r["market"],
             "side": "Over" if float(r["p_model"]) >= 0.5 else "Under", "ch": r.get("chance")} for r in pk]
    b = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        x = b[min(int(r["p"] * 10), 9)]; x[0] += 1; x[1] += r["y"]; x[2] += r["p"]
    print(f"PK {sp} model P(over) said -> happened: " + " ".join(f"{v[2]/v[0]:.0%}->{v[1]/v[0]:.0%}(n{v[0]})" for k, v in sorted(b.items()) if v[0] >= 15))
    dates = sorted({r["d"] for r in rows}); A = set(dates[::2])
    tot = defaultdict(float); n = 0; fits = []
    for trA in (True, False):
        tr = [r for r in rows if (r["d"] in A) == trA]; te = [r for r in rows if (r["d"] in A) != trA]
        if len(tr) < 30 or len(te) < 30: continue
        w = min(WS, key=lambda w: ll(tr, w)); fits.append(w)
        tot["coin"] += ll(te, 0) * len(te); tot["fit"] += ll(te, w) * len(te); tot["raw"] += ll(te, 1) * len(te); n += len(te)
    wall = min(WS, key=lambda w: ll(rows, w))
    if n: print(f"PK {sp} held-out log loss: coin flip {tot['coin']/n:.4f} | model as is {tot['raw']/n:.4f} | model share fitted {fits} {tot['fit']/n:.4f} || all data w={wall}")
    # the side the model takes: hit rate by its stated chance
    sb = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        c = max(r["p"], 1 - r["p"]); hit = r["y"] if r["p"] >= 0.5 else not r["y"]
        k = "50-55" if c < .55 else "55-60" if c < .6 else "60-65" if c < .65 else "65-70" if c < .7 else "70+"
        x = sb[k]; x[0] += 1; x[1] += hit; x[2] += c
    print(f"PK {sp} model's side by its chance: " + " | ".join(f"{k}: said {v[2]/v[0]:.0%} hit {v[1]/v[0]:.0%} (n{v[0]})" for k, v in sorted(sb.items())))
    ov = [r for r in rows if r["p"] >= .5]; un = [r for r in rows if r["p"] < .5]
    print(f"PK {sp} More picks hit {sum(r['y'] for r in ov)/max(len(ov),1):.0%} of {len(ov)}; Less picks hit {sum(not r['y'] for r in un)/max(len(un),1):.0%} of {len(un)}")
    mk = defaultdict(lambda: [0, 0])
    for r in rows:
        hit = r["y"] if r["p"] >= 0.5 else not r["y"]; mk[r["mk"]][0] += 1; mk[r["mk"]][1] += hit
    print(f"PK {sp} by market (model's side hit): " + ", ".join(f"{m} {v[1]}/{v[0]}" for m, v in sorted(mk.items(), key=lambda kv: -kv[1][0])[:10]))
