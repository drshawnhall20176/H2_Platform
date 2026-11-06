import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB
from datetime import datetime, timezone
import pytz
from collections import Counter
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
now = datetime.now(timezone.utc)
sp = []
for r in MS.load_game_picks("NCAAMB", ungraded=True):
    if TB._et_date(r.get("kickoff")) != d:
        continue
    if datetime.fromisoformat(str(r["kickoff"]).replace("Z", "+00:00")) <= now:
        continue
    if r.get("cover_est") is not None and r.get("edge") is not None and r.get("home_spread") is not None:
        home = r["edge"] >= 0
        lab = f"{r['home']} {r['home_spread']:+g}" if home else f"{r['away']} {-r['home_spread']:+g}"
        sp.append((float(r["cover_est"]), round(abs(r["edge"]), 1), TB._et_time(r["kickoff"]), lab, r.get("spread_price"), r.get("use")))
print("COVER DIST", Counter(round(x[0], 3) for x in sp).most_common(8))
for x in sorted(sp, key=lambda x: -x[0])[:8]:
    print("SP", " | ".join(str(v) for v in x))
