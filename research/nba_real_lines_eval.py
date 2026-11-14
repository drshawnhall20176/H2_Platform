"""Nov 14 -- judge NBA regression settings on REAL lines: every graded read of the last 28 days with posted prices.
The proxy-line backtest liked shrinking toward the league average; the real-line damage check said Rebounds leans got
worse. Here: the read's projection re-scaled by (new rate / raw rate), its chance recomputed with the read's own spread,
blended with the market as live (40/60), scored on log loss, and the leans at +3% EV scored on hit rate and profit."""
import math, os, sys
from collections import defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, props_engine as PE, player_props as PPR, long_shots as LS, position_data as PD
import position_matchups as PM

smp = PD.nba_league_props_sample(date.today().isoformat())
pg = (smp.get("cur") or []) + (smp.get("prior") or [])
byp = defaultdict(list)
for q in pg: byp[str(q["pid"])].append(q)
for v in byp.values(): v.sort(key=lambda q: str(q["order"]))
dates = [d for d in MS.snapshot_dates("NBA") if (date.today() - timedelta(days=28)).isoformat() <= d < date.today().isoformat()]
graded = [r for recs in D.grade_dates("NBA", dates).values() for r in recs]
seen = {}
for r in graded:
    if r.get("actual") is None or r.get("line") is None or r.get("over_price") is None or r.get("under_price") is None: continue
    seen[(r["slate_date"], r.get("player"), r.get("market"), r.get("line"))] = r
reads = list(seen.values())
print("graded NBA reads with both prices", len(reads))
cache = {}
def target(day, mk, grp):
    k = (day, mk, grp)
    if k not in cache:
        before = [q for q in pg if str(q["order"])[:10] < day]
        cache[k] = (PPR.league_rate(before, mk, group=grp) if grp else None) or PPR.league_rate(before, mk)
    return cache[k]
BASE_K = {"pts": 0.0, "reb": 45.0, "ast": 45.0, "fg3m": 45.0, "stl": 220.0, "blk": 110.0, "tov": 110.0}
CONFIGS = {"no regression": (None, 0.0), "league avg (live now)": ("league", 1.0), "position group": ("group", 1.0),
           "position group x2": ("group", 2.0), "position group x0.5": ("group", 0.5),
           "position group, points too": ("group+pts", 1.0)}
res = {c: defaultdict(lambda: [0.0, 0, 0, 0, 0.0]) for c in CONFIGS}   # mk -> [logloss sum, n, leans, hits, profit]
for r in reads:
    mk = r["market"]
    if mk not in PPR.MARKETS: continue
    hist = [q for q in byp.get(str(r.get("player_id")), []) if str(q["order"])[:10] < r["slate_date"]
            and PE.num((q.get("stats") or {}).get("min")) > 0][-PPR.HIT_N:][::-1]
    if len(hist) < 3: continue
    vals = [PPR.market_value(q.get("stats") or {}, mk) for q in hist]; mins = [PE.num(q["stats"].get("min")) for q in hist]
    raw, _ = PE.rate_and_opportunity(vals, mins)
    f = LS.fit(r, "NBA")
    if not raw or not f: continue
    grp = r.get("slot") if r.get("slot") in ("G", "F", "C") else PM.position_group(hist[0].get("pos"))
    y = r["actual"] > PE.threshold(float(r["line"]))
    pm = PE.devig(r["over_price"], r["under_price"])
    k_need = PE.k_needed(float(r["line"]))
    for name, (kind, mult) in CONFIGS.items():
        comps = PPR.MARKETS[mk]
        if kind is None:
            k = 0.0
        else:
            ks = [BASE_K.get(c, 45.0) if c != "pts" else (45.0 if kind == "group+pts" else 0.0) for c in comps]
            if "pts" in comps and kind != "group+pts": ks = [0.0]
            k = mult * sum(ks) / len(ks)
        tgt = target(r["slate_date"], mk, grp if kind and kind.startswith("group") else None)
        new = PE.shrink_toward(raw, mins, tgt, k) if k else raw
        p_mod = LS.rung_raw(dict(f, projection=float(r["projection"]) * new / raw), k_need)
        p = PE.blend(p_mod, pm, PE.MODEL_WEIGHT)
        p = min(max(p, 0.01), 0.99)
        R = res[name][mk]; R[0] += -math.log(p if y else 1 - p); R[1] += 1
        eo, eu = PE.ev(p, r["over_price"]), PE.ev(1 - p, r["under_price"])
        e, side, price = max((eo, "Over", r["over_price"]), (eu, "Under", r["under_price"]))
        if e >= PE.MIN_EV:
            won = y if side == "Over" else not y
            R[2] += 1; R[3] += won; R[4] += (PE.decimal(price) - 1) if won else -1
mks = sorted({m for c in res.values() for m in c})
for name in CONFIGS:
    tot = [0.0, 0, 0, 0, 0.0]
    for mk in mks:
        for i in range(5): tot[i] += res[name][mk][i]
    print(f"EVAL {name:28} all markets: log loss {tot[0] / tot[1]:.4f} | leans {tot[2]} hit {tot[3] / max(tot[2], 1):.1%} ROI {tot[4] / max(tot[2], 1):+.1%}")
for mk in mks:
    print(f"EVAL {mk}: " + " | ".join(f"{name}: {res[name][mk][0] / max(res[name][mk][1], 1):.4f} ({res[name][mk][3]}/{res[name][mk][2]}, {res[name][mk][4] / max(res[name][mk][2], 1):+.0%})" for name in CONFIGS))
