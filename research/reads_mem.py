import sys, os, subprocess, json
sys.path.insert(0, ".")
CHILD = r'''
import sys, time, resource
sys.path.insert(0, ".")
import best_bets_data as BBD, slate_store as SS
SS._in_app = lambda: True
BBD._in_app = lambda: True
sp, d = sys.argv[1], sys.argv[2]
t = time.time()
try:
    r = BBD.load_slate_reads(sp, d, BBD.O.DEFAULT_BOOK)
    n = len(r or {})
except Exception as e:
    n = f"ERR {type(e).__name__}: {e}"
print(f"RM {sp} {d}: reads={n} peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e3:.0f}MB t={time.time()-t:.0f}s")
'''
from datetime import datetime, timedelta
import pytz
today = datetime.now(pytz.timezone("US/Eastern")).date()
for sp, d in (("NBA", today), ("NHL", today), ("NFL", today + timedelta(days=1)), ("NBA", today + timedelta(days=1))):
    out = subprocess.run([sys.executable, "-c", CHILD, sp, d.isoformat()], capture_output=True, text=True, timeout=1500)
    print([l for l in out.stdout.splitlines() if l.startswith("RM ")] or out.stderr[-400:])
