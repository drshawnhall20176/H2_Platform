import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import collections, math
import model_store as MS, intl_hoops as I, todays_best as TB
games = MS.load_results("NCAAMB", since="2025-10-01")
print("results", len(games), "neutral share this season:", sum(1 for g in games if g["date"]>="2026-11-01" and str(g.get("neutral_site")).lower() in ("true","1"))/max(1,sum(1 for g in games if g["date"]>="2026-11-01")))
by_day = collections.Counter(g["date"][:10] for g in games if g["date"]>="2026-11-01")
print("games per day:", sorted(by_day.items())[-6:])
nd = collections.Counter(g["date"][:10] for g in games if g["date"]>="2026-11-01" and str(g.get("neutral_site")).lower() in ("true","1"))
print("neutral per day:", sorted(nd.items())[-10:])
for asof in ("2026-11-05","2026-11-12","2026-11-19","2026-11-22"):
    gg=[g for g in games if g["date"][:10] < asof]
    r = I.ratings_weighted(gg, I.decay_weights(gg, asof, "NCAAMB"), I.LEAGUES["NCAAMB"]["lam"], I.HFA_PRIOR["NCAAMB"])
    print(asof, "hfa %.2f mu %.1f" % (r["hfa"], r["mu"]))
# Walk-forward: model error by neutral vs not, with neutral passed or not
def wf(neutral_aware, hfa_prior=I.HFA_PRIOR["NCAAMB"], half=None, prior_w=None):
    if half: I.HALF_LIFE = half
    if prior_w is not None: I.PRIOR_SEASON_WEIGHT = prior_w
    out=[]
    d=date(2026,11,4)
    while d<=date(2026,11,21):
        ds=d.isoformat(); gg=[g for g in games if g["date"][:10] < ds]
        r = I.ratings_weighted(gg, I.decay_weights(gg, ds, "NCAAMB"), I.LEAGUES["NCAAMB"]["lam"], hfa_prior)
        for g in games:
            if g["date"][:10]!=ds: continue
            neu = str(g.get("neutral_site")).lower() in ("true","1")
            p = I.project(r, g["home_team"], g["away_team"], neutral=(neu and neutral_aware))
            if not p: continue
            out.append((ds, neu, p["margin"], g["home_points"]-g["away_points"], g["home_team"], g["away_team"]))
        d+=timedelta(days=1)
    I.HALF_LIFE=45.0; I.PRIOR_SEASON_WEIGHT=0.5
    return out
def summ(lab, out):
    def s(xs):
        n=len(xs); 
        if n<2: return f"n={n}"
        m=sum(xs)/n; sd=(sum((x-m)**2 for x in xs)/(n-1))**.5; return f"n={n} bias {m:+.2f}±{sd/math.sqrt(n):.2f} mae {sum(abs(x) for x in xs)/n:.2f}"
    e=[m-a for _,_,m,a,_,_ in out]
    print(lab, "all:", s(e), "| neutral:", s([m-a for _,n,m,a,_,_ in out if n]), "| home court:", s([m-a for _,n,m,a,_,_ in out if not n]))
    per=collections.defaultdict(list)
    for ds,n,m,a,_,_ in out: per[ds[:8]+("a" if ds[8:]<"11" else "b" if ds[8:]<"18" else "c")].append(m-a)
    print("   by period:", {k: round(sum(v)/len(v),2) for k,v in sorted(per.items())})
base = wf(False); summ("CURRENT (neutral ignored)", base)
fix = wf(True); summ("NEUTRAL PASSED", fix)
