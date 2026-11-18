import os, sys, json, urllib.request, random
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_view as MV, kotc as K
def get(u): return json.load(urllib.request.urlopen(u, timeout=30))
sb = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261117")
act = {}
for e in sb["events"]:
    s = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={e['id']}")
    comp = e["competitions"][0]["competitors"]
    margin = abs(int(comp[0]["score"]) - int(comp[1]["score"]))
    print("GAME", e["shortName"], comp[0]["score"], comp[1]["score"])
    for t in s["boxscore"]["players"]:
        st = t["statistics"][0]; keys = st["keys"]
        for a in st["athletes"]:
            if not a.get("stats"): continue
            d = dict(zip(keys, a["stats"]))
            try: pra = int(d["points"]) + int(d["rebounds"]) + int(d["assists"])
            except Exception: continue
            act[MV.norm_name(a["athlete"]["displayName"])] = (a["athlete"]["displayName"], t["team"]["abbreviation"], pra, d.get("minutes"), d["points"], d["rebounds"], d["assists"], e["shortName"], margin)
top = sorted(act.values(), key=lambda x: -x[2])[:10]
for x in top: print("ACT", x)
reads = MV.latest_reads("NBA", "2026-11-17")
mp = K.model_pra(reads)
print("MODEL_N", len(mp))
rank = sorted(mp.items(), key=lambda kv: -kv[1])
for i, (p, v) in enumerate(rank[:15], 1): print("MODEL", i, p, round(v, 1), "actual", act.get(p, ("",))[2:4] if p in act else "DNP/none")
for x in top[:5]:
    p = MV.norm_name(x[0])
    r = [i for i, (q, _) in enumerate(rank, 1) if q == p]
    parts = {mk: (reads.get((p, mk)) or {}).get("projection") for mk in ("PRA", "Points", "Rebounds", "Assists")}
    print("WHERE", x[0], x[2], "model rank", r, "proj", parts)
# simple sim using model projections, sd 18%
rnd = random.Random(7); T = rank[:40]; w = [0]*len(T)
for _ in range(20000):
    v = [rnd.gauss(m, max(4, .18*m)) for _, m in T]; w[v.index(max(v))] += 1
for (p, m), c in sorted(zip(T, w), key=lambda z: -z[1])[:12]: print("CHANCE", p, round(m,1), round(c/20000,3))
for x in top[:3]:
    p = MV.norm_name(x[0]); print("WCHANCE", p, [round(c/20000,3) for (q, _), c in zip(T, w) if q == p])
