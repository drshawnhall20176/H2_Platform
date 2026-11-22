import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import math, todays_best as TB
d = date(2026, 11, 21); rows = []
for i in range(45):
    day = (d - timedelta(days=i)).isoformat()
    try: rows += [dict(r["_full"], _day=day) for r in TB.winner_rows(day, leagues=["NCAAMB"], past=True) if r.get("_full")]
    except Exception as e: pass
g = [r for r in rows if r.get("final_home") is not None and r.get("home_spread") is not None and r.get("model_margin") is not None]
print("graded games", len(g), "days", min(r["_day"] for r in g), "->", max(r["_day"] for r in g))
def stats(xs):
    n=len(xs); m=sum(xs)/n; sd=(sum((x-m)**2 for x in xs)/(n-1))**.5; return n, m, sd/math.sqrt(n)
act = [r["final_home"]-r["final_away"] for r in g]
merr = [r["model_margin"]-a for r,a in zip(g,act)]
berr = [-r["home_spread"]-a for r,a in zip(g,act)]
print("model home-margin error (model - actual): n=%d mean=%+.2f se=%.2f" % stats(merr))
print("book  home-margin error (book - actual):  n=%d mean=%+.2f se=%.2f" % stats(berr))
gap = [r["model_margin"]+r["home_spread"] for r in g]
print("model minus book (home pts): n=%d mean=%+.2f se=%.2f" % stats(gap))
def cover(r, a):
    x = a + r["home_spread"]; return "home" if x>0 else "away" if x<0 else "push"
for lab, f in (("all", lambda r: True), ("neutral", lambda r: r.get("neutral")), ("not neutral", lambda r: not r.get("neutral"))):
    sub=[(r,a) for r,a in zip(g,act) if f(r)]
    lh=[(r,a) for r,a in sub if r["model_margin"]+r["home_spread"]>0]; la=[(r,a) for r,a in sub if r["model_margin"]+r["home_spread"]<0]
    def rate(xs, side):
        res=[cover(r,a) for r,a in xs]; w=res.count(side); l=len([x for x in res if x not in (side,"push")]); return w,l
    hw,hl=rate(lh,"home"); aw,al=rate(la,"away")
    print(f"{lab}: games {len(sub)} | lean home {len(lh)} ({len(lh)/max(1,len(sub)):.0%}) covered {hw}-{hl} ({hw/max(1,hw+hl):.1%}) | lean away {len(la)} covered {aw}-{al} ({aw/max(1,aw+al):.1%})")
# by gap size
for lo,hi in ((0,3),(3,6),(6,10),(10,99)):
    lh=[(r,a) for r,a in zip(g,act) if lo<=r["model_margin"]+r["home_spread"]<hi]
    la=[(r,a) for r,a in zip(g,act) if lo<=-(r["model_margin"]+r["home_spread"])<hi]
    hw=sum(cover(r,a)=="home" for r,a in lh); hl=sum(cover(r,a)=="away" for r,a in lh)
    aw=sum(cover(r,a)=="away" for r,a in la); al=sum(cover(r,a)=="home" for r,a in la)
    print(f"gap {lo}-{hi}: home leans {hw}-{hl} ({hw/max(1,hw+hl):.1%}), away leans {aw}-{al} ({aw/max(1,aw+al):.1%})")
# trend by week
import collections
wk=collections.defaultdict(list)
for r,a in zip(g,act): wk[r["_day"][:8]+("1" if r["_day"][8:]<"11" else "2" if r["_day"][8:]<"21" else "3")].append(r["model_margin"]-a)
for k in sorted(wk): n,m,se=stats(wk[k]) if len(wk[k])>1 else (len(wk[k]),0,0); print("period", k, "n", n, "model err %+.2f ± %.2f" % (m, se))
