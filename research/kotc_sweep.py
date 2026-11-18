"""Nov 18: King of the Court -- old sim (top 40 by projection, normal 18% spread) vs a full-field sim that draws each
player's night from how players at his projection level actually finished vs the model (leave-one-night-out).
Every NBA night with saved reads (the PRA-leader question is the same any night; 5 were Tuesdays)."""
import os, sys, json, math, random, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, model_view as MV, kotc as K
from datetime import date
def get(u):
    try: return json.load(urllib.request.urlopen(u, timeout=30))
    except Exception: return {}
def box(d):
    sb = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d.replace('-', '')}")
    out = {}
    for e in sb.get("events", []):
        s = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={e['id']}")
        for t in (s.get("boxscore") or {}).get("players", []):
            st = t["statistics"][0]; keys = st["keys"]
            for a in st["athletes"]:
                if not a.get("stats"): continue
                dd = dict(zip(keys, a["stats"]))
                try: out[MV.norm_name(a["athlete"]["displayName"])] = (int(dd["points"]) + int(dd["rebounds"]) + int(dd["assists"]), a["athlete"]["displayName"])
                except Exception: pass
    return out
nights = [d for d in MS.snapshot_dates("NBA") if d < date.today().isoformat()]
with ThreadPoolExecutor(6) as ex:
    boxes = dict(zip(nights, ex.map(box, nights)))
data = {}
for d in nights:
    mp = K.model_pra(MV.latest_reads("NBA", d))
    b = boxes[d]
    if not b or not mp: continue
    played = {p: v for p, v in mp.items() if p in b}
    top = max(x[0] for x in b.values())
    winners = [p for p, x in b.items() if x[0] == top]
    data[d] = {"proj": played, "act": {p: b[p][0] for p in played}, "winners": winners, "top": top,
               "names": [b[w][1] for w in winners], "listed": [w in played for w in winners], "n_box": len(b)}
    print("NIGHT", d, date.fromisoformat(d).strftime("%a"), "players w/ model PRA", len(played), "of", len(b), "| winner", data[d]["names"], top,
          "| had a read:", data[d]["listed"])
BKT = [0, 15, 25, 35, 999]
def bk(x): return next(i for i in range(4) if BKT[i] <= x < BKT[i + 1])
def pool_without(d):
    pool = defaultdict(list)
    for dd, v in data.items():
        if dd == d: continue
        for p, pr in v["proj"].items():
            if pr > 0: pool[bk(pr)].append(v["act"][p] / pr)
    return pool
SIMS = 20000
def sim_old(proj, rnd):
    top = sorted(proj.items(), key=lambda kv: -kv[1])[:40]
    w = defaultdict(int)
    for _ in range(SIMS):
        best = max(top, key=lambda kv: rnd.gauss(kv[1], max(4.0, 0.18 * kv[1])) if False else 0) if False else None
        vals = [(rnd.gauss(m, max(4.0, 0.18 * m)), p) for p, m in top]
        w[max(vals)[1]] += 1
    return {p: w[p] / SIMS for p in proj}
def sim_new(proj, pool, rnd):
    items = list(proj.items())
    pools = [pool[bk(m)] for _, m in items]
    w = defaultdict(int)
    for _ in range(SIMS):
        best, bp = -1, None
        for (p, m), pl in zip(items, pools):
            v = m * pl[int(rnd.random() * len(pl))]
            if v > best: best, bp = v, p
        w[bp] += 1
    return {p: w[p] / SIMS for p in proj}
SIMS = 8000
rnd = random.Random(7)
def sim_s(proj, pool, rnd, sh):
    items = list(proj.items()); pools = [pool[bk(m)] for _, m in items]
    w = defaultdict(int)
    for _ in range(SIMS):
        best, bp = -1, None
        for (p, m), pl in zip(items, pools):
            v = m * (1 + sh * (pl[int(rnd.random() * len(pl))] - 1))
            if v > best: best, bp = v, p
        w[bp] += 1
    return {p: w[p] / SIMS for p in proj}
for sh in (0.6, 0.7, 0.8, 0.9, 1.0):
    rs = []
    for d, v in data.items():
        ch = sim_s(v["proj"], pool_without(d), rnd, sh)
        order = sorted(ch, key=ch.get, reverse=True)
        rs.append({"pw": sum(ch.get(w, 0) for w in v["winners"]), "pfav": ch[order[0]], "fav_won": order[0] in v["winners"],
                   "top5": sum(ch[p] for p in order[:5]), "in5": any(w in order[:5] for w in v["winners"]),
                   "tue": date.fromisoformat(d).weekday() == 1})
    n = len(rs)
    print(f"SWEEP spread x{sh}: log score {-sum(math.log(max(r['pw'],1e-3)) for r in rs)/n:.3f} | favorite said {sum(r['pfav'] for r in rs)/n:.0%} won {sum(r['fav_won'] for r in rs)}/{n}"
          f" | top-5 said {sum(r['top5'] for r in rs)/n:.0%} won {sum(r['in5'] for r in rs)}/{n} | Tuesdays log {-sum(math.log(max(r['pw'],1e-3)) for r in rs if r['tue'])/max(1,sum(r['tue'] for r in rs)):.3f}")
pool = pool_without(None)
for i in range(4):
    xs = sorted(pool[i])
    if xs: print("QUANT", i, [round(xs[int(q * (len(xs) - 1))], 3) for q in [j / 20 for j in range(21)]])
