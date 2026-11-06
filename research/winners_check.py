import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
from datetime import datetime
import pytz
from collections import Counter
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
rows = TB.winner_rows(d)
withv = [r for r in rows if r.get("best")]
print("ROWS", len(rows), "with value", len(withv), Counter(r["sport"] for r in withv), "tested", sum(r["best_tested"] for r in withv))
for r in sorted(withv, key=lambda r: -r["best_value"])[:12]:
    print("  ", r["sport"], r["game"], "|", r["best"], round(r["best_chance"], 3), r["best_price"], f"{r['best_value']:+.3f}", "tested" if r["best_tested"] else "")
