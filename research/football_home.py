import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math, model_store as MS, intl_hoops as I
from datetime import date
def s(xs):
    n=len(xs)
    if n<2: return f"n={n}"
    m=sum(xs)/n; sd=(sum((x-m)**2 for x in xs)/(n-1))**.5; return f"n={n} {m:+.2f}±{sd/math.sqrt(n):.2f}"
for lg in ("NFL", "NCAAF", "NBA", "NHL"):
    try:
        picks = MS.load_game_picks(lg) if hasattr(MS, "load_game_picks") else []
    except Exception as e:
        picks = []; print(lg, "load_game_picks failed", e)
    g = [p for p in picks if p.get("final_home") is not None and p.get("model_margin") is not None and str(p.get("kickoff") or "")[:10] >= "2026-09-01"]
    err=[p["model_margin"]-(p["final_home"]-p["final_away"]) for p in g]
    lined=[p for p in g if p.get("home_spread") is not None]
    close=[p["model_margin"]-(p["final_home"]-p["final_away"]) for p in lined if abs(p["home_spread"])<=(7 if lg in ("NFL","NCAAF") else 10 if lg=="NBA" else 1.5)]
    neu=[p["model_margin"]-(p["final_home"]-p["final_away"]) for p in g if p.get("neutral")]
    cov=lambda p: (p["final_home"]-p["final_away"])+p["home_spread"]
    lh=[p for p in lined if p["model_margin"]+p["home_spread"]>0]; la=[p for p in lined if p["model_margin"]+p["home_spread"]<0]
    print(f"{lg}: graded {len(g)} | model-minus-actual {s(err)} | close lined {s(close)} | neutral {s(neu)} | lean home {len(lh)}/{len(lined)} covered {sum(cov(p)>0 for p in lh)}-{sum(cov(p)<0 for p in lh)}, away {sum(cov(p)<0 for p in la)}-{sum(cov(p)>0 for p in la)}")
# fitted home court now, every league on the hoops machinery
for lg in ("NBA","NHL","NFL","WNBA"):
    try:
        cfg=I.LEAGUES[lg]; games=MS.load_results(lg, since="2025-08-01")
        today=date.today().isoformat()
        r=I.ratings_weighted(games, I.decay_weights(games, today, lg), cfg["lam"], I.HFA_PRIOR.get(lg)) if cfg.get("decay") else I.ratings([g for g in games if str(g.get("season"))==I.season_of(lg,today)], cfg["lam"])
        print(lg, "fitted home court", None if not r else round(r["hfa"],2), "prior", I.HFA_PRIOR.get(lg), "games", len(games))
    except Exception as e: print(lg, "fit failed", type(e).__name__, e)
import game_picks as GP
try:
    print("NCAAF game_picks home court:", {k: getattr(GP, k) for k in dir(GP) if "HFA" in k.upper() or "HOME" in k.upper()})
except Exception as e: print(e)
