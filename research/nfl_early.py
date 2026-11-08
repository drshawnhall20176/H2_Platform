"""Nov 8: the 9:30 ET NFL game -- what it is, its line, and the props model's NFL record so far."""
import os
import sys
from collections import defaultdict
from datetime import datetime

import pytz
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D     # noqa: E402
import model_store as MS     # noqa: E402

ET = pytz.timezone("US/Eastern")
sb = requests.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard", params={"dates": "20261108"},
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=20).json()
for ev in sb.get("events") or []:
    k = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
    comp = ev["competitions"][0]
    odds = (comp.get("odds") or [{}])[0]
    print("NE GAME", k.strftime("%a %-I:%M %p"), "|", ev.get("shortName"), "|", odds.get("details"), "O/U", odds.get("overUnder"),
          "|", (comp.get("venue") or {}).get("fullName"))
dates = MS.snapshot_dates("NFL")
print("NE snapshot dates", dates)
graded = D.grade_dates("NFL", dates)
by = defaultdict(lambda: [0, 0])
for d, rs in graded.items():
    for r in rs:
        if r.get("result") not in ("hit", "miss"):
            continue
        tag = r.get("use_tag") or ""
        grp = "playable" if tag.startswith(("🔒", "🎟", "🎯")) else "pass"
        for key in (("all", grp), (tag or "none", ""), (r.get("side"), grp), (r.get("market"), grp)):
            c = by[key]
            c[0] += r["result"] == "hit"
            c[1] += 1
for k, (h, n) in sorted(by.items(), key=lambda kv: -kv[1][1]):
    if n >= 15:
        print("NE REC", k, f"{h / n:.1%}", f"n={n}")
