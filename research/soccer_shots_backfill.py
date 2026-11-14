import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, soccer_data as D
since = (date.today() - timedelta(days=500)).isoformat()
tot = 0
for lg in D.LEAGUES:
    res = MS.load_results(lg, since=since)
    have = D.cache_team_stats(lg, res, limit=3000, workers=8)
    n = sum(1 for g in res if str(g["id"]) in have)
    tot += n
    print(f"SHOTS {lg:24} results {len(res):5d} with team shots {n:5d}")
print("SHOTS total", tot)
