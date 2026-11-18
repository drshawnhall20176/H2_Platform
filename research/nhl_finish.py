"""Nov 18: NHL final-score shape -- OT share, final margin distribution, totals -- to calibrate game_sim's hockey draws."""
import math, os, sys, random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import postgame as PG
ds = []
for a, b in (("2025-10-07", "2026-04-16"), ("2026-10-06", (date.today() - timedelta(days=1)).isoformat())):
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    while a <= b: ds.append(a); a += timedelta(days=1)
def day(d):
    data = PG._http("https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard", {"dates": d.strftime("%Y%m%d")}) or {}
    out = []
    for ev in data.get("events") or []:
        c = (ev.get("competitions") or [{}])[0]; st = c.get("status") or {}
        if not (st.get("type") or {}).get("completed") or (ev.get("season") or {}).get("type") != 2: continue
        sc = [int(t.get("score")) for t in c.get("competitors") or []]
        if len(sc) == 2: out.append((sc[0], sc[1], st.get("period") or 3))
    return out
with ThreadPoolExecutor(10) as ex:
    games = [g for gs in ex.map(day, ds) for g in gs]
n = len(games)
ot = [g for g in games if g[2] > 3]; reg = [g for g in games if g[2] <= 3]
print(f"NF games {n} OT/SO {len(ot)/n:.1%} avg total {sum(a+b for a,b,_ in games)/n:.2f} (regulation-only avg {sum(a+b for a,b,_ in reg)/len(reg):.2f}, OT games' regulation total {sum(a+b-1 for a,b,_ in ot)/len(ot):.2f})")
mc = Counter(abs(a - b) for a, b, _ in reg)
print("NF regulation-decided margins (share of ALL games):", {k: f"{v/n:.1%}" for k, v in sorted(mc.items())})
tot_reg = [a + b for a, b, _ in reg] + [a + b - 1 for a, b, _ in ot]
m = sum(tot_reg) / n
print(f"NF regulation total mean {m:.2f} var {sum((x-m)**2 for x in tot_reg)/n:.2f} (independent Poisson var = mean)")
# fit: independent Poisson at the regulation total, + tie mix pi, + empty-net goal prob e1 (margin 1 games) / e2 (margin 2)
rnd = random.Random(3)
def pois(l):
    L = math.exp(-l); k = 0; p = 1.0
    while True:
        p *= rnd.random()
        if p <= L: return k
        k += 1
def sim(pi, e1, e2, N=60000):
    c = Counter(); ties = 0
    for _ in range(N):
        h, a = pois(m / 2), pois(m / 2)
        if h != a and rnd.random() < pi:
            s = h + a; h = s // 2; a = s - h
        if h == a: ties += 1; continue
        d = abs(h - a)
        if (d == 1 and rnd.random() < e1) or (d == 2 and rnd.random() < e2): d += 1
        c[d] += 1
    return ties / N, {k: v / N for k, v in c.items()}
target_t = len(ot) / n
best = None
for pi in (0.06, 0.08, 0.09, 0.10, 0.12):
    for e1 in (0.0, 0.2, 0.3, 0.4, 0.5):
        for e2 in (0.0, 0.2, 0.3, 0.4):
            t, dist = sim(pi, e1, e2, 20000)
            err = (t - target_t) ** 2 + sum((dist.get(k, 0) - mc.get(k, 0) / n) ** 2 for k in (1, 2, 3, 4))
            if best is None or err < best[0]: best = (err, pi, e1, e2, t, dist)
err, pi, e1, e2, t, dist = best
t, dist = sim(pi, e1, e2)
t0, d0 = sim(0, 0, 0)
print(f"NF fit: tie mix {pi} empty-net 1->2 {e1} 2->3 {e2}: OT {t:.1%} (actual {target_t:.1%}); margins", {k: f"{v:.1%}" for k, v in sorted(dist.items()) if k <= 5})
print(f"NF plain Poisson: OT {t0:.1%}; margins", {k: f"{v:.1%}" for k, v in sorted(d0.items()) if k <= 5})
