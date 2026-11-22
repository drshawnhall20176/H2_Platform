import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import math, todays_best as TB
for lg in ("NBA", "NHL", "NFL", "NCAAF", "WNBA"):
    rows = []
    for i in range(45):
        ds = (date(2026,11,21)-timedelta(days=i)).isoformat()
        try: rows += [dict(r["_full"], _day=ds) for r in TB.winner_rows(ds, leagues=[lg], past=True) if r.get("_full")]
        except Exception: pass
    g = [r for r in rows if r.get("final_home") is not None and r.get("home_spread") is not None and r.get("model_margin") is not None]
    if len(g) < 5:
        print(lg, "graded lined games:", len(g)); continue
    def s(xs):
        n=len(xs); m=sum(xs)/n; sd=(sum((x-m)**2 for x in xs)/max(1,n-1))**.5; return f"n={n} {m:+.2f}±{sd/math.sqrt(n):.2f}"
    err=[r["model_margin"]-(r["final_home"]-r["final_away"]) for r in g]
    gap=[r["model_margin"]+r["home_spread"] for r in g]
    close=[r["model_margin"]-(r["final_home"]-r["final_away"]) for r in g if abs(r["home_spread"])<= (10 if lg in ("NBA","WNBA") else 7 if lg in ("NFL","NCAAF") else 1.5)]
    lh=[r for r in g if r["model_margin"]+r["home_spread"]>0]; la=[r for r in g if r["model_margin"]+r["home_spread"]<0]
    cov=lambda r: (r["final_home"]-r["final_away"])+r["home_spread"]
    hw=sum(cov(r)>0 for r in lh); hl=sum(cov(r)<0 for r in lh); aw=sum(cov(r)<0 for r in la); al=sum(cov(r)>0 for r in la)
    half=sorted(g, key=lambda r:r["_day"]); mid=len(half)//2
    e1=[r["model_margin"]-(r["final_home"]-r["final_away"]) for r in half[:mid]]; e2=[r["model_margin"]-(r["final_home"]-r["final_away"]) for r in half[mid:]]
    print(f"{lg}: {min(r['_day'] for r in g)}..{max(r['_day'] for r in g)} | model-minus-actual (home) {s(err)} | close games {s(close) if len(close)>1 else len(close)} | model-minus-book {s(gap)} | lean home {len(lh)/len(g):.0%}: covered {hw}-{hl}, away {aw}-{al} | first half {s(e1)}, second half {s(e2)}")
