"""Nov 17: is the model overconfident where it disagrees with the market? Fit q = mkt + t*(chance - mkt) on graded
reads (t relative to what's shown), held out by later days, and look at the bet-tagged reads before/after."""
import os, sys, math
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR

GRID = [round(i * 0.02, 2) for i in range(0, 61)]       # 0 .. 1.2
def q(r, t): return min(max(r["m"] + t * (r["p"] - r["m"]), 1e-3), 1 - 1e-3)
def ll(rows, t): return -sum(math.log(q(r, t)) if r["y"] else math.log(1 - q(r, t)) for r in rows) / len(rows)
def best(rows): return min(GRID, key=lambda t: ll(rows, t))
def cal(rows, t, label):
    if not rows: return
    sh = sum(q(r, t) for r in rows) / len(rows); hit = sum(r["y"] for r in rows) / len(rows)
    print(f"     {label:28} n {len(rows):5} shown {sh:.1%} hit {hit:.1%}")

morning = "2026-11-17"
for sport in ("NBA", "NHL", "NFL", "NCAAF"):
    days = 63 if sport in ("NFL", "NCAAF") else 30
    cut = (date.fromisoformat(morning) - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sport) if cut <= d < morning]
    g = DR.grade_dates(sport, ds)
    rows = {"props": [], "td": []}
    for d, rs in g.items():
        for r in rs:
            if r.get("result") not in ("hit", "miss"): continue
            try:
                p = float(r["chance"]); pm = float(r["p_market"])
            except (TypeError, ValueError, KeyError):
                continue
            side = r.get("side")
            m = pm if side in ("Over", "Yes") else 1 - pm
            row = {"date": d, "p": p, "m": m, "y": 1 if r["result"] == "hit" else 0,
                   "bet": bool(r.get("use_tag")) and "Pass" not in str(r.get("use_tag")), "ts": str(r.get("ts"))}
            rows["td" if r.get("market") in ("Anytime TD", "1st TD", "Last TD") else "props"].append(row)
    for kind, rs in rows.items():
        if len(rs) < 200: 
            if rs: print(f"\n{sport} {kind}: only {len(rs)}"); 
            continue
        t = best(rs)
        dts = sorted({r["date"] for r in rs}); gains = []
        for c in dts[len(dts)//2:]:
            tr = [r for r in rs if r["date"] < c]; te = [r for r in rs if r["date"] >= c]
            if len(tr) < 150 or len(te) < 100: continue
            tt = best(tr); gains.append((ll(te, 1.0) - ll(te, tt), tt))
        print(f"\n{sport} {kind}: n {len(rs)} days {len(dts)}  best t {t:.2f}  logloss {ll(rs,1.0):.4f} -> {ll(rs,t):.4f}  "
              f"market-only {ll(rs,0.0):.4f} | held-out later-day splits {sum(1 for x,_ in gains if x>0)}/{len(gains)} "
              f"t's {[tt for _,tt in gains]}")
        bets = [r for r in rs if r["bet"]]
        cal(bets, 1.0, "bet-tagged as shown"); cal(bets, t, f"bet-tagged at t={t:.2f}")
        hi = [r for r in rs if r["p"] >= 0.6]; cal(hi, 1.0, "chance>=60% as shown"); cal(hi, t, f"chance>=60% at t={t:.2f}")
        # how many bet tags would survive: chance at t still clears price? approx: q - m >= 0.03
        keep = sum(1 for r in bets if q(r, t) - r["m"] >= 0.03)
        print(f"     bet-tagged that still clear market by 3pts at t: {keep}/{len(bets)}")
