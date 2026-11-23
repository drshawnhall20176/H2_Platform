import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
from datetime import date, timedelta
out = []
d = date(2026, 11, 5)
while d <= date(2026, 11, 22):
    try:
        rows = TB.winner_rows(d.isoformat(), leagues=["NCAAMB"], past=True)
    except Exception as e:
        print("err", d, e); rows = []
    for r in rows:
        f = r.get("_full") or {}
        if f.get("final_home") is None: continue
        out.append({"day": d.isoformat(), "edge": f.get("edge"), "hs": f.get("home_spread"), "neutral": f.get("neutral"),
                    "chance": r.get("chance"), "price": r.get("price"), "mp": r.get("money_price"), "mm": r.get("money_market"),
                    "ms": r.get("money_score"), "mc": r.get("money_chance"),
                    "mr": r.get("money_result"), "lr": r.get("best_result"), "wr": r.get("winner_result"),
                    "fm": f["final_home"] - f["final_away"], "mod": f.get("model_margin")})
    d += timedelta(days=1)
print("N", len(out))
for i in range(0, len(out), 40): print("JSON" + json.dumps(out[i:i+40]))
