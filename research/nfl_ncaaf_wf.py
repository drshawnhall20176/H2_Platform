import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math, collections, model_store as MS, intl_hoops as I
from datetime import date, timedelta
def s(xs):
    n=len(xs)
    if n<2: return f"n={n}"
    m=sum(xs)/n; sd=(sum((x-m)**2 for x in xs)/(n-1))**.5; return f"n={n} {m:+.2f}±{sd/math.sqrt(n):.2f}"
games=MS.load_results("NFL", since="2024-08-01")
cfg=I.LEAGUES["NFL"]; days=sorted({g["date"][:10] for g in games if g["date"]>="2026-09-01"})
err=[]; neu=[]
for ds in days:
    gg=[g for g in games if g["date"][:10]<ds]
    r=I.ratings_weighted(gg, I.decay_weights(gg, ds, "NFL"), cfg["lam"], I.HFA_PRIOR.get("NFL")) if cfg.get("decay") else None
    for g in games:
        if g["date"][:10]!=ds: continue
        n=str(g.get("neutral_site")).lower() in ("true","1")
        p=I.project(r, g["home_team"], g["away_team"], neutral=n)
        if not p: continue
        e=p["margin"]-(g["home_points"]-g["away_points"]); err.append(e); (neu.append(e) if n else None)
print("NFL walk-forward 2026:", s(err), "| neutral games", s(neu), "| first half", s(err[:len(err)//2]), "second half", s(err[len(err)//2:]))
# NCAAF: stored picks by size of the model's margin, by month, and vs FCS
picks=[p for p in MS.load_game_picks("NCAAF") if p.get("final_home") is not None and p.get("model_margin") is not None and str(p.get("kickoff") or "")[:10]>="2026-08-01"]
def e(p): return p["model_margin"]-(p["final_home"]-p["final_away"])
print("NCAAF all", s([e(p) for p in picks]))
for lo,hi in ((0,7),(7,14),(14,28),(28,99)):
    print(f"  model margin |{lo}-{hi}|:", s([e(p) for p in picks if lo<=abs(p["model_margin"])<hi]))
by=collections.defaultdict(list)
for p in picks: by[str(p["kickoff"])[:7]].append(e(p))
print("  by month:", {k: s(v) for k,v in sorted(by.items())})
print("  neutral:", s([e(p) for p in picks if p.get("neutral")]), "home field:", s([e(p) for p in picks if not p.get("neutral")]))
print("  sample keys:", sorted(picks[0].keys())[:40] if picks else None)
