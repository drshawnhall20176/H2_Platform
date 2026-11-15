import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import pytz, model_store as MS, long_shots_scan as L
day = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
res = L.scan("NFL", day, os.environ["ODDS_API_KEY"])
MS.save_setting(L.KEY.format(sport="NFL", date=day), res)
print("SCAN games", res["games"], "value rungs", len(res["rows"]))
for r in res["top"]:
    print("TOP", r["time"], r["game"], r["pick"], int(r["Price"]), f"{r['Honest chance']:.0%}", "tested" if r["tested"] else "")
