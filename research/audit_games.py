import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math, model_store as MS
from datetime import date, timedelta
since = (date(2026,11,22) - timedelta(days=30)).isoformat()
LG = ["NCAAMB","NBA","NHL","NFL","NCAAF","EUROLEAGUE","EUROCUP","BCL","FEC","NKL","NBL","ICELAND","BAHRAIN","ESTONIA1","QATAR","EUROCUPW","WNBA","TENNIS","SOCCER","EPL","UFC","MLB"]
def ms(xs):
    n=len(xs)
    if n<2: return (n, None, None)
    m=sum(xs)/n; sd=(sum((x-m)**2 for x in xs)/(n-1))**.5; return (n, m, sd/math.sqrt(n))
def fmt(t): n,m,se=t; return f"n={n}" if m is None else f"{m:+.2f}±{se:.2f} (n={n})"
for lg in LG:
    try: recs = MS.load_game_picks(lg)
    except Exception: recs = []
    g = [r for r in recs if str(r.get("kickoff") or "")[:10] >= since and r.get("final_home") is not None and r.get("model_margin") is not None]
    if len(g) < 15:
        if recs: print(f"{lg}: only {len(g)} graded games in 30 days (stored {len(recs)})")
        continue
    act=[float(r["final_home"])-float(r["final_away"]) for r in g]; mm=[float(r["model_margin"]) for r in g]
    err=[m-a for m,a in zip(mm,act)]
    # dispersion: regression slope of actual on model margin (1 = right size; <1 = too extreme; >1 = too timid)
    mx=sum(mm)/len(mm); my=sum(act)/len(act); sxx=sum((x-mx)**2 for x in mm); slope=sum((x-mx)*(y-my) for x,y in zip(mm,act))/sxx if sxx else None
    # vs book: slope of actual on book margin, and of (actual - book) on (model - book)
    lined=[(r, a) for r,a in zip(g,act) if r.get("home_spread") is not None]
    disp_vs_book=None
    if len(lined)>=15:
        d=[(float(r["model_margin"])+float(r["home_spread"])) for r,_ in lined]; y=[a+float(r["home_spread"]) for r,a in lined]
        dx=sum(d)/len(d); dy=sum(y)/len(y); sdd=sum((x-dx)**2 for x in d)
        disp_vs_book = sum((x-dx)*(v-dy) for x,v in zip(d,y))/sdd if sdd else None
    close=[e for r,e in zip(g,err) if (abs(float(r["home_spread"])) if r.get("home_spread") is not None else abs(float(r["model_margin"]))) <= (10 if lg not in ("NFL","NCAAF","NHL","TENNIS","SOCCER") else 7 if lg in ("NFL","NCAAF") else 1.5)]
    tot=[float(r["model_total"])-(float(r["final_home"])+float(r["final_away"])) for r in g if r.get("model_total") is not None]
    # calibration of home win chance
    cal=[]
    for lo,hi in ((0,.35),(.35,.5),(.5,.65),(.65,.8),(.8,1.01)):
        b=[(float(r.get("model_p")), 1.0 if a>0 else 0.0) for r,a in zip(g,act) if r.get("model_p") is not None and lo<=float(r["model_p"])<hi and a!=0]
        if len(b)>=10: cal.append(f"{lo:.2f}-{hi:.2f}: said {sum(p for p,_ in b)/len(b):.0%} hit {sum(y for _,y in b)/len(b):.0%} (n={len(b)})")
    print(f"{lg}: graded {len(g)} | home bias all {fmt(ms(err))} close {fmt(ms(close))} | margin slope {slope:.2f}" + (f" | vs-book disagreement slope {disp_vs_book:.2f} (1=right, 0=no info, <0=wrong way)" if disp_vs_book is not None else "") + f" | total bias {fmt(ms(tot))}")
    for c in cal: print("     cal", c)
