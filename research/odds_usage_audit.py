"""Nov 20: Odds API credit use by day and job (last 10 days) + the money rules in force."""
import sys
from collections import defaultdict
from datetime import date, timedelta
sys.path.insert(0, ".")
import model_store as MS
rows = MS.odds_usage((date.today() - timedelta(days=10)).isoformat())
byday = defaultdict(int); byjob = defaultdict(lambda: defaultdict(int))
for r in rows:
    byday[r["day"]] += r["credits"] or 0
    byjob[r["day"]][r["job"]] += r["credits"] or 0
for d in sorted(byday):
    top = sorted(byjob[d].items(), key=lambda kv: -kv[1])[:6]
    print(f"ODDS {d}: total={byday[d]} " + ", ".join(f"{j}={c}" for j, c in top))
print("ODDS MONEY", MS.get_setting("money:rules", None))
