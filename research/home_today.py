import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
rs=[r["_full"] for r in TB.winner_rows("2026-11-22", leagues=["NCAAMB"]) if r.get("_full") and r["_full"].get("model_margin") is not None and r["_full"].get("home_spread") is not None]
e=[r["model_margin"]+r["home_spread"] for r in rs]
print("today games", len(rs), "lean home", sum(x>0 for x in e), "lean away", sum(x<0 for x in e), "avg model-minus-book home %+.2f" % (sum(e)/len(e)))
