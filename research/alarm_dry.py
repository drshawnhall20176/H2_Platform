import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data_checks as DC, model_store as MS, pick_ledger as PL
from datetime import date, timedelta
since = "2026-11-08"
for lg in DC.BIAS_LEAGUES:
    recs = [r for r in MS.load_game_picks(lg) if str(r.get("kickoff") or "")[:10] >= since and r.get("final_home") is not None and r.get("model_margin") is not None]
    n = len(recs)
    if n < 3: print(lg, n); continue
    pairs = [(float(r["model_margin"]), float(r["final_home"]) - float(r["final_away"])) for r in recs]
    mx = sum(a for a, _ in pairs)/n; my = sum(b for _, b in pairs)/n
    sxx = sum((a-mx)**2 for a, _ in pairs); sl = sum((a-mx)*(b-my) for a, b in pairs)/sxx if sxx else None
    tots = [float(r["model_total"]) - float(r["final_home"]) - float(r["final_away"]) for r in recs if r.get("model_total") is not None]
    bias = sum(a-b for a, b in pairs)/n
    print(lg, "n", n, "bias %+.2f" % bias, "slope", sl and round(sl, 2), "tot n", len(tots), "tot err %+.2f" % (sum(tots)/len(tots) if tots else 0))
groups = {}
d = date(2026, 11, 8)
while d < date(2026, 11, 22):
    for kind, sp in [("strong", "ALL"), ("hot", "ALL")] + [("money", s) for s in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")]:
        for k, r in (PL.load(kind, sp, d.isoformat()) or {}).get("rows", {}).items():
            if r.get("result") not in ("win", "loss"): continue
            ch = r.get("earned") if r.get("earned") is not None else r.get("chance")
            key = (r.get("sport") or sp, "pickem" if (r.get("pickem_only") or r.get("price") is None) else "book", ch is not None)
            g = groups.setdefault(key, [0, 0, 0.0]); g[0] += 1; g[1] += r["result"] == "win"; g[2] += ch or 0
    d += timedelta(days=1)
for k, (n, w, c) in sorted(groups.items()): print("SHOWN", k, n, "hit %.2f" % (w/n), "said %.2f" % (c/n))
print("keys sample", list((PL.load("strong", "ALL", "2026-11-21") or {}).get("rows", {}).values())[:1])
