import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
import todays_best as TB
d = date(2026, 11, 21); rows = []
for i in range(40):
    day = (d - timedelta(days=i)).isoformat()
    try: rows += [dict(r, _day=day) for r in TB.winner_rows(day, leagues=["NCAAMB"], past=True)]
    except Exception as e: print(day, e)
print("rows", len(rows))
if rows: print(sorted(rows[0].keys()))
import json
print(json.dumps({k: rows[0].get(k) for k in list(rows[0].keys())[:60]}, default=str)[:2500] if rows else "")
