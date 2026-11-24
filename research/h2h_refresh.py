import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import h2h, json, model_store as MS
h2h.refresh()
for lg in h2h.SITE:
    k = f"{lg}|2026-11-24"; raw = MS.load_blobs(h2h.KIND, [k]).get(k)
    d = json.loads(raw) if raw else {}
    print(lg, len(d), list(d.items())[:3])
