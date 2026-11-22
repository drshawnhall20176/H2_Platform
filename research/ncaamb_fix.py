import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import collections, math
import model_store as MS, intl_hoops as I, todays_best as TB
games = MS.load_results("NCAAMB", since="2025-10-01")
lined = []
for i in range(19):
    ds = (date(2026,11,3)+timedelta(days=i)).isoformat()
    for r in TB.winner_rows(ds, leagues=["NCAAMB"], past=True):
        f = r.get("_full") or {}
        if f.get("final_home") is not None and f.get("home_spread") is not None and f.get("model_margin") is not None:
            lined.append(dict(f, _day=ds))
print("lined games", len(lined))
def res_for(f):
    for g in games:
        if g["date"][:10] in (f["_day"], (date.fromisoformat(f["_day"])+timedelta(days=1)).isoformat()) and I.same_team(g["home_team"], f["home"]) and I.same_team(g["away_team"], f["away"]):
            return g
    return None
nm = 0
for f in lined:
    g = res_for(f); f["_neutral"] = bool(g) and str(g.get("neutral_site")).lower() in ("true","1"); nm += bool(g)
print("matched to results", nm, "neutral", sum(f["_neutral"] for f in lined))
cache = {}
def ratings_at(ds, hfa_prior, key):
    k=(ds,key)
    if k not in cache:
        gg=[g for g in games if g["date"][:10] < ds]
        cache[k]=I.ratings_weighted(gg, I.decay_weights(gg, ds, "NCAAMB"), I.LEAGUES["NCAAMB"]["lam"], hfa_prior)
    return cache[k]
def run(lab, hfa_prior, neutral_aware, fixed_hfa=None):
    errs, w, l, per = [], 0, 0, collections.defaultdict(lambda:[0,0])
    home_leans = 0; n=0; strong=[0,0]
    for f in lined:
        r = ratings_at(f["_day"], hfa_prior, str(hfa_prior))
        if fixed_hfa is not None:
            r = dict(r, hfa=fixed_hfa)
        p = I.project(r, f["home"], f["away"], neutral=(f["_neutral"] and neutral_aware), loose=False)
        if not p: continue
        act = f["final_home"]-f["final_away"]; m = p["margin"]
        errs.append(m-act)
        edge = m + f["home_spread"]; cov = act + f["home_spread"]
        if edge==0 or cov==0: continue
        n+=1; home_leans += edge>0
        hit = (edge>0)==(cov>0); w+=hit; l+=not hit
        if abs(edge)>=6: strong[0]+=hit; strong[1]+=1
        per[f["_day"][:9]+("a" if f["_day"][8:]<"11" else "b" if f["_day"][8:]<"18" else "c")][0 if hit else 1]+=1
    k=len(errs); mb=sum(errs)/k; se=(sum((x-mb)**2 for x in errs)/(k-1))**.5/math.sqrt(k)
    print(f"{lab:38s} n={k} bias {mb:+.2f}±{se:.2f} mae {sum(abs(x) for x in errs)/k:.2f} | lean home {home_leans/n:.0%} | ATS {w}-{l} {w/(w+l):.1%} | gap6+ {strong[0]}/{strong[1]} {strong[0]/max(1,strong[1]):.1%} | periods "+str({p:f'{a/(a+b):.0%}' for p,(a,b) in sorted(per.items())}))
rec_errs=[f["model_margin"]-(f["final_home"]-f["final_away"]) for f in lined]
print("AS RECORDED: bias %+.2f" % (sum(rec_errs)/len(rec_errs)))
P=I.HFA_PRIOR["NCAAMB"]
#run("current (prior 3/200, no neutral)", P, False)
#run("+ neutral at prediction", P, True)
for hv in ():
    run(f"neutral + HFA fixed {hv} (fit as now)", P, True, fixed_hfa=hv)
#run("neutral + prior 3.2/20000 (refit)", (3.2, 20000.0), True)

print("---- close games (|book spread| <= 10) and win-chance accuracy ----")
def run2(lab, hfa_prior, neutral_aware):
    e, ll, br, n = [], 0.0, 0.0, 0
    for f in lined:
        if abs(f["home_spread"]) > 10: continue
        r = ratings_at(f["_day"], hfa_prior, str(hfa_prior))
        p = I.project(r, f["home"], f["away"], neutral=(f["_neutral"] and neutral_aware))
        if not p: continue
        act = f["final_home"]-f["final_away"]; e.append(p["margin"]-act)
        q = I.win_prob(p["margin"], league="NCAAMB"); y = 1.0 if act > 0 else 0.0
        q = min(max(q, 1e-4), 1-1e-4); ll -= y*math.log(q)+(1-y)*math.log(1-q); br += (q-y)**2; n += 1
    k=len(e); mb=sum(e)/k; se=(sum((x-mb)**2 for x in e)/(k-1))**.5/math.sqrt(k)
    print(f"{lab:38s} close games n={k} bias {mb:+.2f}±{se:.2f} mae {sum(abs(x) for x in e)/k:.2f} | win-chance log loss {ll/n:.4f} brier {br/n:.4f}")
run2("current", P, False)
run2("neutral only", P, True)
run2("neutral + prior 3.2/20000", (3.2, 20000.0), True)
run2("neutral + prior 4.0/20000", (4.0, 20000.0), True)
