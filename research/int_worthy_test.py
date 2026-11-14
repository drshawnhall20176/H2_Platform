"""Nov 14 -- NFL interceptions: does "interception-worthy throws" (FTN charting via nflverse: picks + dropped picks +
near picks) predict a QB's next-game interceptions better than his interceptions? Walk-forward, starters (15+ att)."""
import math, os, sys
from collections import defaultdict
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import nflreadpy as nfl

seasons = [2022, 2023, 2024, 2025, 2026]
ftn, pbp = [], []
for s in seasons:
    try:
        f = nfl.load_ftn_charting([s]).to_pandas()
        ftn.append(f); print("ftn", s, len(f), list(f.columns)[:30])
    except Exception as exc:
        print("ftn", s, "unavailable", type(exc).__name__, str(exc)[:100])
    try:
        p = nfl.load_pbp([s]).to_pandas()[["game_id", "play_id", "season", "week", "season_type", "passer_player_id",
                                           "passer_player_name", "pass_attempt", "interception", "sack", "posteam"]]
        pbp.append(p); print("pbp", s, len(p))
    except Exception as exc:
        print("pbp", s, "unavailable", type(exc).__name__, str(exc)[:100])
import pandas as pd
ftn = pd.concat(ftn); pbp = pd.concat(pbp)
m = pbp.merge(ftn[["nflverse_game_id", "nflverse_play_id", "is_interception_worthy"]],
              left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "nflverse_play_id"], how="inner")
m = m[(m["pass_attempt"] == 1) & (m["sack"] != 1) & m["passer_player_id"].notna()]
m["iw"] = m["is_interception_worthy"].fillna(False).astype(bool).astype(int)
m["intc"] = m["interception"].fillna(0).astype(int)
print("charted pass attempts", len(m), "INT", m["intc"].sum(), "INT-worthy", m["iw"].sum(),
      "INT that were INT-worthy", int(((m["intc"] == 1) & (m["iw"] == 1)).sum()))
g = m.groupby(["season", "week", "game_id", "passer_player_id", "passer_player_name"]).agg(att=("pass_attempt", "sum"),
      ints=("intc", "sum"), iw=("iw", "sum")).reset_index()
g = g[g["att"] >= 15].sort_values(["passer_player_id", "season", "week"])
lg_int = g["ints"].sum() / g["att"].sum(); lg_iw = g["iw"].sum() / g["att"].sum()
c = g["ints"].sum() / g["iw"].sum()
print(f"QB-games {len(g)}; league INT/att {lg_int:.4f}, INT-worthy/att {lg_iw:.4f}, INT per INT-worthy {c:.3f}")

# stability (split-half, first 10 starts)
a = defaultdict(list)
for r in g.itertuples(): a[(r.season, r.passer_player_id)].append(r)
def split(col):
    x, y = [], []
    for v in a.values():
        if len(v) < 10: continue
        h1, h2 = v[:10:2], v[1:10:2]
        x.append(sum(getattr(q, col) for q in h1) / sum(q.att for q in h1)); y.append(sum(getattr(q, col) for q in h2) / sum(q.att for q in h2))
    return float(np.corrcoef(x, y)[0, 1]), len(x)
print("split-half r (5 starts vs 5 starts): INT rate %.2f, INT-worthy rate %.2f (n=%d)" % (split("ints")[0], split("iw")[0], split("iw")[1]))

def pois_ge(lam, k):
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))
results = defaultdict(lambda: {"se": 0.0, "b05": 0.0, "b15": 0.0, "ll": 0.0, "n": 0})
by = defaultdict(list)
for r in g.itertuples(): by[r.passer_player_id].append(r)
for games in by.values():
    for i in range(3, len(games)):
        prev = games[max(0, i - 16):i]; cur = games[i]
        att = sum(q.att for q in prev); ints = sum(q.ints for q in prev); iw = sum(q.iw for q in prev)
        models = {}
        for K in (120, 400, 1200, 3000):
            models[f"INT only, K={K}"] = (ints + lg_int * K) / (att + K)
        for K in (0, 100, 200, 400, 800):
            models[f"INT-worthy, K={K}"] = c * (iw + lg_iw * K) / (att + K)
        for K in (200, 400, 800):
            models[f"half INT + half worthy, K={K}"] = 0.5 * (ints + lg_int * K) / (att + K) + 0.5 * c * (iw + lg_iw * K) / (att + K)
        models["league average"] = lg_int
        y = cur.ints
        for name, rate in models.items():
            lam = max(rate * cur.att, 1e-6)
            p05, p15 = pois_ge(lam, 1), pois_ge(lam, 2)
            R = results[name]
            R["se"] += (lam - y) ** 2; R["b05"] += (p05 - (y >= 1)) ** 2; R["b15"] += (p15 - (y >= 2)) ** 2
            R["ll"] += -(y * math.log(lam) - lam - math.lgamma(y + 1)); R["n"] += 1
for name, R in sorted(results.items(), key=lambda kv: kv[1]["ll"]):
    n = R["n"]
    print(f"IW {name:32} n={n} rmse {math.sqrt(R['se'] / n):.4f} brier(1+) {R['b05'] / n:.4f} brier(2+) {R['b15'] / n:.4f} logloss {R['ll'] / n:.4f}")
os.makedirs("research_out", exist_ok=True)
g.to_csv("research_out/qb_int_worthy.csv", index=False)
