import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import pytz
import todays_best as TB
d = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
rows = TB.blowout_rows(d)
print("BLOW", d, len(rows))
for r in rows[:12]:
    print("BLOW", r["sport"], r["time"], "|", r["game"], "|", r["team"], r["who"], f"{r['chance']:.0%}", "| close", f"{r['close']:.0%}", "|", r["line"], r["margin"])
