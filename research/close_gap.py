import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pick_ledger as PL, model_store as MS
from collections import Counter
caps = MS.get_setting("LEDGER_CLOSE:2026-11-22") or {}
print("captures", len(caps))
c = Counter()
for kind, sp in [("strong","ALL"),("hot","ALL")]+[("money",s) for s in ("NBA","NHL","NFL","NCAAF","NCAAMB")]:
    for k, r in (PL.load(kind, sp, "2026-11-22") or {}).get("rows", {}).items():
        c[(r.get("sport") or sp, r.get("time"), bool(r.get("watched_close")) , r.get("close_price") is not None, r.get("clv_mark") is not None)] += 1
for k, v in sorted(c.items(), key=lambda x: str(x)): print(k, v)
