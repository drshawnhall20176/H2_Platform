import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
from datetime import datetime
import pytz
from collections import Counter
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
rows = TB.winner_rows(d)
print("ROWS", len(rows), "tested", sum(1 for r in rows if r.get("best_tested")), "leans", sum(1 for r in rows if r.get("best") and not r.get("best_tested")), Counter(r["sport"] for r in rows))
for r in sorted(rows, key=lambda r: (not r.get("best_tested"), r.get("backtest") is None, -(r.get("backtest") or 0), -(r.get("lean_z") or 0)))[:10]:
    print("  ", r["sport"], r["game"], "|", r.get("best"), "|", r.get("lean_detail"), "| tested" if r.get("best_tested") else "", r.get("backtest"), r.get("best_price"))
