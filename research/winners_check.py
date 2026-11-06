import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
from datetime import datetime
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
rows = TB.winner_rows(d)
from collections import Counter
print("ROWS", len(rows), Counter(r["sport"] for r in rows))
for r in rows[:8]:
    print("  ", r["sport"], r["game"], "->", r["winner"], round(r["chance"], 3), r["book"] and round(r["book"], 3), r["price"], r["value"] and round(r["value"], 3))
for sp, a in TB.winner_record().items():
    print("REC", sp, a["n"], round(a["won"] / a["n"], 3), {f"{lo:.0%}": (n, round(w / n, 3) if n else None) for (lo, hi), (n, w) in a["bands"].items()})
