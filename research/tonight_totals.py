import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB
from datetime import datetime, timezone
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
now = datetime.now(timezone.utc)
out = []
for r in MS.load_game_picks("NCAAMB", ungraded=True):
    if TB._et_date(r.get("kickoff")) != d or r.get("line_total") is None or r.get("model_total") is None:
        continue
    k = datetime.fromisoformat(str(r["kickoff"]).replace("Z", "+00:00"))
    gap = float(r["model_total"]) - float(r["line_total"])
    if abs(gap) >= 3:
        side = "Over" if gap > 0 else "Under"
        price = r.get("over_price") if gap > 0 else r.get("under_price")
        out.append((TB._et_time(r["kickoff"]), k > now, f"{r['away']} @ {r['home']}", f"{side} {r['line_total']:g}",
                    round(r["model_total"], 1), round(gap, 1), price))
for o in sorted(out, key=lambda o: datetime.strptime(o[0], "%I:%M %p")):
    print("TOT", " | ".join(str(x) for x in o))
print("COUNT", len(out), "not started", sum(1 for o in out if o[1]))
